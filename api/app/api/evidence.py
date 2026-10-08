from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.models import Evidence, EvidenceLink, EvidenceSource, Hypothesis, Project
from app.db.session import get_db
from app.schemas.evidence import EvidenceCreate, EvidenceRead, EvidenceVerificationUpdate
from app.services.audit import record_audit_event

router = APIRouter(prefix="/api/v1/projects/{project_id}/evidence", tags=["evidence"])

@router.post("", response_model=EvidenceRead, status_code=status.HTTP_201_CREATED)
def create_evidence(project_id: int, data: EvidenceCreate, db: Annotated[Session, Depends(get_db)]):
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    hypothesis = None
    if data.hypothesis_id is not None:
        hypothesis = db.get(Hypothesis, data.hypothesis_id)
        if hypothesis is None or hypothesis.project_id != project_id:
            raise HTTPException(status_code=404, detail="Hypothesis not found in project")
    source = EvidenceSource(project_id=project_id, name=data.source_name, url=data.url, source_type=data.source_type)
    # Candidate input is provenance only: its supplied classification cannot
    # accidentally become decision evidence before an explicit review.
    is_candidate = data.evidence_status == "candidate"
    evidence = Evidence(
        source=source, content=data.content,
        direction="neutral" if is_candidate else data.direction,
        tier="E0" if is_candidate else data.tier,
        category=data.category, relevance=data.relevance, source_quality=data.source_quality,
        observed_on=data.observed_on, source_cluster=data.source_cluster, independent=data.independent,
        evidence_status=data.evidence_status, candidate_claim=data.candidate_claim or (data.content if is_candidate else None),
        verification_reason=data.verification_reason,
    )
    db.add(evidence)
    if hypothesis is not None:
        evidence.links.append(EvidenceLink(hypothesis=hypothesis, relation=data.direction))
    db.flush()
    record_audit_event(
        db,
        project_id=project_id,
        event_type="evidence.created",
        entity_type="evidence",
        entity_id=evidence.id,
        payload={"hypothesis_id": data.hypothesis_id, "source_id": evidence.source_id, "tier": evidence.tier},
    )
    db.commit()
    db.refresh(evidence)
    return evidence


@router.patch("/{evidence_id}/verification", response_model=EvidenceRead)
def verify_evidence(project_id: int, evidence_id: int, data: EvidenceVerificationUpdate,
                    db: Annotated[Session, Depends(get_db)]):
    """Review a candidate claim explicitly; review is the only promotion path."""
    evidence = db.get(Evidence, evidence_id)
    if evidence is None or evidence.source.project_id != project_id:
        raise HTTPException(status_code=404, detail="Evidence not found in project")
    if data.evidence_status == "verified" and (data.direction is None or data.tier is None):
        raise HTTPException(status_code=422, detail="Verified evidence requires direction and tier classification")
    evidence.evidence_status = data.evidence_status
    evidence.verification_reason = data.verification_reason
    if data.claim is not None:
        evidence.candidate_claim = data.claim
        evidence.content = data.claim
    # Classification values are only accepted as part of an explicit review.
    for field in ("direction", "tier", "category", "relevance", "source_quality", "observed_on", "independent"):
        value = getattr(data, field)
        if value is not None:
            setattr(evidence, field, value)
    db.flush()
    record_audit_event(
        db, project_id=project_id, event_type="evidence.verified" if data.evidence_status == "verified" else "evidence.rejected",
        entity_type="evidence", entity_id=evidence.id,
        payload={"status": data.evidence_status, "reason": data.verification_reason},
    )
    db.commit()
    db.refresh(evidence)
    return evidence
