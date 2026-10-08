"""Verdict evaluation and persistence endpoints."""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Evidence as ORMEvidence
from app.db.models import EvidenceLink, EvidenceSource, Hypothesis, Project, Verdict
from app.db.session import get_db
from app.engines.evidence import Evidence as EngineEvidence
from app.engines.verdict import VerdictEngine
from app.schemas.verdicts import VerdictRead
from app.services.audit import record_audit_event

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/hypotheses/{hypothesis_id}/verdict",
    tags=["verdicts"],
)


def hypothesis_in_project_or_404(project_id: int, hypothesis_id: int, db: Session) -> Hypothesis:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    hypothesis = db.scalar(
        select(Hypothesis).where(
            Hypothesis.id == hypothesis_id,
            Hypothesis.project_id == project_id,
        )
    )
    if hypothesis is None:
        # Do not reveal a hypothesis belonging to a different project.
        raise HTTPException(status_code=404, detail="Hypothesis not found in project")
    return hypothesis


def linked_engine_evidence(hypothesis_id: int, project_id: int, db: Session) -> list[EngineEvidence]:
    """Load only evidence linked to the hypothesis and owned by its project."""
    evidence_rows = db.scalars(
        select(ORMEvidence)
        .join(EvidenceLink, EvidenceLink.evidence_id == ORMEvidence.id)
        .join(EvidenceSource, ORMEvidence.source_id == EvidenceSource.id)
        .where(
            EvidenceLink.hypothesis_id == hypothesis_id,
            EvidenceSource.project_id == project_id,
        )
        .order_by(EvidenceLink.id)
    ).all()
    return [
        EngineEvidence(
            tier=evidence.tier,
            direction=evidence.direction,
            relevance=evidence.relevance,
            source_quality=evidence.source_quality,
            observed_on=evidence.observed_on,
            category=evidence.category,
            source_cluster=evidence.source_cluster,
            independent=evidence.independent,
            evidence_status=evidence.evidence_status,
        )
        for evidence in evidence_rows
    ]


def serialize_verdict(verdict: Verdict) -> VerdictRead:
    """Turn the persisted engine output in ``rationale`` into the API shape."""
    try:
        result = json.loads(verdict.rationale or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Stored verdict is invalid") from exc
    return VerdictRead(
        id=verdict.id,
        hypothesis_id=verdict.hypothesis_id,
        analysis_run_id=verdict.analysis_run_id,
        created_at=verdict.created_at,
        **result,
    )


@router.post("", response_model=VerdictRead, status_code=status.HTTP_201_CREATED)
def create_verdict(
    project_id: int,
    hypothesis_id: int,
    db: Annotated[Session, Depends(get_db)],
):
    hypothesis = hypothesis_in_project_or_404(project_id, hypothesis_id, db)
    result = VerdictEngine().evaluate(linked_engine_evidence(hypothesis.id, project_id, db))
    persisted = Verdict(
        hypothesis_id=hypothesis.id,
        analysis_run_id=hypothesis.analysis_run_id,
        verdict=result["verdict"],
        # The existing text field is used as an immutable snapshot of every
        # engine output; this permits GET to return the original calculation.
        rationale=json.dumps(result, sort_keys=True),
    )
    db.add(persisted)
    db.flush()
    record_audit_event(
        db,
        project_id=project_id,
        event_type="verdict.created",
        entity_type="verdict",
        entity_id=persisted.id,
        payload={"hypothesis_id": hypothesis.id, "analysis_run_id": persisted.analysis_run_id, "verdict": persisted.verdict},
    )
    db.commit()
    db.refresh(persisted)
    return serialize_verdict(persisted)


@router.get("", response_model=VerdictRead)
def get_latest_verdict(
    project_id: int,
    hypothesis_id: int,
    db: Annotated[Session, Depends(get_db)],
):
    hypothesis_in_project_or_404(project_id, hypothesis_id, db)
    persisted = db.scalar(
        select(Verdict)
        .where(Verdict.hypothesis_id == hypothesis_id)
        .order_by(Verdict.created_at.desc(), Verdict.id.desc())
        .limit(1)
    )
    if persisted is None:
        raise HTTPException(status_code=404, detail="Verdict not found")
    return serialize_verdict(persisted)
