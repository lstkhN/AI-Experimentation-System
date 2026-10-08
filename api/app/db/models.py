"""Persistence models for the Release 0.1 analysis domain."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy import CheckConstraint, Index, JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class HypothesisCriticality(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    FATAL = "FATAL"


class EconomicsReliability(str, Enum):
    RELIABLE = "RELIABLE"
    INSUFFICIENT_CRITICAL_INPUTS = "INSUFFICIENT_CRITICAL_INPUTS"


class ProjectDecision(str, Enum):
    """Actionable project decision, deliberately separate from evidence verdicts."""
    GO = "GO"
    VALIDATE = "VALIDATE"
    NO_GO = "NO_GO"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    geography: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    budget: Mapped[float | None] = mapped_column(nullable=True)
    deadline_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str] = mapped_column(String(2), default="en", nullable=False)
    known_facts: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    analysis_runs: Mapped[list[AnalysisRun]] = relationship(back_populates="project", cascade="all, delete-orphan")
    hypotheses: Mapped[list[Hypothesis]] = relationship(back_populates="project", cascade="all, delete-orphan")
    evidence_sources: Mapped[list[EvidenceSource]] = relationship(back_populates="project", cascade="all, delete-orphan")
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="project", cascade="all, delete-orphan")
    economics_models: Mapped[list[EconomicsModel]] = relationship(back_populates="project", cascade="all, delete-orphan")
    experiment_proposals: Mapped[list[ExperimentProposal]] = relationship(back_populates="project", cascade="all, delete-orphan")
    experiment_runs: Mapped[list[ExperimentRun]] = relationship(back_populates="project", cascade="all, delete-orphan")
    project_verdicts: Mapped[list[ProjectVerdict]] = relationship(back_populates="project", cascade="all, delete-orphan")
    market_entities: Mapped[list[MarketEntity]] = relationship(back_populates="project", cascade="all, delete-orphan")
    competitors: Mapped[list[Competitor]] = relationship(back_populates="project", cascade="all, delete-orphan")
    icp_segments: Mapped[list[ICPSegment]] = relationship(back_populates="project", cascade="all, delete-orphan")
    monetization_assumptions: Mapped[list[MonetizationAssumption]] = relationship(back_populates="project", cascade="all, delete-orphan")
    risk_map_entries: Mapped[list[RiskMapEntry]] = relationship(back_populates="project", cascade="all, delete-orphan")
    capital_plans: Mapped[list[CapitalPlan]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ManualProvenanceMixin:
    """Every strategic record is explicitly entered and attributable to a human source."""

    provenance: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    source_reference: Mapped[str] = mapped_column(Text, nullable=False)


class MarketEntity(ManualProvenanceMixin, Base):
    __tablename__ = "market_entities"
    __table_args__ = (CheckConstraint("provenance = 'manual'", name="ck_market_entities_manual_provenance"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False, default="verified", server_default="verified")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    project: Mapped[Project] = relationship(back_populates="market_entities")


class Competitor(ManualProvenanceMixin, Base):
    __tablename__ = "competitors"
    __table_args__ = (CheckConstraint("provenance = 'manual'", name="ck_competitors_manual_provenance"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    competitor_type: Mapped[str] = mapped_column(String(100), nullable=False)
    positioning: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    project: Mapped[Project] = relationship(back_populates="competitors")


class ICPSegment(ManualProvenanceMixin, Base):
    __tablename__ = "icp_segments"
    __table_args__ = (CheckConstraint("provenance = 'manual'", name="ck_icp_segments_manual_provenance"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    profile: Mapped[str] = mapped_column(Text, nullable=False)
    job_to_be_done: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    project: Mapped[Project] = relationship(back_populates="icp_segments")


class MonetizationAssumption(ManualProvenanceMixin, Base):
    __tablename__ = "monetization_assumptions"
    __table_args__ = (CheckConstraint("provenance = 'manual'", name="ck_monetization_assumptions_manual_provenance"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    assumption: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    project: Mapped[Project] = relationship(back_populates="monetization_assumptions")


class RiskMapEntry(ManualProvenanceMixin, Base):
    __tablename__ = "risk_map_entries"
    __table_args__ = (CheckConstraint("provenance = 'manual'", name="ck_risk_map_entries_manual_provenance"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    probability: Mapped[int] = mapped_column(Integer, nullable=False)
    impact: Mapped[int] = mapped_column(Integer, nullable=False)
    mitigation: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    project: Mapped[Project] = relationship(back_populates="risk_map_entries")


class ExperimentTemplate(Base):
    """Versioned, deterministic test-plan template shared by all projects."""

    __tablename__ = "experiment_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    rules: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ExperimentProposal(Base):
    """A project-owned immutable snapshot of a selected experiment template."""

    __tablename__ = "experiment_proposals"
    __table_args__ = (
        CheckConstraint("status IN ('proposed', 'accepted', 'rejected', 'completed')", name="ck_experiment_proposals_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    hypothesis_id: Mapped[int | None] = mapped_column(ForeignKey("hypotheses.id", ondelete="SET NULL"), nullable=True, index=True)
    template_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    rules: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed", server_default="proposed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project: Mapped[Project] = relationship(back_populates="experiment_proposals")
    hypothesis: Mapped[Hypothesis | None] = relationship(back_populates="experiment_proposals")
    experiment_runs: Mapped[list[ExperimentRun]] = relationship(back_populates="proposal")


class ExperimentRun(Base):
    """Locally operated experiment lifecycle; it never invokes external execution."""

    __tablename__ = "experiment_runs"
    __table_args__ = (
        CheckConstraint("status IN ('proposed', 'approved', 'running', 'completed', 'stopped')", name="ck_experiment_runs_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("experiment_proposals.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    forecast: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed", server_default="proposed")
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="experiment_runs")
    proposal: Mapped[ExperimentProposal | None] = relationship(back_populates="experiment_runs")
    measurements: Mapped[list[ExperimentMeasurement]] = relationship(back_populates="experiment_run", cascade="all, delete-orphan")
    approvals: Mapped[list[ExperimentApproval]] = relationship(back_populates="experiment_run", cascade="all, delete-orphan")
    actual_vs_forecast: Mapped[ActualVsForecast | None] = relationship(back_populates="experiment_run", cascade="all, delete-orphan", uselist=False)


class ExperimentMeasurement(Base):
    __tablename__ = "experiment_measurements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_run_id: Mapped[int] = mapped_column(ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    value: Mapped[float] = mapped_column(nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    experiment_run: Mapped[ExperimentRun] = relationship(back_populates="measurements")


class ExperimentApproval(Base):
    __tablename__ = "experiment_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_run_id: Mapped[int] = mapped_column(ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(20), nullable=False, default="approved", server_default="approved")
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    experiment_run: Mapped[ExperimentRun] = relationship(back_populates="approvals")


class ActualVsForecast(Base):
    __tablename__ = "actual_vs_forecast"
    __table_args__ = (UniqueConstraint("experiment_run_id", name="uq_actual_vs_forecast_run"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_run_id: Mapped[int] = mapped_column(ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    experiment_run: Mapped[ExperimentRun] = relationship(back_populates="actual_vs_forecast")


class EconomicsModel(Base):
    """Immutable snapshot of assumptions and deterministic economics output."""

    __tablename__ = "economics_models"
    __table_args__ = (CheckConstraint("reliability IN ('RELIABLE', 'INSUFFICIENT_CRITICAL_INPUTS')", name="ck_economics_models_reliability"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    economics_inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reliability: Mapped[str] = mapped_column(
        String(40), nullable=False, default=EconomicsReliability.INSUFFICIENT_CRITICAL_INPUTS.value,
        server_default=EconomicsReliability.INSUFFICIENT_CRITICAL_INPUTS.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project: Mapped[Project] = relationship(back_populates="economics_models")


class EconomicParameter(Base):
    __tablename__ = "economic_parameters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    economics_model_id: Mapped[int] = mapped_column(ForeignKey("economics_models.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    low: Mapped[float | None] = mapped_column(nullable=True)
    base: Mapped[float | None] = mapped_column(nullable=True)
    high: Mapped[float | None] = mapped_column(nullable=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, default="LOW")
    user_supplied: Mapped[bool] = mapped_column(default=False, nullable=False)
    observed: Mapped[bool] = mapped_column(default=False, nullable=False)
    benchmark: Mapped[bool] = mapped_column(default=False, nullable=False)
    inferred: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CapitalPlan(Base):
    """A durable, ordered budget plan.  Gates are evaluated before allocation."""
    __tablename__ = "capital_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    available_budget: Mapped[float] = mapped_column(nullable=False)
    recommended_spend: Mapped[float] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    project: Mapped[Project] = relationship(back_populates="capital_plans")
    gates: Mapped[list[CapitalGate]] = relationship(back_populates="plan", cascade="all, delete-orphan", order_by="CapitalGate.sequence")
    allocations: Mapped[list[CapitalAllocation]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class CapitalGate(Base):
    __tablename__ = "capital_gates"
    __table_args__ = (UniqueConstraint("capital_plan_id", "sequence", name="uq_capital_gate_plan_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    capital_plan_id: Mapped[int] = mapped_column(ForeignKey("capital_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    recommended_spend: Mapped[float] = mapped_column(nullable=False, default=0)
    unlock_condition: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="LOCKED", server_default="LOCKED")
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    plan: Mapped[CapitalPlan] = relationship(back_populates="gates")
    allocations: Mapped[list[CapitalAllocation]] = relationship(back_populates="gate")


class CapitalAllocation(Base):
    __tablename__ = "capital_allocations"
    __table_args__ = (Index("uq_capital_allocations_plan_idempotency", "capital_plan_id", "idempotency_key", unique=True),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    capital_plan_id: Mapped[int] = mapped_column(ForeignKey("capital_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    capital_gate_id: Mapped[int | None] = mapped_column(ForeignKey("capital_gates.id", ondelete="SET NULL"), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    requested_spend: Mapped[float] = mapped_column(nullable=False)
    allocated_spend: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    plan: Mapped[CapitalPlan] = relationship(back_populates="allocations")
    gate: Mapped[CapitalGate | None] = relationship(back_populates="allocations")


class ProjectVerdict(Base):
    """Immutable project-decision snapshot produced by ProjectVerdictEngine."""

    __tablename__ = "project_verdicts"
    __table_args__ = (CheckConstraint("decision IN ('GO', 'VALIDATE', 'NO_GO')", name="ck_project_verdicts_decision"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    economics_model_id: Mapped[int | None] = mapped_column(ForeignKey("economics_models.id", ondelete="SET NULL"), nullable=True)
    # Immutable input/provenance used to produce this decision snapshot.
    provenance_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    verdict: Mapped[str] = mapped_column(String(50), nullable=False)
    decision: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ProjectDecision.VALIDATE.value,
        server_default=ProjectDecision.VALIDATE.value,
    )
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project: Mapped[Project] = relationship(back_populates="project_verdicts")


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'completed', 'failed')", name="ck_analysis_runs_status"),
        UniqueConstraint("project_id", "idempotency_key", name="uq_analysis_runs_project_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="queued", server_default="queued", nullable=False)
    inputs: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3", nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    last_error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="analysis_runs")
    hypotheses: Mapped[list[Hypothesis]] = relationship(back_populates="analysis_run")
    verdicts: Mapped[list[Verdict]] = relationship(back_populates="analysis_run")


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    __table_args__ = (
        CheckConstraint("length(category) BETWEEN 1 AND 50", name="ck_hypotheses_category_length"),
        CheckConstraint("importance >= 0 AND importance <= 1", name="ck_hypotheses_importance_range"),
        CheckConstraint("criticality IN ('LOW', 'NORMAL', 'HIGH', 'FATAL')", name="ck_hypotheses_criticality"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    analysis_run_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="problem", server_default="problem", nullable=False)
    importance: Mapped[float] = mapped_column(default=0.5, server_default="0.5", nullable=False)
    criticality: Mapped[str] = mapped_column(
        String(10), nullable=False, default=HypothesisCriticality.NORMAL.value,
        server_default=HypothesisCriticality.NORMAL.value,
    )
    is_blocking: Mapped[bool] = mapped_column(default=False, server_default="0", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project: Mapped[Project] = relationship(back_populates="hypotheses")
    analysis_run: Mapped[AnalysisRun | None] = relationship(back_populates="hypotheses")
    evidence_links: Mapped[list[EvidenceLink]] = relationship(back_populates="hypothesis", cascade="all, delete-orphan")
    verdicts: Mapped[list[Verdict]] = relationship(back_populates="hypothesis", cascade="all, delete-orphan")
    experiment_proposals: Mapped[list[ExperimentProposal]] = relationship(back_populates="hypothesis")


class EvidenceSource(Base):
    __tablename__ = "evidence_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(50), default="other", nullable=False)
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project: Mapped[Project] = relationship(back_populates="evidence_sources")
    evidence: Mapped[list[Evidence]] = relationship(back_populates="source", cascade="all, delete-orphan")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("evidence_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(String(50), default="supporting", nullable=False)
    tier: Mapped[str] = mapped_column(String(2), default="E1", nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="problem", nullable=False)
    relevance: Mapped[float] = mapped_column(default=1.0, nullable=False)
    source_quality: Mapped[float] = mapped_column(default=0.75, nullable=False)
    observed_on: Mapped[date | None] = mapped_column(nullable=True)
    source_cluster: Mapped[str] = mapped_column(String(255), default="unknown", nullable=False)
    independent: Mapped[bool] = mapped_column(default=True, nullable=False)
    score: Mapped[float | None] = mapped_column(nullable=True)
    # Search output begins as a candidate. It cannot affect a verdict until reviewed.
    candidate_claim: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_status: Mapped[str] = mapped_column(String(20), nullable=False, default="verified", server_default="verified")
    verification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    source: Mapped[EvidenceSource] = relationship(back_populates="evidence")
    links: Mapped[list[EvidenceLink]] = relationship(back_populates="evidence", cascade="all, delete-orphan")


class EvidenceCandidate(Base):
    __tablename__ = "evidence_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    hypothesis_id: Mapped[int | None] = mapped_column(ForeignKey("hypotheses.id", ondelete="SET NULL"), nullable=True, index=True)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate", server_default="candidate")
    verification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_quality: Mapped[float] = mapped_column(default=0.0, nullable=False)
    source_cluster: Mapped[str] = mapped_column(String(255), default="unknown", nullable=False)
    observed_on: Mapped[date | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EvidenceLink(Base):
    __tablename__ = "evidence_links"
    __table_args__ = (UniqueConstraint("evidence_id", "hypothesis_id", name="uq_evidence_hypothesis"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False, index=True)
    hypothesis_id: Mapped[int] = mapped_column(ForeignKey("hypotheses.id", ondelete="CASCADE"), nullable=False, index=True)
    relation: Mapped[str] = mapped_column(String(50), default="supports", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    evidence: Mapped[Evidence] = relationship(back_populates="links")
    hypothesis: Mapped[Hypothesis] = relationship(back_populates="evidence_links")


class Verdict(Base):
    __tablename__ = "verdicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(ForeignKey("hypotheses.id", ondelete="CASCADE"), nullable=False, index=True)
    analysis_run_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True)
    verdict: Mapped[str] = mapped_column(String(50), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    hypothesis: Mapped[Hypothesis] = relationship(back_populates="verdicts")
    analysis_run: Mapped[AnalysisRun | None] = relationship(back_populates="verdicts")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project: Mapped[Project] = relationship(back_populates="audit_events")
