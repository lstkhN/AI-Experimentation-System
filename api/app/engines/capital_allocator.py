"""Deterministic marginal capital allocation and sequential gates."""
from __future__ import annotations
import math

FORMULA_VERSION = "capital-allocator-v2"


def _priority(item: dict) -> float:
    criticality = float(item.get("criticality", 1.0))
    gap = float(item.get("evidence_gap", 1.0))
    decisive = float(item.get("probability_of_decisive_result", 0.0))
    information = float(item.get("expected_information_gain", 0.0))
    cost = max(float(item.get("cost", item.get("recommended_spend", 0.0))), 1e-9)
    time_penalty = max(1.0, float(item.get("time_to_result_days", 0.0)) / 7.0)
    return criticality * gap * decisive * information / (cost * time_penalty)


def allocate_capital(available_budget: float, requests: list[dict], *, candidate_experiments: list[dict] | None = None) -> dict:
    """Allocate only unlocked sequential requests and rank candidate tests.

    The returned commitment is the currently eligible spend; all remaining
    budget is explicitly held back until a gate is unlocked.
    """
    if not math.isfinite(available_budget) or available_budget < 0:
        raise ValueError("available_budget must be finite and non-negative")
    remaining = available_budget
    allocations: list[dict] = []
    prior_unlocked = True
    for index, request in enumerate(requests, start=1):
        requested = float(request.get("recommended_spend", request.get("amount", 0)))
        if not math.isfinite(requested) or requested < 0:
            raise ValueError("requested spend must be finite and non-negative")
        eligible = prior_unlocked and bool(request.get("gate_unlocked", True))
        allocated = min(requested, remaining) if eligible else 0.0
        status = "ALLOCATED" if allocated == requested and eligible else ("PARTIAL" if allocated > 0 else ("LOCKED" if not eligible else "INSUFFICIENT_BUDGET"))
        allocations.append({"sequence": index, "gate_id": request.get("gate_id"), "requested_spend": requested, "allocated_spend": allocated, "status": status})
        remaining -= allocated
        prior_unlocked = eligible and allocated == requested
    ranked = []
    for candidate in candidate_experiments or []:
        item = dict(candidate)
        item["priority_score"] = _priority(item)
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["priority_score"], str(item.get("name", item.get("title", "")))))
    commitment = available_budget - remaining
    return {
        "formula_version": FORMULA_VERSION,
        "available_budget": available_budget,
        "recommended_commitment": commitment,
        "do_not_commit_yet": remaining,
        "allocated_total": commitment,
        "remaining_budget": remaining,
        "allocations": allocations,
        "ranked_experiments": ranked,
        "provenance": {"calculation": "deterministic", "llm_used": False},
    }


capital_allocator = allocate_capital
