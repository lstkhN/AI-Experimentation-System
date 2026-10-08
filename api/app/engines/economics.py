"""Pure deterministic economics calculations. No LLM calls belong here."""
from dataclasses import dataclass
import math
import numpy as np

FORMULA_VERSION = "economics-mvp-v1"


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


def simulate_economics(
    scenarios: list[dict], *, iterations: int = 5000, seed: int = 0, currency: str = "USD", capital_steps: list[dict] | None = None,
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
    return {
        "formula_version": FORMULA_VERSION,
        "reliability": "RELIABLE" if output else "INSUFFICIENT_CRITICAL_INPUTS",
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
    reliability = "RELIABLE" if calculated and not unknowns and all(
        scenario["metrics"].get("ltv_simple") is not None
        and "months_to_payback" in scenario["metrics"]
        for scenario in calculated
    ) else "INSUFFICIENT_CRITICAL_INPUTS"
    return {
        "scenarios": calculated,
        "unknowns": unknowns,
        "reliability": reliability,
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
