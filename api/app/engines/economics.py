"""Pure deterministic economics calculations. No LLM calls belong here."""
from dataclasses import dataclass
import math
import numpy as np

FORMULA_VERSION = "economics-decision-v2"
CRITICAL_PARAMETERS = ("price", "variable_cost", "monthly_churn", "cac", "fixed_monthly_cost")
# The target ratio is a decision policy used to calculate CAC targets, so it
# must have the same provenance standard for calculated economics results.
CALCULATION_CRITICAL_PARAMETERS = CRITICAL_PARAMETERS + ("target_ltv_cac_ratio",)

# A model with complete numbers remains a heuristic until each decision-critical
# assumption is attributable to evidence or a benchmark at the stated threshold.
HEURISTIC_CONTRACT = {
    "classification": "HEURISTIC",
    "method": "unit_economics_with_optional_seeded_monte_carlo",
    "version": FORMULA_VERSION,
    "assumptions": [
        "LTV is gross profit per customer divided by monthly churn.",
        "CAC, churn, price, variable cost, and fixed monthly cost are independent draws.",
        "Budget bands are planning estimates, not a funding authorization.",
    ],
    "threshold": {
        "reliable_source_types": ["verified_evidence", "benchmark"],
        "minimum_confidence": "MEDIUM",
        "minimum_source_quality": 0.7,
        "minimum_freshness": 0.5,
        "source_id_required": True,
        "critical_parameters": list(CRITICAL_PARAMETERS),
        "calculation_critical_parameters": list(CALCULATION_CRITICAL_PARAMETERS),
    },
}


def _p10_p50_p90(samples: np.ndarray) -> dict:
    """JSON-safe percentile summary with names used by the MVP contract."""
    return {label: float(np.percentile(samples, percentile)) for label, percentile in (("p10", 10), ("p50", 50), ("p90", 90))}


def _draw_distribution(spec: dict, rng: np.random.Generator, iterations: int) -> np.ndarray:
    """Draw from an explicitly supplied distribution; no inferred/LLM assumptions."""
    kind = spec["kind"]
    if kind == "fixed":
        return np.full(iterations, spec["value"], dtype=float)
    if kind == "uniform":
        return rng.uniform(spec["low"], spec["high"], iterations)
    if kind == "triangular":
        return rng.triangular(spec["low"], spec["mode"], spec["high"], iterations)
    if kind == "normal":
        return rng.normal(spec["mean"], spec["stddev"], iterations)
    raise ValueError(f"unsupported distribution: {kind}")


def _reliability(
    scenarios: list[dict], *, required_parameters: tuple[str, ...] = CRITICAL_PARAMETERS,
    trusted_source_ids: dict[str, set[str]] | None = None,
    trusted_source_metadata: dict[tuple[str, str], dict] | None = None,
) -> tuple[str, list[str]]:
    """Gate decision-grade reliability on provenance resolved by the project boundary.

    Caller-supplied source IDs are labels, not proof.  Only IDs resolved by the
    API against verified project evidence/benchmarks can qualify a result.
    """
    failures: list[str] = []
    qualifying_sources = set(HEURISTIC_CONTRACT["threshold"]["reliable_source_types"])
    qualifying_confidence = {"MEDIUM", "HIGH"}
    trusted_source_ids = trusted_source_ids or {}
    trusted_source_metadata = trusted_source_metadata or {}
    for scenario in scenarios:
        name = scenario.get("name", "base")
        provenance = scenario.get("parameter_provenance") or {}
        for parameter in required_parameters:
            value = scenario.get(parameter)
            if value is None:
                failures.append(f"{name}.{parameter}:missing")
                continue
            source = provenance.get(parameter) or {}
            source_type = source.get("source_type")
            expected_flag = {
                "verified_evidence": "observed",
                "benchmark": "benchmark",
                "inference": "inferred",
                "user_input": None,
            }.get(source_type)
            enabled_flags = {flag for flag in ("observed", "benchmark", "inferred") if source.get(flag)}
            source_id = source.get("source_id", "").strip() if isinstance(source.get("source_id"), str) else ""
            metadata = trusted_source_metadata.get((source_type, source_id))
            # Direct engine callers can provide trusted IDs only (the legacy
            # API); API callers provide DB-resolved quality/freshness metadata.
            quality = (metadata or {}).get("source_quality", 1.0)
            freshness = (metadata or {}).get("freshness", 1.0)
            if (source_type not in qualifying_sources
                    or source.get("confidence") not in qualifying_confidence
                    or not source_id
                    or source_id not in trusted_source_ids.get(source_type, set())
                    or enabled_flags != {expected_flag}):
                failures.append(f"{name}.{parameter}:unqualified_provenance")
            elif quality < HEURISTIC_CONTRACT["threshold"]["minimum_source_quality"]:
                failures.append(f"{name}.{parameter}:low_source_quality")
            elif freshness < HEURISTIC_CONTRACT["threshold"]["minimum_freshness"]:
                failures.append(f"{name}.{parameter}:stale_source")
    if failures:
        return ("INSUFFICIENT_CRITICAL_INPUTS" if any(item.endswith(":missing") for item in failures) else "HEURISTIC", failures)
    return "RELIABLE", []


