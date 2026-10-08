"""Reviewable research evidence candidates."""
from hashlib import sha256
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.models import Evidence, EvidenceCandidate, EvidenceLink, EvidenceSource, Project, Hypothesis
from app.db.session import get_db
from app.services.audit import record_audit_event
from app.services.evidence_normalization import canonical_source_cluster, canonical_url

router = APIRouter(prefix="/api/v1/projects/{project_id}/evidence-candidates", tags=["evidence-candidates"])
class CandidateCreate(BaseModel):
    claim: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    url: str | None = None
    hypothesis_id: int | None = None
    source_quality: float = Field(default=0, ge=0, le=1)
    source_cluster: str | None = None
class CandidateDecision(BaseModel):
    verification_reason: str = Field(min_length=1)


class CandidatePromotion(CandidateDecision):
    """Human classification required before a candidate becomes decision evidence."""
    direction: Literal["supporting", "contradicting"]
    tier: Literal["E1", "E2", "E3", "E4", "E5", "E6"]
    category: str = Field(min_length=1, max_length=50)

def _project(project_id, db):
    if db.get(Project, project_id) is None: raise HTTPException(404, "Project not found")


def _source_identity(url: str | None, name: str) -> str:
    """Return a fixed-width source identity; NULL URLs still deduplicate."""
    value = f"url:{url}" if url else f"name:{name.strip().casefold()}"
    return sha256(value.encode("utf-8")).hexdigest()


def _get_or_create_source(db: Session, project_id: int, name: str, url: str | None) -> EvidenceSource:
    identity_key = _source_identity(url, name)
    source = db.scalar(select(EvidenceSource).where(
        EvidenceSource.project_id == project_id, EvidenceSource.identity_key == identity_key
    ))
    if source is not None:
        return source
    # Rows created before URL-derived identities use legacy keys. Compare their
    # stored URLs canonically so a promotion does not duplicate that source.
    if url is not None:
        sources = db.scalars(select(EvidenceSource).where(
            EvidenceSource.project_id == project_id, EvidenceSource.url.is_not(None)
        ))
        source = next((row for row in sources if canonical_url(row.url) == url), None)
        if source is not None:
            return source
    try:
        with db.begin_nested():
            source = EvidenceSource(project_id=project_id, identity_key=identity_key,
                                    name=name, url=url, source_type="research")
            db.add(source)
            db.flush()
    except IntegrityError:
        source = db.scalar(select(EvidenceSource).where(
            EvidenceSource.project_id == project_id, EvidenceSource.identity_key == identity_key
        ))
        if source is None:
            raise
    return source
@router.post("")
def create(project_id: int, data: CandidateCreate, db: Annotated[Session, Depends(get_db)]):
    _project(project_id, db)
    if data.hypothesis_id is not None:
        hypothesis = db.get(Hypothesis, data.hypothesis_id)
        if hypothesis is None or hypothesis.project_id != project_id:
            raise HTTPException(404, "Hypothesis not found in project")
    values = data.model_dump()
    normalized_url = canonical_url(data.url) if data.url else None
    # URLs define their source identity and independence cluster; callers may
    # only supply a cluster for URL-less sources.
    if data.url:
        values["source_cluster"] = canonical_source_cluster(normalized_url)
    elif values["source_cluster"] is None:
        values["source_cluster"] = "unknown"
    item = EvidenceCandidate(project_id=project_id, **values)
    db.add(item); db.commit(); db.refresh(item); return item
@router.get("")
def list_candidates(project_id: int, db: Annotated[Session, Depends(get_db)]):
    _project(project_id, db); return list(db.scalars(select(EvidenceCandidate).where(EvidenceCandidate.project_id==project_id).order_by(EvidenceCandidate.id)))
@router.post("/{candidate_id}/verify")
def verify(project_id: int, candidate_id: int, data: CandidateDecision, db: Annotated[Session, Depends(get_db)]):
    _project(project_id, db); item=db.scalar(select(EvidenceCandidate).where(EvidenceCandidate.id==candidate_id, EvidenceCandidate.project_id==project_id))
    if item is None: raise HTTPException(404,"Evidence candidate not found")
    item.status="verified"; item.verification_reason=data.verification_reason; db.commit(); db.refresh(item); return item
@router.post("/{candidate_id}/promote")
def promote(project_id: int, candidate_id: int, data: CandidatePromotion, db: Annotated[Session, Depends(get_db)]):
    _project(project_id, db)
    # Row locking serializes competing promotion requests for this candidate.
    item=db.scalar(select(EvidenceCandidate).where(EvidenceCandidate.id==candidate_id, EvidenceCandidate.project_id==project_id).with_for_update())
    if item is None: raise HTTPException(404,"Evidence candidate not found")
    if item.status != "verified": raise HTTPException(409,"Candidate must be verified before promotion")
    # The unique evidence.candidate_id link is both the canonical promotion
    # record and the database-level idempotency guard.
    evidence = db.scalar(select(Evidence).where(Evidence.candidate_id == item.id))
    if evidence is not None:
        return evidence
    # The unique project/identity key and savepoint retry make source creation
    # safe when independent promotion requests arrive concurrently.
    canonical_source_url = canonical_url(item.url) if item.url else None
    source = _get_or_create_source(db, project_id, item.source_name, canonical_source_url)
    # The unique candidate_id index makes SQLite safe even though it ignores
    # SELECT ... FOR UPDATE.  Savepoint rollback leaves the caller transaction
    # usable so a competing insert can be re-queried deterministically.
    try:
        with db.begin_nested():
            evidence = Evidence(source_id=source.id, candidate_id=item.id, content=item.claim, direction=data.direction, tier=data.tier, category=data.category, relevance=1.0, source_quality=max(item.source_quality, .5), source_cluster=canonical_source_cluster(canonical_source_url) if item.url else item.source_cluster, evidence_status="verified", verification_reason=data.verification_reason)
            db.add(evidence)
            db.flush()
            if item.hypothesis_id is not None:
                db.add(EvidenceLink(evidence_id=evidence.id, hypothesis_id=item.hypothesis_id, relation=data.direction))
    except IntegrityError:
        evidence = db.scalar(select(Evidence).where(Evidence.candidate_id == item.id))
        if evidence is None:
            raise
    item.verification_reason=data.verification_reason; db.commit(); db.refresh(evidence); return evidence

@router.post("/{candidate_id}/reject")
def reject(project_id: int, candidate_id: int, data: CandidateDecision, db: Annotated[Session, Depends(get_db)]):
    _project(project_id, db); item=db.scalar(select(EvidenceCandidate).where(EvidenceCandidate.id==candidate_id, EvidenceCandidate.project_id==project_id))
    if item is None: raise HTTPException(404,"Evidence candidate not found")
    item.status="rejected"; item.verification_reason=data.verification_reason; db.commit(); db.refresh(item); return item
