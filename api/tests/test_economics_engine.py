import numpy as np
import pytest
from pydantic import ValidationError

from app.engines.economics import UnitEconomics, beta_update, calculate_economics, calculate_value_of_information, sample_size_proportion, scenario_percentiles, simulate_economics, unit_economics
from app.schemas.economics import ParameterProvenance

def test_parameter_provenance_requires_consistent_flags_and_trusted_references():
    assert ParameterProvenance(source_type="verified_evidence", source_id="evidence-1", observed=True).observed
    assert ParameterProvenance(source_type="benchmark", source_id="benchmark-1", benchmark=True).benchmark
    assert ParameterProvenance(source_type="inference", source_id="model-1", inferred=True).inferred
    with pytest.raises(ValidationError):
        ParameterProvenance(source_type="verified_evidence", source_id="evidence-1", benchmark=True)
    with pytest.raises(ValidationError):
        ParameterProvenance(source_type="benchmark", benchmark=True)
    with pytest.raises(ValidationError):
        ParameterProvenance(source_type="user_input", observed=True)


def test_unresolved_caller_source_ids_cannot_make_simulation_reliable():
    scenario = {
        "price": {"kind": "fixed", "value": 100}, "variable_cost": {"kind": "fixed", "value": 20},
        "monthly_churn": {"kind": "fixed", "value": .1}, "cac": {"kind": "fixed", "value": 120},
        "fixed_monthly_cost": {"kind": "fixed", "value": 0},
        "parameter_provenance": {
            field: {"source_type": "verified_evidence", "source_id": "999", "confidence": "HIGH", "observed": True}
            for field in ("price", "variable_cost", "monthly_churn", "cac", "fixed_monthly_cost")
        },
    }
    heuristic = simulate_economics([scenario], iterations=1)
    assert heuristic["reliability"] == "HEURISTIC"
    assert heuristic["scenarios"][0]["value_of_information"]["status"] == "HEURISTIC"
    assert simulate_economics([scenario], iterations=1, trusted_source_ids={"verified_evidence": {"999"}})["reliability"] == "RELIABLE"


def test_calculated_economics_gates_target_ratio_provenance():
    scenario = {"price": 100, "variable_cost": 20, "monthly_churn": .1, "cac": 120, "fixed_monthly_cost": 0, "target_ltv_cac_ratio": 3}
    fields = ("price", "variable_cost", "monthly_churn", "cac", "fixed_monthly_cost", "target_ltv_cac_ratio")
    scenario["parameter_provenance"] = {
        field: {"source_type": "verified_evidence", "source_id": "1", "confidence": "HIGH", "observed": True}
        for field in fields
    }
    assert calculate_economics([scenario], trusted_source_ids={"verified_evidence": {"1"}})["reliability"] == "RELIABLE"
    del scenario["parameter_provenance"]["target_ltv_cac_ratio"]
    assert calculate_economics([scenario], trusted_source_ids={"verified_evidence": {"1"}})["reliability"] == "HEURISTIC"


def test_reliability_checks_resolved_source_quality_and_freshness_and_exposes_deterministic_voi():
    scenario = {"price": 100, "variable_cost": 20, "monthly_churn": .1, "cac": 120, "fixed_monthly_cost": 0, "target_ltv_cac_ratio": 3}
    fields = ("price", "variable_cost", "monthly_churn", "cac", "fixed_monthly_cost", "target_ltv_cac_ratio")
    scenario["parameter_provenance"] = {field: {"source_type": "verified_evidence", "source_id": "1", "confidence": "HIGH", "observed": True} for field in fields}
    metadata = {("verified_evidence", "1"): {"source_quality": .6, "freshness": 1}}
    result = calculate_economics([scenario], capital_steps=[{"name": "test", "amount": 25}], trusted_source_ids={"verified_evidence": {"1"}}, trusted_source_metadata=metadata)
    assert result["reliability"] == "HEURISTIC"
    assert "base.price:low_source_quality" in result["reliability_failures"]
    voi = result["scenarios"][0]["value_of_information"]
    assert voi["status"] == "HEURISTIC"
    assert voi["method"] == "deterministic_evsi_evpi_heuristic_fallback"
    assert voi["candidate_budgets"] == [25]