def simulate_economics(
    scenarios: list[dict], *, iterations: int = 5000, seed: int = 0, currency: str = "USD", capital_steps: list[dict] | None = None,
    trusted_source_ids: dict[str, set[str]] | None = None,
    trusted_source_metadata: dict[tuple[str, str], dict] | None = None,
) -> dict:
    """Seeded Monte Carlo unit-economics simulation using only request distributions.

    Budget formulas are deliberately simple and recorded in provenance: fund one
    acquisition (minimum), enough acquisitions to cover one month of fixed cost
    (recommended), and acquisitions up to the LTV/CAC value boundary (max useful).
    """
    rng = np.random.default_rng(seed)
    output = []
    for scenario in scenarios:
        draws = {field: _draw_distribution(scenario[field], rng, iterations) for field in (
            "price", "variable_cost", "monthly_churn", "cac", "fixed_monthly_cost"
        )}
        price, cost, churn, cac, fixed = (draws[key] for key in ("price", "variable_cost", "monthly_churn", "cac", "fixed_monthly_cost"))
        if (not all(np.all(np.isfinite(value)) for value in draws.values()) or np.any(price <= 0) or np.any(cost < 0) or np.any(cost >= price) or np.any(churn <= 0) or np.any(churn >= 1) or np.any(cac < 0) or np.any(fixed < 0)):
            raise ValueError("distribution draws must produce price > variable_cost, 0 < monthly_churn < 1, and non-negative costs")
        gross_profit = price - cost
        ltv = gross_profit / churn
        contribution = ltv - cac
        break_even_customers = np.ceil(fixed / gross_profit)
        payback_months = np.divide(cac, gross_profit, out=np.zeros_like(cac), where=gross_profit != 0)
        minimum_budget = fixed + cac
        recommended_budget = fixed + cac * np.maximum(1, break_even_customers)
        # A CAC of zero has no acquisition-spend ceiling; use the recommended
        # operating budget rather than emitting an infinite/non-JSON value.
        useful_customers = np.where(cac > 0, np.maximum(break_even_customers, np.floor(ltv / cac)), break_even_customers)
        max_useful_budget = fixed + cac * np.maximum(1, useful_customers)
        output.append({
            "name": scenario.get("name", "base"),
            "metrics": {
                "gross_profit_per_customer": _p10_p50_p90(gross_profit),
                "ltv": _p10_p50_p90(ltv),
                "ltv_cac_ratio": _p10_p50_p90(np.divide(ltv, cac, out=np.full_like(ltv, 1e308), where=cac != 0)),
                "contribution_after_cac": _p10_p50_p90(contribution),
            },
            "break_even_customers": _p10_p50_p90(break_even_customers),
            "payback_months": _p10_p50_p90(payback_months),
            "budget": {
                "minimum": _p10_p50_p90(minimum_budget),
                "recommended": _p10_p50_p90(recommended_budget),
                "max_useful": _p10_p50_p90(max_useful_budget),
                "currency": currency.upper(),
            },
            "learning_value": {
                "probability_positive_unit_economics": float(np.mean(contribution > 0)),
                "contribution_after_cac": _p10_p50_p90(contribution),
                "uncertainty_width_p90_minus_p10": float(np.percentile(contribution, 90) - np.percentile(contribution, 10)),
            },
        })
    reliability, reliability_failures = _reliability(scenarios, trusted_source_ids=trusted_source_ids, trusted_source_metadata=trusted_source_metadata)
    for result in output:
        contribution = result["learning_value"]["contribution_after_cac"]
        evpi = max(0.0, contribution["p90"] - contribution["p50"])
        result["value_of_information"] = {
            "method": "deterministic_evsi_evpi_heuristic_fallback",
            "assumptions": ["EVPI/EVSI are per-customer contribution heuristics, not financial valuation.", "EVSI is capped at EVPI and assumes a 50% learning capture rate."],
            "threshold": {"reliability_required": "RELIABLE"},
            "evpi": evpi,
            "evsi": evpi * 0.5,
            "candidate_budgets": {key: value["p50"] for key, value in result["budget"].items() if key != "currency"},
        }
    return {
        "formula_version": FORMULA_VERSION,
        "decision_contract": HEURISTIC_CONTRACT,
        "reliability": reliability if output else "INSUFFICIENT_CRITICAL_INPUTS",
        "reliability_failures": reliability_failures,
        "provenance": {"calculation": "seeded_monte_carlo", "llm_used": False, "rng": "numpy.PCG64", "seed": seed, "iterations": iterations},
        "scenarios": output,
        "capital_steps": capital_steps or [],
    }

