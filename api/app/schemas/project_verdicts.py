"""API schema for immutable project verdict snapshots."""
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel


class ProjectDecision(str, Enum):
    """The portfolio action recommended by a project report."""

    GO = "GO"
    VALIDATE = "VALIDATE"
    NO_GO = "NO_GO"


class ReportLanguageMetadata(BaseModel):
    code: Literal["en", "ru"]
    source: Literal["project_intake"]


class ReportDataGap(BaseModel):
    section: Literal["icp", "market", "competitor", "monetization", "risk_map"]
    field: str
    status: Literal["unknown"]
    reason: Literal["not_collected_as_structured_data"]


class ReportSection(BaseModel):
    """Structured manual records, or explicit unknowns when none were supplied."""
    model_config = {"extra": "allow"}
    status: Literal["unknown", "collected"]
    data_gaps: list[ReportDataGap] = []


class ProjectVerdictRead(BaseModel):
    id: int
    project_id: int
    economics_snapshot_id: int | None
    verdict: str
    decision: ProjectDecision = ProjectDecision.VALIDATE
    action: str = "validate_critical_assumptions"
    rule: str
    evidence_coverage: int
    hypothesis_verdicts: list[dict[str, Any]]
    idea_summary: dict[str, Any] = {}
    success_conditions: list[dict[str, Any]] = []
    failure_conditions: list[dict[str, Any]] = []
    tested_hypotheses: list[dict[str, Any]] = []
    market_findings: list[dict[str, Any]] = []
    evidence_quality: dict[str, Any] = {}
    next_recommended_tests: list[dict[str, Any]] = []
    economics: dict[str, Any]
    decisive_facts: list[dict[str, Any]]
    unknowns: list[str]
    kill_gates: list[dict[str, Any]]
    unresolved_critical_hypotheses: list[dict[str, Any]] = []
    ranked_assumptions: list[dict[str, Any]]
    market_attractiveness: dict[str, Any] = {}
    business_viability: dict[str, Any] = {}
    experiment_comparison: dict[str, Any] = {}
    capital_recommendation: dict[str, Any] = {}
    language_metadata: ReportLanguageMetadata
    icp: ReportSection
    market: ReportSection
    competitor: ReportSection
    monetization: ReportSection
    risk_map: ReportSection
    data_gaps: list[ReportDataGap]
    created_at: datetime
