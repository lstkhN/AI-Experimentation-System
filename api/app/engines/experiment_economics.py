"""Deterministic economics for deciding how much to spend on one experiment."""
from __future__ import annotations
import math

FORMULA_VERSION = "experiment-economics-v2"


def calculate_experiment_economics(
    *, estimated_cost: float,
    success_probability: float = 0.0,
    upside: float = 0.0,
    learning_value: float = 0.0,
    max_spend: float | None = None,
    minimum_spend: float | None = None,
    expected_observations_low: int = 0,
    expected_observations_base: int = 0,
    expected_observations_high: int = 0,
    time_to_result_days: int = 0,
    capital_at_risk: float | None = None,
    capital_unlocked_if_pass: float = 0.0,
    confidence: str = "LOW",
    confidence_reason: str = "No observed experiment data was supplied.",
    stop_loss: float | None = None,
) -> dict:
    """Return bounded spend, information value and explicit provenance.

    This is a planning heuristic, not a claim about the probability of success.
    Every estimate is supplied by the caller; this engine performs no LLM
    inference and never recommends spending the whole available budget.
    """
    numeric = (estimated_cost, success_probability, upside, learning_value, capital_unlocked_if_pass)
    if not all(math.isfinite(float(value)) for value in numeric):
        raise ValueError("experiment economics inputs must be finite")
    if max_spend is not None and not math.isfinite(max_spend):
        raise ValueError("max_spend must be finite")
    if estimated_cost < 0 or not 0 <= success_probability <= 1 or upside < 0 or learning_value < 0:
        raise ValueError("costs and values must be non-negative; probability must be between 0 and 1")
    if any(int(value) < 0 for value in (expected_observations_low, expected_observations_base, expected_observations_high, time_to_result_days)):
        raise ValueError("observations and time must be non-negative")
    minimum = estimated_cost if minimum_spend is None else minimum_spend
    if minimum < 0 or (max_spend is not None and max_spend < 0) or capital_unlocked_if_pass < 0:
        raise ValueError("spend values must be non-negative")
    if max_spend is not None and minimum > max_spend:
        raise ValueError("minimum_spend cannot exceed maximum_useful_spend")
    recommended = min(estimated_cost, max_spend) if max_spend is not None else estimated_cost
    recommended = max(minimum, recommended)
    risk = estimated_cost if capital_at_risk is None else capital_at_risk
    loss = risk if stop_loss is None else stop_loss
    expected_value = success_probability * upside + learning_value
    return {
        "formula_version": FORMULA_VERSION,
        "minimum_spend": minimum,
        "recommended_spend": recommended,
        "maximum_useful_spend": max_spend if max_spend is not None else estimated_cost,
        "expected_observations_low": int(expected_observations_low),
        "expected_observations_base": int(expected_observations_base),
        "expected_observations_high": int(expected_observations_high),
        "probability_of_decisive_result": success_probability,
        "expected_information_gain": learning_value,
        "cost_per_information_unit": (recommended / learning_value) if learning_value > 0 else None,
        "time_to_result_days": int(time_to_result_days),
        "capital_at_risk": risk,
        "capital_unlocked_if_pass": capital_unlocked_if_pass,
        "confidence": confidence,
        "confidence_reason": confidence_reason,
        "stop_loss": loss,
        "estimated_cost": estimated_cost,
        "expected_value": expected_value,
        "net_expected_value": expected_value - recommended,
        "inputs_complete": True,
        "provenance": {"calculation": "deterministic", "llm_used": False},
    }


evaluate_experiment_economics = calculate_experiment_economics
experiment_economics = calculate_experiment_economics