@dataclass(frozen=True)
class UnitEconomics:
    price: float
    variable_cost: float
    monthly_churn: float | None
    cac: float | None
    fixed_monthly_cost: float = 0.0
    target_ltv_cac_ratio: float = 3.0


def unit_economics(x: UnitEconomics) -> dict:
    values = (x.price, x.variable_cost, x.target_ltv_cac_ratio, x.fixed_monthly_cost)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("numeric inputs must be finite")
    if x.cac is not None and (x.cac < 0 or not math.isfinite(x.cac)):
        raise ValueError("cac must be finite and non-negative")
    if x.price <= 0 or x.variable_cost < 0 or x.variable_cost >= x.price or x.target_ltv_cac_ratio <= 0:
        raise ValueError("price must be positive and exceed variable_cost")
    gross_profit = x.price - x.variable_cost
    margin = gross_profit / x.price
    result = {"gross_profit_per_order": gross_profit, "gross_margin": margin, "monthly_gross_profit_per_customer": x.price * margin}
    if x.monthly_churn is not None:
        if not 0 < x.monthly_churn < 1:
            raise ValueError("monthly_churn must be between 0 and 1")
        ltv = x.price * margin / x.monthly_churn
        result.update({"ltv_simple": ltv, "cac_ceiling_break_even": ltv, "cac_target": ltv / x.target_ltv_cac_ratio})
        if x.cac is not None:
            result["months_to_payback"] = x.cac / (x.price * margin)
        if x.fixed_monthly_cost:
            result["break_even_customers"] = math.ceil(x.fixed_monthly_cost / (x.price * margin))
    else:
        result["ltv_simple"] = None
        result["unknowns"] = ["monthly_churn"]
    return result


def churn_sensitivity(x: UnitEconomics, churn_rates: list[float] | None = None) -> dict:
    """Return LTV/CAC outcomes for explicit churn assumptions, without sampling."""
    if churn_rates is None:
        if x.monthly_churn is None:
            return {
                "status": "requires_assumption",
                "unknowns": ["monthly_churn"],
                "values": [],
            }
        # A compact, deterministic default around the supplied base assumption.
        churn_rates = [max(0.000001, x.monthly_churn * 0.8), x.monthly_churn, min(0.999999, x.monthly_churn * 1.2)]
    if any(not math.isfinite(rate) or not 0 < rate < 1 for rate in churn_rates):
        raise ValueError("churn sensitivity rates must be between 0 and 1")

    gross_profit = x.price - x.variable_cost
    values = []
    for churn in sorted(set(churn_rates)):
        ltv = gross_profit / churn
        value = {
            "monthly_churn": churn,
            "ltv_simple": ltv,
            "cac_ceiling_break_even": ltv,
            "cac_target": ltv / x.target_ltv_cac_ratio,
        }
        if x.cac is not None:
            value["ltv_cac_ratio"] = ltv / x.cac if x.cac else None
        values.append(value)
    return {"status": "available", "values": values}


