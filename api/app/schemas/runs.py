from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field, ConfigDict

class AnalysisRunCreate(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    # Also accepted via the standard Idempotency-Key request header.
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)

class EvidenceNormalizationRequest(BaseModel):
    """Optionally normalize only one hypothesis produced by the run."""

    hypothesis_id: int | None = None


class EvidenceNormalizationRead(BaseModel):
    sources_created: int
    evidence_created: int
    evidence_reused: int
    results_skipped: int
    hypotheses_normalized: int


class AnalysisRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    status: str
    inputs: dict[str, Any] | None
    result: dict[str, Any] | None
    queued_at: datetime
    started_at: datetime | None
    attempt: int
    max_attempts: int
    lease_until: datetime | None
    heartbeat_at: datetime | None
    available_at: datetime
    last_error: dict[str, Any] | None
    idempotency_key: str | None
    created_at: datetime
    completed_at: datetime | None
