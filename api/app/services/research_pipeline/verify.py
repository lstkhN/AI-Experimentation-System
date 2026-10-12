"""Deterministic verification, freshness, and contradiction policy for research claims."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from app.engines.evidence import freshness_factor

_NEGATION = re.compile(r"\b(?:no|not|never|none|without|isn't|aren't|doesn't|don't|cannot|can't)\b", re.I)
_WORDS = re.compile(r"\w+", re.U)


def claim_key(claim: str) -> tuple[str, bool]:
    """Return a conservative comparison key and whether the claim is negated."""
    negated = bool(_NEGATION.search(claim))
    words = _WORDS.findall(_NEGATION.sub("", claim).lower())
    # Auxiliary verbs carry polarity rather than claim subject matter here.
    words = [word for word in words if word not in {"do", "does", "did", "is", "are", "was", "were"}]
    # Conservative inflection normalization keeps "exists" and "exist" comparable.
    return " ".join(word[:-1] if word.endswith("s") and len(word) > 3 else word for word in words), negated


def contradicts(first: str, second: str) -> bool:
    """Detect explicit polarity conflicts only; unrelated claims are never guessed."""
    first_key, first_negated = claim_key(first)
    second_key, second_negated = claim_key(second)
    return bool(first_key and first_key == second_key and first_negated != second_negated)


def freshness_score(fetched_at: datetime | None, category: str = "research") -> float:
    observed = fetched_at.date() if fetched_at else None
    return freshness_factor(observed, category, date.today())


def verify_claim(claim: dict, *, methodology_available: bool, source_quality: float,
                 fetched_at: datetime | None = None, source_cluster: str = "unknown",
                 independent_clusters: int = 0) -> dict:
    """Create an auditable primary verification without changing legacy status rules."""
    fresh = freshness_score(fetched_at)
    independent = min(1.0, independent_clusters / 2)
    verified = methodology_available and source_quality >= 0.7
    provenance = {
        "source_cluster": source_cluster or "unknown",
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "methodology_available": methodology_available,
        "source_quality": source_quality,
    }
    return {
        **claim, "status": "verified" if verified else "candidate",
        "verification_reason": "methodology_and_quality_review" if verified else "original methodology unavailable or source quality is low",
        "freshness_score": fresh, "independence_score": independent, "provenance": provenance,
    }
