"""Manual, attributable strategic context schemas; no generated facts are accepted."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ManualInput(BaseModel):
    provenance: Literal["manual"] = "manual"
    source_reference: str = Field(min_length=1, max_length=4000)


class MarketEntityCreate(ManualInput):
    name: str = Field(min_length=1, max_length=255)
    entity_type: str = Field(min_length=1, max_length=100)
    claim: str = Field(min_length=1, max_length=10000)
    verification_status: Literal["verified"] = "verified"


class CompetitorCreate(ManualInput):
    name: str = Field(min_length=1, max_length=255)
    competitor_type: str = Field(min_length=1, max_length=100)
    positioning: str | None = Field(default=None, max_length=10000)


class ICPSegmentCreate(ManualInput):
    name: str = Field(min_length=1, max_length=255)
    profile: str = Field(min_length=1, max_length=10000)
    job_to_be_done: str | None = Field(default=None, max_length=10000)
    priority: int = Field(default=3, ge=1, le=5)


class MonetizationAssumptionCreate(ManualInput):
    name: str = Field(min_length=1, max_length=255)
    assumption: str = Field(min_length=1, max_length=10000)
    value: str | None = Field(default=None, max_length=255)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class RiskMapEntryCreate(ManualInput):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=10000)
    probability: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    mitigation: str | None = Field(default=None, max_length=10000)
    owner: str | None = Field(default=None, max_length=255)


class StrategyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    provenance: Literal["manual"]
    source_reference: str
    created_at: datetime


class MarketEntityRead(MarketEntityCreate, StrategyRead): pass
class CompetitorRead(CompetitorCreate, StrategyRead): pass
class ICPSegmentRead(ICPSegmentCreate, StrategyRead): pass
class MonetizationAssumptionRead(MonetizationAssumptionCreate, StrategyRead): pass
class RiskMapEntryRead(RiskMapEntryCreate, StrategyRead): pass
