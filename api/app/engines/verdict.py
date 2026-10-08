"""Deterministic, rule-assisted verdicts derived from scored evidence.

This module deliberately has no database, HTTP, or LLM dependencies.  The
thresholds below are the v1.1 policy and are kept in one immutable object so a
call made with the same evidence and date always produces the same result.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from .evidence import Evidence, effective_weight, score_evidence


@dataclass(frozen=True)
class VerdictPolicy:
    """Explicit v1.1 decision thresholds for :class:`VerdictEngine`."""

    promising_support: int = 65
    promising_coverage: int = 25
    weak_support: int = 45
    weak_coverage: int = 25
    no_go_min_contradiction_mass: float = 0.5
    no_go_margin: float = 0.35
    no_go_coverage: int = 15
    decisive_facts_limit: int = 3


class VerdictEngine:
    """Turn evidence into a reproducible verdict and an audit-friendly trace."""

    def __init__(self, policy: VerdictPolicy | None = None) -> None:
        self.policy = policy or VerdictPolicy()

    def evaluate(self, evidence: Iterable[Evidence], *, today: date | None = None) -> dict:
        """Evaluate evidence without mutating it.

        The result contains the three evidence dimensions at top level, the
        selected rule, the strongest evidence records (``decisive_facts``),
        and explicit gaps (``unknowns``).
        """
        items = list(evidence)
        scores = score_evidence(items, today=today)
        verdict, rule = self._select_verdict(scores)
        return {
            "verdict": verdict,
            "support_score": scores["support_score"],
            "coverage": scores["coverage"],
            "data_quality": scores["data_quality"],
            "decisive_facts": self._decisive_facts(items, today),
            "unknowns": self._unknowns(items, scores),
            "rule": rule,
            # Keep the raw values available for auditing while retaining the
            # public evidence score names as the canonical dimensions.
            "support_mass": scores["support_mass"],
            "contradiction_mass": scores["contradiction_mass"],
            "source_clusters": scores["source_clusters"],
            "independent_source_clusters": scores["independent_source_clusters"],
        }

    def _select_verdict(self, scores: dict) -> tuple[str, str]:
        policy = self.policy
        support = scores["support_score"]
        coverage = scores["coverage"]
        quality = scores["data_quality"]
        supporting = scores["support_mass"]
        contradicting = scores["contradiction_mass"]

        if (
            contradicting >= policy.no_go_min_contradiction_mass
            and contradicting >= supporting + policy.no_go_margin
            and coverage >= policy.no_go_coverage
            and quality != "LOW"
        ):
            return "NO-GO-FOR-NOW", "material_contradiction"
        if (
            support >= policy.promising_support
            and coverage >= policy.promising_coverage
            and quality in {"MEDIUM", "HIGH"}
        ):
            return "PROMISING", "supported_with_sufficient_coverage"
        if (
            support <= policy.weak_support
            and coverage >= policy.weak_coverage
            and quality in {"MEDIUM", "HIGH"}
        ):
            return "WEAK", "net_contradiction_without_no_go_confidence"
        return "UNPROVEN", "insufficient_or_inconclusive_evidence"

    def _decisive_facts(self, items: list[Evidence], today: date | None) -> list[dict]:
        # enumerate gives a deterministic tie breaker without depending on
        # input object ordering implementation details.
        weighted = [
            (effective_weight(item, today), index, item)
            for index, item in enumerate(items)
            if effective_weight(item, today) > 0
        ]
        weighted.sort(key=lambda entry: (-entry[0], entry[1]))
        return [
            {
                "direction": item.direction,
                "tier": item.tier,
                "category": item.category,
                "source_cluster": item.source_cluster,
                "weight": round(weight, 4),
            }
            for weight, _, item in weighted[: self.policy.decisive_facts_limit]
        ]

    def _unknowns(self, items: list[Evidence], scores: dict) -> list[str]:
        unknowns: list[str] = []
        if not items:
            unknowns.append("no_evidence")
        if scores["coverage"] < self.policy.promising_coverage:
            unknowns.append("insufficient_coverage")
        if scores["data_quality"] == "LOW":
            unknowns.append("low_data_quality")
        if scores["independent_source_clusters"] < 2:
            unknowns.append("insufficient_independent_sources")
        if not any(item.tier in {"E4", "E5", "E6"} for item in items):
            unknowns.append("no_high_strength_evidence")
        return unknowns


def evaluate_verdict(evidence: Iterable[Evidence], *, today: date | None = None) -> dict:
    """Convenience function for the default v1.1 deterministic policy."""
    return VerdictEngine().evaluate(evidence, today=today)


# A short alias mirrors the other deterministic engine's ``score_evidence`` API.
score_verdict = evaluate_verdict
