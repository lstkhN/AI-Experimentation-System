from datetime import datetime
from typing import Any

from pydantic import BaseModel


class VerdictRead(BaseModel):
    """Persisted result of evaluating one hypothesis' linked evidence."""

    id: int
    hypothesis_id: int
    analysis_run_id: int | None
    verdict: str
    support_score: int
    coverage: int
    data_quality: str
    decisive_facts: list[dict[str, Any]]
    unknowns: list[str]
    rule: str
    support_mass: float
    contradiction_mass: float
    source_clusters: int
    independent_source_clusters: int
    created_at: datetime