def calculate_economics(
    scenarios: list[dict],
    sensitivity_rates: list[float] | None = None,
    capital_steps: list[dict] | None = None,
    currency: str = "USD",
    trusted_source_ids: dict[str, set[str]] | None = None,
    trusted_source_metadata: dict[tuple[str, str], dict] | None = None,
) -> dict:
    """Calculate project economics deterministically from JSON-safe assumptions."""
    calculated = []
    unknowns: list[str] = []
    for scenario in scenarios:
        assumptions = UnitEconomics(**{key: scenario[key] for key in UnitEconomics.__dataclass_fields__ if key in scenario})
        metrics = unit_economics(assumptions)
        sensitivity = churn_sensitivity(assumptions, sensitivity_rates)
        scenario_unknowns = metrics.get("unknowns", [])
        if scenario_unknowns:
            unknowns.extend(f"{scenario.get('name', 'base')}.{item}" for item in scenario_unknowns)
        calculated.append({
            "name": scenario.get("name", "base"),
            "metrics": metrics,
            "sensitivity": sensitivity,
        })

    steps = capital_steps or []
    # Steps are supplied as a sequence intentionally: their order is the funding plan order.
    normalized_steps = [
        {key: step[key] for key in ("name", "amount", "month", "trigger", "purpose", "expected_learning", "unlock_condition") if key in step and step[key] is not None}
        for step in steps
    ]
    # Price, variable cost, churn, and CAC are required to make a project-level
    # investment decision.  A capital plan can still be saved without them,
    # but must not be treated as decision-grade economics.
    provenance_reliability, reliability_failures = _reliability(
        scenarios,
        required_parameters=CALCULATION_CRITICAL_PARAMETERS,
        trusted_source_ids=trusted_source_ids,
        trusted_source_metadata=trusted_source_metadata,
    )
    has_metrics = calculated and not unknowns and all(
        scenario["metrics"].get("ltv_simple") is not None
        and "months_to_payback" in scenario["metrics"]
        for scenario in calculated
    )
    reliability = provenance_reliability if has_metrics else "INSUFFICIENT_CRITICAL_INPUTS"
    candidate_budgets = [step["amount"] for step in normalized_steps]
    for item in calculated:
        item["value_of_information"] = {
            "method": "deterministic_evsi_evpi_heuristic_fallback",
            "assumptions": ["Point assumptions have no modeled uncertainty; EVPI and EVSI default to zero.", "Candidate budgets are submitted capital steps."],
            "threshold": {"reliability_required": "RELIABLE"},
            "evpi": 0.0,
            "evsi": 0.0,
            "candidate_budgets": candidate_budgets,
        }
    return {
        "formula_version": FORMULA_VERSION,
        "decision_contract": HEURISTIC_CONTRACT,
        "scenarios": calculated,
        "unknowns": unknowns,
        "reliability": reliability,
        "reliability_failures": reliability_failures,
        "capital_plan": {
            "currency": currency.upper(),
            "total_required": sum(step["amount"] for step in normalized_steps),
            "steps": normalized_steps,
        },
    }


def beta_update(alpha: float, beta: float, successes: int, failures: int) -> dict:
    if not all(math.isfinite(v) for v in (alpha, beta)):
        raise ValueError("alpha and beta must be finite")
    if min(alpha, beta, successes, failures) < 0 or alpha == 0 or beta == 0:
        raise ValueError("alpha and beta must be positive; observations non-negative")
    a, b = alpha + successes, beta + failures
    return {"alpha": a, "beta": b, "posterior_mean": a / (a + b)}


