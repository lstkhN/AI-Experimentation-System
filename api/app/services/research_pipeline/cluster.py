"""Deterministic source clustering."""

from app.services.evidence_normalization import canonical_source_cluster


def cluster(claims: list[dict]) -> list[dict]:
    """Assign URL-derived clusters, retaining legacy fallbacks for URL-less claims."""
    return [
        {
            **item,
            "source_cluster": (
                canonical_source_cluster(item["url"])
                if item.get("url")
                else item.get("source_cluster") or item.get("domain") or "unknown"
            ),
        }
        for item in claims
    ]
