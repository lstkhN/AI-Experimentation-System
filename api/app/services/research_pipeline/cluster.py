"""Deterministic source clustering."""
def cluster(claims: list[dict]) -> list[dict]:
    return [{**item, "source_cluster": item.get("source_cluster") or item.get("domain") or "unknown"} for item in claims]