def scenario_percentiles(samples: np.ndarray) -> dict:
    if len(samples) == 0:
        raise ValueError("samples cannot be empty")
    return {"low": float(np.percentile(samples, 10)), "base": float(np.percentile(samples, 50)), "high": float(np.percentile(samples, 90))}


def sample_size_proportion(expected: float = 0.5, half_width: float = 0.1, z: float = 1.96) -> int:
    if not 0 < expected < 1 or half_width <= 0:
        raise ValueError("expected must be in (0,1), half_width must be positive")
    return math.ceil((z * z * expected * (1 - expected)) / (half_width * half_width))


def calculate_value_of_information(*, prior_alpha: float, prior_beta: float, threshold: float,
                                   upside: float, downside: float, experiments: list[dict],
                                   iterations: int = 20_000, seed: int = 0) -> dict:
    """Estimate EVPI/EVSI with an explicit Beta-Binomial decision model."""
    numeric_inputs = (prior_alpha, prior_beta, threshold, upside, downside)
    if not all(math.isfinite(value) for value in numeric_inputs):
        raise ValueError("value-of-information inputs must be finite")
    if prior_alpha <= 0 or prior_beta <= 0 or not 0 < threshold < 1:
        raise ValueError("prior alpha/beta must be positive and threshold must be between 0 and 1")
    if iterations < 1 or iterations > 100_000:
        raise ValueError("iterations must be between 1 and 100000")
    if upside < 0 or downside > 0:
        raise ValueError("upside must be non-negative and downside must be non-positive")
    if not experiments:
        raise ValueError("at least one experiment is required")
    rng = np.random.default_rng(seed)
    theta = rng.beta(prior_alpha, prior_beta, iterations)
    truth_is_good = theta >= threshold
    current_go = (prior_alpha / (prior_alpha + prior_beta)) >= threshold
    current_utility = np.where(truth_is_good, upside, downside) if current_go else np.zeros(iterations)
    current_value = float(np.mean(current_utility))
    evpi = float(np.mean(np.where(truth_is_good, upside, 0.0)) - current_value)
    results: list[dict] = []
    for experiment in experiments:
        name = str(experiment.get("name", "experiment"))
        sample_size = int(experiment.get("sample_size", 0))
        cost = float(experiment.get("cost", 0))
        if sample_size < 1 or not math.isfinite(cost) or cost < 0:
            raise ValueError("experiment sample_size must be positive and cost must be finite and non-negative")
        successes = rng.binomial(sample_size, theta)
        posterior_mean = (prior_alpha + successes) / (prior_alpha + prior_beta + sample_size)
        go_after = posterior_mean >= threshold
        after_utility = np.where(go_after, np.where(truth_is_good, upside, downside), 0.0)
        # Shared Monte Carlo draws make the estimates reproducible, but finite
        # samples can otherwise violate the information-value bounds.  EVSI is
        # non-negative before experiment cost and cannot exceed perfect info.
        gross = min(evpi, max(0.0, float(np.mean(after_utility) - current_value)))
        net = gross - cost
        results.append({"name": name, "sample_size": sample_size, "cost": cost,
                        "evsi_gross": gross, "evsi_net": net,
                        "decision_change_probability": float(np.mean(go_after != current_go)),
                        "recommended": net > 0})
    best = max(results, key=lambda item: item["evsi_net"], default=None)
    return {"method": "beta_binomial_nested_monte_carlo", "status": "AVAILABLE",
            "current_decision": "GO" if current_go else "STOP", "current_value": current_value,
            "evpi": evpi, "experiments": results,
            "recommended_experiment": best["name"] if best and best["recommended"] else None,
            "provenance": {"seed": seed, "iterations": iterations, "rng": "numpy.PCG64"},
            "assumptions": ["Unknown success rate follows a Beta prior.", "Experiment outcomes follow a Binomial likelihood.", "GO is selected when posterior mean reaches the threshold.", "Upside and downside are decision utilities, not revenue forecasts."]}
