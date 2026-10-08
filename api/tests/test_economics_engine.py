import numpy as np
import pytest
from app.engines.economics import UnitEconomics, beta_update, sample_size_proportion, scenario_percentiles, simulate_economics, unit_economics

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
