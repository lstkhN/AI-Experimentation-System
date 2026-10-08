"""Deterministic evidence scoring primitives for Release 0.1."""
from dataclasses import dataclass
from datetime import date
from math import exp, log
from typing import Literal
import math

TIER_STRENGTH = {"E0": 0.0, "E1": 0.10, "E2": 0.20, "E3": 0.35, "E4": 0.55, "E5": 0.80, "E6": 1.0}
# Volatile market observations decay much faster than durable behavioural data.
HALF_LIFE_DAYS = {
    "pricing": 180, "channel": 180, "competition": 270, "market_size": 270,
    "regulation": 270, "technology": 270, "problem": 365, "workflow": 365,
    "research": 365, "transaction": 540, "retention": 540, "behavior": 540,
}
CATEGORY_ALIASES = {"market": "market_size", "market-sizing": "market_size", "behaviour": "behavior"}

@dataclass(frozen=True)
class Evidence:
    tier: str
    direction: Literal["supporting", "contradicting"]
    relevance: float = 1.0
    source_quality: float = 0.75
    observed_on: date | None = None
    category: str = "problem"
    source_cluster: str = "unknown"
    independent: bool = True
    evidence_status: str = "verified"


def freshness_factor(observed_on: date | None, category: str, today: date | None = None) -> float:
    if observed_on is None:
        return 1.0
    today = today or date.today()
    age = max(0, (today - observed_on).days)
    half_life = HALF_LIFE_DAYS.get(CATEGORY_ALIASES.get(category.lower(), category.lower()), 365)
    return exp(-log(2) * age / half_life)


def effective_weight(item: Evidence, today: date | None = None) -> float:
    """Weight one reviewed record; cluster de-duplication happens in scoring."""
    if item.evidence_status != "verified":
        return 0.0
    independence = 1.0 if item.independent else 0.5
    return TIER_STRENGTH.get(item.tier, 0.0) * item.relevance * item.source_quality * freshness_factor(item.observed_on, item.category, today) * independence


def score_evidence(items: list[Evidence], today: date | None = None, target_mass: float = 3.0) -> dict:
    if target_mass <= 0 or not math.isfinite(target_mass):
        raise ValueError("target_mass must be positive and finite")
    # Multiple pages syndicated by one publisher are not independent evidence.
    # Divide their combined influence by sqrt(n): corroboration remains useful,
    # but cannot masquerade as n independent sources.
    scoreable = [x for x in items if x.evidence_status == "verified" and TIER_STRENGTH.get(x.tier, 0.0) > 0]
    cluster_counts: dict[str, int] = {}
    for item in scoreable:
        # Unknown provenance must not be treated as independent sources.
        cluster = item.source_cluster or "unknown"
        cluster_counts[cluster] = cluster_counts.get(cluster, 0) + 1
    def clustered_weight(item: Evidence) -> float:
        cluster = item.source_cluster or "unknown"
        return effective_weight(item, today) / math.sqrt(cluster_counts.get(cluster, 1))
    support = sum(clustered_weight(x) for x in scoreable if x.direction == "supporting")
    contradiction = sum(clustered_weight(x) for x in scoreable if x.direction == "contradicting")
    ratio = (0.5 + support) / (1.0 + support + contradiction)
    coverage = 100 * (1 - exp(-(support + contradiction) / target_mass))
    clusters = {x.source_cluster for x in scoreable if x.source_cluster != "unknown"}
    independent_clusters = {x.source_cluster for x in scoreable if x.source_cluster != "unknown" and x.independent}
    quality_items = scoreable
    if quality_items:
        denom = sum(TIER_STRENGTH[x.tier] for x in quality_items)
        quality_raw = sum(x.source_quality * x.relevance * (1.0 if x.independent else 0.5) * TIER_STRENGTH[x.tier] for x in quality_items) / denom
    else:
        quality_raw = 0.0
    quality = "HIGH" if quality_raw > 0.78 and len(independent_clusters) >= 2 and any(x.tier in {"E4", "E5", "E6"} for x in quality_items) else "MEDIUM" if quality_raw >= 0.55 else "LOW"
    return {"support_score": round(100 * ratio), "coverage": round(coverage), "data_quality": quality, "quality_raw": round(quality_raw, 4), "support_mass": support, "contradiction_mass": contradiction, "source_clusters": len(clusters), "independent_source_clusters": len(independent_clusters), "source_cluster_penalty": round(sum(effective_weight(x, today) for x in scoreable) - support - contradiction, 6), "unverified_candidates": sum(1 for x in items if x.evidence_status == "candidate")}
