"""Reviewable research evidence candidates."""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Evidence, EvidenceCandidate, EvidenceLink, EvidenceSource, Project, Hypothesis
from app.db.session import get_db
from app.services.audit import record_audit_event

router = APIRouter(prefix="/api/v1/projects/{project_id}/evidence-candidates", tags=["evidence-candidates"])
class CandidateCreate(BaseModel):
    claim: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    url: str | None = None
    hypothesis_id: int | None = None
    source_quality: float = Field(default=0, ge=0, le=1)
    source_cluster: str = "unknown"
class CandidateDecision(BaseModel):
    verification_reason: str = Field(min_length=1)

def _project(project_id, db):
    if db.get(Project, project_id) is None: raise HTTPException(404, "Project not found")
@router.post("")
def create(project_id: int, data: CandidateCreate, db: Annotated[Session, Depends(get_db)]):
    _project(project_id, db)
    if data.hypothesis_id is not None:
        hypothesis = db.get(Hypothesis, data.hypothesis_id)
        if hypothesis is None or hypothesis.project_id != project_id:
            raise HTTPException(404, "Hypothesis not found in project")
    item=EvidenceCandidate(project_id=project_id, **data.model_dump()); db.add(item); db.commit(); db.refresh(item); return item
@router.get("")
def list_candidates(project_id: int, db: Annotated[Session, Depends(get_db)]):
    _project(project_id, db); return list(db.scalars(select(EvidenceCandidate).where(EvidenceCandidate.project_id==project_id).order_by(EvidenceCandidate.id)))
@router.post("/{candidate_id}/verify")
def verify(project_id: int, candidate_id: int, data: CandidateDecision, db: Annotated[Session, Depends(get_db)]):
    _project(project_id, db); item=db.scalar(select(EvidenceCandidate).where(EvidenceCandidate.id==candidate_id, EvidenceCandidate.project_id==project_id))
    if item is None: raise HTTPException(404,"Evidence candidate not found")
    item.status="verified"; item.verification_reason=data.verification_reason; db.commit(); db.refresh(item); return item
@router.post("/{candidate_id}/promote")
def promote(project_id: int, candidate_id: int, data: CandidateDecision, db: Annotated[Session, Depends(get_db)]):
    _project(project_id, db)
    item=db.scalar(select(EvidenceCandidate).where(EvidenceCandidate.id==candidate_id, EvidenceCandidate.project_id==project_id))
    if item is None: raise HTTPException(404,"Evidence candidate not found")
    if item.status != "verified": raise HTTPException(409,"Candidate must be verified before promotion")
    source = db.scalar(select(EvidenceSource).where(EvidenceSource.project_id==project_id, EvidenceSource.url==item.url)) if item.url else None
    if source is None:
        source=EvidenceSource(project_id=project_id,name=item.source_name,url=item.url,source_type="research"); db.add(source); db.flush()
    evidence = Evidence(source_id=source.id, content=item.claim, direction="supporting", tier="E1", category="problem", relevance=1.0, source_quality=max(item.source_quality, .5), source_cluster=item.source_cluster, evidence_status="verified", verification_reason=data.verification_reason)
    db.add(evidence); db.flush()
    if item.hypothesis_id is not None: db.add(EvidenceLink(evidence_id=evidence.id,hypothesis_id=item.hypothesis_id,relation="supports"))
    item.verification_reason=data.verification_reason; db.commit(); db.refresh(evidence); return evidence

@router.post("/{candidate_id}/reject")
def reject(project_id: int, candidate_id: int, data: CandidateDecision, db: Annotated[Session, Depends(get_db)]):
    _project(project_id, db); item=db.scalar(select(EvidenceCandidate).where(EvidenceCandidate.id==candidate_id, EvidenceCandidate.project_id==project_id))
    if item is None: raise HTTPException(404,"Evidence candidate not found")
    item.status="rejected"; item.verification_reason=data.verification_reason; db.commit(); db.refresh(item); return item
