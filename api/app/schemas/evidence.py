from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class EvidenceCreate(BaseModel):
    hypothesis_id: int | None = None
    content: str = Field(min_length=1)
    url: str | None = None
    source_name: str = "Manual source"
    source_type: str = "manual"
    direction: str = Field(default="supporting", pattern="^(supporting|contradicting)$")
    tier: str = Field(default="E1", pattern="^E[0-6]$")
    category: str = "problem"
    relevance: float = Field(default=1.0, ge=0.5, le=1)
    source_quality: float = Field(default=0.75, ge=0.5, le=1)
    observed_on: date | None = None
    source_cluster: str = "unknown"
    independent: bool = True
    # Candidates are retained as provenance but are not scoreable until verified.
    evidence_status: Literal["candidate", "verified", "rejected"] = "verified"
    candidate_claim: str | None = Field(default=None, min_length=1)
    verification_reason: str | None = None


class EvidenceVerificationUpdate(BaseModel):
    evidence_status: Literal["verified", "rejected"]
    verification_reason: str = Field(min_length=1)
    claim: str | None = Field(default=None, min_length=1)
    direction: Literal["supporting", "contradicting"] | None = None
    tier: str | None = Field(default=None, pattern="^E[1-6]$")
    category: str | None = None
    relevance: float | None = Field(default=None, ge=0.5, le=1)
    source_quality: float | None = Field(default=None, ge=0.5, le=1)
    observed_on: date | None = None
    independent: bool | None = None


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_id: int
    content: str
    direction: str
    tier: str
    category: str
    relevance: float
    source_quality: float
    observed_on: date | None
    source_cluster: str
    independent: bool
    candidate_claim: str | None
    evidence_status: str
    verification_reason: str | None
    captured_at: datetime
