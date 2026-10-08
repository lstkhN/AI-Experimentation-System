"""Project-level deterministic verdict endpoints."""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EconomicsModel, Hypothesis, Project, ProjectVerdict, Verdict
from app.db.session import get_db
from app.engines.project_verdict import ProjectVerdictEngine
from app.schemas.project_verdicts import ProjectVerdictRead
from app.services.audit import record_audit_event
from app.services.report_gaps import build_structured_report_gaps
from app.services.project_report_snapshot import save_project_report_snapshot

router = APIRouter(prefix="/api/v1/projects/{project_id}/verdict", tags=["project-verdicts"])


def _project_or_404(project_id: int, db: Session) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _latest_hypothesis_inputs(project_id: int, db: Session) -> list[dict]:
    hypotheses = db.scalars(
        select(Hypothesis).where(Hypothesis.project_id == project_id).order_by(Hypothesis.id)
    ).all()
    # This query is explicitly joined through Hypothesis, preventing a verdict
    # belonging to another project from ever being included in the roll-up.
    rows = db.scalars(
        select(Verdict)
        .join(Hypothesis, Verdict.hypothesis_id == Hypothesis.id)
        .where(Hypothesis.project_id == project_id)
        .order_by(Hypothesis.id, Verdict.created_at.desc(), Verdict.id.desc())
    ).all()
    latest: dict[int, Verdict] = {}
    for row in rows:
        latest.setdefault(row.hypothesis_id, row)

    inputs = []
    for hypothesis in hypotheses:
        item = {
            "hypothesis_id": hypothesis.id,
            "statement": hypothesis.statement,
            "importance": hypothesis.importance,
            "criticality": hypothesis.criticality,
            "is_blocking": hypothesis.is_blocking,
            "verdict": None,
            "coverage": 0,
            "support_score": 50,
            "rule": "missing_hypothesis_verdict",
            "unknowns": ["missing_hypothesis_verdict"],
            "decisive_facts": [],
        }
        if persisted := latest.get(hypothesis.id):
            try:
                snapshot = json.loads(persisted.rationale or "{}")
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=500, detail="Stored hypothesis verdict is invalid") from exc
            item.update({key: snapshot.get(key, item[key]) for key in item if key not in {"hypothesis_id", "statement", "importance", "criticality", "is_blocking"}})
            item["verdict"] = persisted.verdict
        inputs.append(item)
    return inputs


def _latest_economics_input(project_id: int, db: Session) -> tuple[dict | None, EconomicsModel | None]:
    snapshot = db.scalar(
        select(EconomicsModel)
        .where(EconomicsModel.project_id == project_id)
        .order_by(EconomicsModel.created_at.desc(), EconomicsModel.id.desc())
        .limit(1)
    )
    if snapshot is None:
        return None, None
    return {"snapshot_id": snapshot.id, "inputs": snapshot.economics_inputs, "result": snapshot.result, "reliability": snapshot.reliability}, snapshot


def _serialize(persisted: ProjectVerdict) -> ProjectVerdictRead:
    # Older immutable snapshots predate the structured-gap fields.  Enrich
    # only their response representation so they remain readable; new
    # snapshots persist the same deterministic fields in ``result``.
    result = {
        **build_structured_report_gaps(persisted.project.language),
        "decision": "VALIDATE", "action": "validate_critical_assumptions",
        "unresolved_critical_hypotheses": [],
        "market_attractiveness": {"status": "unknown", "summary": "No structured market or ICP evidence has been collected.", "market_signals": 0, "icp_segments": 0, "competitors": 0, "unknowns": ["market_attractiveness_not_measured"]},
        "business_viability": {"status": "unknown", "economics_status": "missing", "economics_reliability": "INSUFFICIENT_CRITICAL_INPUTS", "supported_hypotheses": 0, "hypotheses_assessed": 0, "monetization_assumptions": 0, "unknowns": ["no_economics_snapshot"]},
        "experiment_comparison": {"status": "unknown", "selected": [], "alternatives": [], "why_not_alternatives": []},
        "capital_recommendation": {"status": "unknown", "currency": None, "available_budget": None, "recommended_spend": 0, "gates": [], "recommendation": "Create a gated capital plan after validating economics."},
        **persisted.result,
    }
    return ProjectVerdictRead(
        id=persisted.id,
        project_id=persisted.project_id,
        economics_snapshot_id=persisted.economics_model_id,
        created_at=persisted.created_at,
        **result,
    )


@router.post("", response_model=ProjectVerdictRead, status_code=status.HTTP_201_CREATED)
def create_project_verdict(project_id: int, db: Annotated[Session, Depends(get_db)]):
    project = _project_or_404(project_id, db)
    persisted = save_project_report_snapshot(db, project)
    record_audit_event(
        db,
        project_id=project_id,
        event_type="project.verdict.created",
        entity_type="project_verdict",
        entity_id=persisted.id,
        payload={"verdict": persisted.verdict, "economics_snapshot_id": persisted.economics_model_id},
    )
    db.commit()
    db.refresh(persisted)
    return _serialize(persisted)


@router.get("", response_model=ProjectVerdictRead)
def get_latest_project_verdict(project_id: int, db: Annotated[Session, Depends(get_db)]):
    _project_or_404(project_id, db)
    persisted = db.scalar(
        select(ProjectVerdict)
        .where(ProjectVerdict.project_id == project_id)
        .order_by(ProjectVerdict.created_at.desc(), ProjectVerdict.id.desc())
        .limit(1)
    )
    if persisted is None:
        raise HTTPException(status_code=404, detail="Project verdict not found")
    return _serialize(persisted)