def test_unit_economics_with_known_churn():
    result = unit_economics(UnitEconomics(price=100, variable_cost=20, monthly_churn=.1, cac=120, fixed_monthly_cost=800))
    assert result["gross_margin"] == pytest.approx(.8)
    assert result["ltv_simple"] == pytest.approx(800)
    assert result["cac_target"] == pytest.approx(800 / 3)
    assert result["months_to_payback"] == pytest.approx(1.5)
    assert result["break_even_customers"] == 10

def test_unknown_churn_does_not_emit_ltv():
    result = unit_economics(UnitEconomics(price=100, variable_cost=20, monthly_churn=None, cac=None))
    assert result["ltv_simple"] is None
    assert "monthly_churn" in result["unknowns"]

def test_beta_binomial_update():
    result = beta_update(1, 1, 2, 8)
    assert result == {"alpha": 3, "beta": 9, "posterior_mean": pytest.approx(.25)}

def test_bayesian_value_of_information_is_reproducible_and_cost_sensitive():
    kwargs = {
        "prior_alpha": 2, "prior_beta": 8, "threshold": .3,
        "upside": 1000, "downside": -300,
        "experiments": [{"name": "landing", "sample_size": 100, "cost": 50}],
        "iterations": 2000, "seed": 7,
    }
    first = calculate_value_of_information(**kwargs)
    second = calculate_value_of_information(**kwargs)
    assert first == second
    assert first["method"] == "beta_binomial_nested_monte_carlo"
    assert first["status"] == "AVAILABLE"
    assert first["evpi"] >= first["experiments"][0]["evsi_gross"] - 1e-9
    assert first["experiments"][0]["evsi_net"] == pytest.approx(first["experiments"][0]["evsi_gross"] - 50)


def test_bayesian_value_of_information_bounds_evsi_and_rejects_invalid_direct_inputs():
    result = calculate_value_of_information(
        prior_alpha=2, prior_beta=8, threshold=.3, upside=1000, downside=-300,
        experiments=[{"name": "landing", "sample_size": 1, "cost": 0}], iterations=1, seed=0,
    )
    experiment = result["experiments"][0]
    assert 0 <= experiment["evsi_gross"] <= result["evpi"]
    assert experiment["evsi_net"] == experiment["evsi_gross"]
    with pytest.raises(ValueError, match="finite"):
        calculate_value_of_information(
            prior_alpha=float("nan"), prior_beta=1, threshold=.5, upside=1, downside=0,
            experiments=[{"name": "test", "sample_size": 1, "cost": 0}],
        )
    with pytest.raises(ValueError, match="at least one"):
        calculate_value_of_information(
            prior_alpha=1, prior_beta=1, threshold=.5, upside=1, downside=0, experiments=[],
        )


def test_percentile_ranges():
    result = scenario_percentiles(np.arange(1, 101))
    assert result["low"] == pytest.approx(10.9)
    assert result["base"] == pytest.approx(50.5)
    assert result["high"] == pytest.approx(90.1)

def test_sample_size():
    assert sample_size_proportion(.5, .1) == 97


def test_seeded_simulation_has_contract_percentiles_and_budget_bands():
    scenario = {
        "name": "base",
        "price": {"kind": "uniform", "low": 90, "high": 110},
        "variable_cost": {"kind": "fixed", "value": 20},
        "monthly_churn": {"kind": "fixed", "value": .1},
        "cac": {"kind": "fixed", "value": 120},
        "fixed_monthly_cost": {"kind": "fixed", "value": 800},
    }
    first = simulate_economics([scenario], iterations=100, seed=17)
    second = simulate_economics([scenario], iterations=100, seed=17)
    assert first == second
    result = first["scenarios"][0]
    assert set(result["metrics"]["ltv"]) == {"p10", "p50", "p90"}
    assert result["budget"]["minimum"]["p50"] == pytest.approx(920)
    assert 10 <= result["break_even_customers"]["p50"] <= 12
    assert first["provenance"] == {"calculation": "seeded_monte_carlo", "llm_used": False, "rng": "numpy.PCG64", "seed": 17, "iterations": 100}
