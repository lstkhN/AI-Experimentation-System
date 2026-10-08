from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AnalysisRun, Hypothesis, Project
from app.db.session import get_db
from app.schemas.runs import AnalysisRunCreate, AnalysisRunRead, EvidenceNormalizationRead, EvidenceNormalizationRequest
from app.services.audit import record_audit_event
from app.services.evidence_normalization import normalize_research_results
from app.services.openai_orchestrator import OpenAIOrchestrator
from app.services.research import ResearchResult, TavilyResearchProvider
from app.services.run_execution import execute_claimed_run
from app.workers.run_worker import claim_run

router = APIRouter(prefix="/api/v1/projects/{project_id}/analysis-runs", tags=["analysis-runs"])


@router.post("", response_model=AnalysisRunRead, status_code=status.HTTP_202_ACCEPTED)
def create_analysis_run(project_id: int, run_in: AnalysisRunCreate, db: Annotated[Session, Depends(get_db)],
                        header_idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> AnalysisRun:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    key = header_idempotency_key or run_in.idempotency_key
    if header_idempotency_key and run_in.idempotency_key and header_idempotency_key != run_in.idempotency_key:
        raise HTTPException(status_code=422, detail="Idempotency-Key header and body value must match")
    if key:
        existing = db.scalar(select(AnalysisRun).where(AnalysisRun.project_id == project_id, AnalysisRun.idempotency_key == key))
        if existing is not None:
            return existing
    now = datetime.now(timezone.utc)
    run = AnalysisRun(project_id=project_id, status="queued", inputs=run_in.inputs, queued_at=now, available_at=now, idempotency_key=key)
    try:
        db.add(run)
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(AnalysisRun).where(AnalysisRun.project_id == project_id, AnalysisRun.idempotency_key == key))
        if existing is not None:
            return existing
        raise
    record_audit_event(db, project_id=project_id, event_type="analysis_run.created", entity_type="analysis_run", entity_id=run.id,
                       payload={"status": run.status, "inputs": run.inputs or {}})
    db.commit()
    db.refresh(run)
    return run


@router.get("", response_model=list[AnalysisRunRead])
def list_analysis_runs(project_id: int, db: Annotated[Session, Depends(get_db)]) -> list[AnalysisRun]:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return list(db.scalars(select(AnalysisRun).where(AnalysisRun.project_id == project_id).order_by(AnalysisRun.id)))


@router.post("/{run_id}/execute", response_model=AnalysisRunRead)
def execute_analysis_run(project_id: int, run_id: int, db: Annotated[Session, Depends(get_db)]) -> AnalysisRun:
    """Manual compatibility trigger; normal processing is done by workers."""
    run = db.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id, AnalysisRun.project_id == project_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    if run.status == "completed":
        return run
    claimed = claim_run(db, run_id)
    if claimed is None:
        raise HTTPException(status_code=409, detail=f"Analysis run is {run.status}")
    # Explicit injection retains compatibility with existing API integrations.
    return execute_claimed_run(db, claimed, research_provider=TavilyResearchProvider(), orchestrator=OpenAIOrchestrator())


@router.post("/{run_id}/normalize-evidence", response_model=EvidenceNormalizationRead)
def normalize_run_evidence(project_id: int, run_id: int, request: EvidenceNormalizationRequest,
                           db: Annotated[Session, Depends(get_db)]) -> EvidenceNormalizationRead:
    run = db.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id, AnalysisRun.project_id == project_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    if request.hypothesis_id is not None:
        hypotheses = list(db.scalars(select(Hypothesis).where(Hypothesis.id == request.hypothesis_id, Hypothesis.project_id == project_id,
                                                            Hypothesis.analysis_run_id == run.id)))
        if not hypotheses:
            raise HTTPException(status_code=404, detail="Hypothesis not found in analysis run")
    else:
        hypotheses = list(db.scalars(select(Hypothesis).where(Hypothesis.analysis_run_id == run.id)))
    research: list[ResearchResult] = []
    for item in (run.result or {}).get("research_results", []):
        if isinstance(item, dict) and isinstance(item.get("title"), str) and isinstance(item.get("url"), str):
            score = item.get("score")
            research.append(ResearchResult(
                item["title"], item["url"], item.get("content") if isinstance(item.get("content"), str) else "",
                float(score) if isinstance(score, (int, float)) else None,
                item.get("fetched_at") if isinstance(item.get("fetched_at"), str) else None,
                item.get("source_metadata") if isinstance(item.get("source_metadata"), dict) else None,
                bool(item.get("content_truncated")),
                item.get("original_content_length") if isinstance(item.get("original_content_length"), int) else None,
            ))
    project = db.get(Project, project_id)
    totals = {"sources_created": 0, "evidence_created": 0, "evidence_reused": 0, "results_skipped": 0}
    for hypothesis in hypotheses:
        summary = normalize_research_results(db, project=project, hypothesis=hypothesis, results=research, analysis_run_id=run.id)
        for key in totals:
            totals[key] += getattr(summary, key)
    db.commit()
    return EvidenceNormalizationRead(**totals, hypotheses_normalized=len(hypotheses))


@router.get("/{run_id}", response_model=AnalysisRunRead)
def get_analysis_run(project_id: int, run_id: int, db: Annotated[Session, Depends(get_db)]) -> AnalysisRun:
    run = db.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id, AnalysisRun.project_id == project_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    return run
