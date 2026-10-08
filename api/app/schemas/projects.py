from datetime import datetime

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.project_verdicts import ReportDataGap, ReportLanguageMetadata, ReportSection


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    geography: str | None = Field(default=None, max_length=255)
    business_type: str | None = Field(default=None, max_length=100)
    budget: float | None = Field(default=None, ge=0)
    deadline_days: int | None = Field(default=None, ge=1)
    language: str = Field(default="en", pattern="^(ru|en)$")
    known_facts: list[str] | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    geography: str | None
    business_type: str | None
    budget: float | None
    deadline_days: int | None
    language: str
    known_facts: list[str] | None
    created_at: datetime
    updated_at: datetime


class ProjectReportRead(BaseModel):
    """Decision report with explicit disclosures for uncaptured business areas."""

    model_config = ConfigDict(extra="allow")

    format_version: str
    project: dict[str, Any]
    project_verdict: dict[str, Any] | None
    language_metadata: ReportLanguageMetadata
    icp: ReportSection
    market: ReportSection
    competitor: ReportSection
    monetization: ReportSection
    risk_map: ReportSection
    data_gaps: list[ReportDataGap]


class ProjectHistoryEventRead(BaseModel):
    """Immutable audit event displayed in a project's activity history."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    event_type: str
    entity_type: str
    entity_id: int | None
    actor: str | None
    payload: dict | None
    created_at: datetime
