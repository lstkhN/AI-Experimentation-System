"""Durable, resumable search-to-cluster research orchestration."""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (AnalysisRun, ResearchClaim, ResearchClaimContradiction, ResearchDocument,
                           ResearchStageRun, ResearchVerification, ResearchVerificationAttempt)
from app.services.evidence_normalization import canonical_source_cluster
from app.services.research import json_normalize
from app.workers.run_worker import heartbeat
from .claims import extract_claims
from .extract import extract
from .fetch import fetch
from .verify import contradicts, verify_claim

STAGES = ("search", "fetch", "extract", "claims", "verify", "cluster")


class ResearchLeaseLost(RuntimeError):
    """The worker no longer owns the run and must not persist its work."""


def _heartbeat_or_raise(db: Session, run_id: int, lease_token: str | None) -> None:
    if lease_token is not None and not heartbeat(db, run_id, lease_token):
        raise ResearchLeaseLost("analysis run lease is no longer owned")


def _stage(db: Session, run_id: int, name: str, lease_token: str | None = None) -> ResearchStageRun:
    _heartbeat_or_raise(db, run_id, lease_token)
    item = db.scalar(select(ResearchStageRun).where(ResearchStageRun.analysis_run_id == run_id, ResearchStageRun.stage == name))
    if item is None:
        item = ResearchStageRun(analysis_run_id=run_id, stage=name, status="pending")
        db.add(item)
        db.flush()
    return item


def _complete(db: Session, stage: ResearchStageRun, lease_token: str | None = None,
              output: dict | None = None, **checkpoint: int) -> None:
    """Commit a stage only while the worker still owns an unexpired lease."""
    stage.status = "completed"
    stage.completed_at = datetime.now(timezone.utc)
    stage.error = None
    stage.checkpoint = checkpoint
    if output is not None:
        stage.output = json_normalize(output)
    # Keep the conditional lease update and artifact/stage writes in one
    # transaction so a stale worker cannot publish a checkpoint.
    if lease_token is not None and not heartbeat(db, stage.analysis_run_id, lease_token, commit=False):
        db.rollback()
        raise ResearchLeaseLost("analysis run lease is no longer owned")
    db.commit()


def _value(result, name, default=None):
    return result.get(name, default) if isinstance(result, dict) else getattr(result, name, default)


def provider_search(provider, query: str, *, max_results: int = 10):
    """Use the provider's documented ``max_results`` spelling, with legacy fallback."""
    try:
        return provider.search(query, max_results=max_results)
    except TypeError as exc:
        try:
            return provider.search(query)
        except TypeError:
            raise exc


def _documents(db: Session, run_id: int) -> list[ResearchDocument]:
    return list(db.scalars(select(ResearchDocument).where(ResearchDocument.analysis_run_id == run_id)))


def _claims(db: Session, run_id: int) -> list[ResearchClaim]:
    return list(db.scalars(select(ResearchClaim).join(ResearchDocument).where(ResearchDocument.analysis_run_id == run_id)))


def run_research_pipeline(db: Session, run: AnalysisRun, provider, query: str, *, max_results: int = 10,
                          lease_token: str | None = None) -> list[ResearchDocument]:
    """Run unfinished stages only, committing each completed stage for durable resume."""
    if run.status == "running" and not lease_token:
        raise ResearchLeaseLost("a lease token is required for a running analysis run")
    run_id, project_id = run.id, run.project_id
    current: ResearchStageRun | None = None
    try:
        current = _stage(db, run_id, "search", lease_token)
        if current.status != "completed":
            _heartbeat_or_raise(db, run_id, lease_token)
            current.status, current.started_at = "running", datetime.now(timezone.utc)
            db.flush()
            # Providers may return duplicate URLs; remove them before ORM work
            # rather than relying on autoflush/unique-constraint side effects.
            seen_urls: set[str] = set()
            results = provider_search(provider, query, max_results=max_results)
            _heartbeat_or_raise(db, run_id, lease_token)
            for result in results:
                _heartbeat_or_raise(db, run_id, lease_token)
                url = _value(result, "url")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                exists = db.scalar(select(ResearchDocument.id).where(ResearchDocument.analysis_run_id == run_id, ResearchDocument.url == url))
                if exists:
                    continue
                fetched_at = _value(result, "fetched_at")
                if isinstance(fetched_at, str):
                    try:
                        fetched_at = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
                    except ValueError:
                        fetched_at = None
                db.add(ResearchDocument(project_id=project_id, analysis_run_id=run_id, stage_run_id=current.id,
                    title=_value(result, "title"), url=url, content=_value(result, "content", ""),
                    source_metadata=json_normalize(_value(result, "source_metadata")), fetched_at=fetched_at))
            db.flush()
            _heartbeat_or_raise(db, run_id, lease_token)
            _complete(db, current, lease_token, documents=len(_documents(db, run_id)))
        documents = _documents(db, run_id)

        current = _stage(db, run_id, "fetch", lease_token)
        if current.status != "completed":
            _heartbeat_or_raise(db, run_id, lease_token)
            current.status, current.started_at = "running", datetime.now(timezone.utc)
            for document in documents:
                _heartbeat_or_raise(db, run_id, lease_token)
                # Search providers may already return document content and not
                # implement a separate fetch API. Preserve that content rather
                # than failing an otherwise valid legacy provider run.
                if callable(getattr(provider, "fetch", None)):
                    result = fetch(provider.fetch, document.url)
                    content = result["content"]
                    document.content = content if isinstance(content, str) else str(content)
                document.fetched_at = datetime.now(timezone.utc)
                document.stage_run_id = current.id
            _heartbeat_or_raise(db, run_id, lease_token)
            _complete(db, current, lease_token, documents=len(documents))

        current = _stage(db, run_id, "extract", lease_token)
        if current.status != "completed":
            _heartbeat_or_raise(db, run_id, lease_token)
            current.status, current.started_at = "running", datetime.now(timezone.utc)
            for document in documents:
                _heartbeat_or_raise(db, run_id, lease_token)
                document.content = extract({"url": document.url, "content": document.content or ""})["text"]
            _heartbeat_or_raise(db, run_id, lease_token)
            _complete(db, current, lease_token, documents=len(documents))

        current = _stage(db, run_id, "claims", lease_token)
        if current.status != "completed":
            _heartbeat_or_raise(db, run_id, lease_token)
            current.status, current.started_at = "running", datetime.now(timezone.utc)
            for document in documents:
                _heartbeat_or_raise(db, run_id, lease_token)
                for item in extract_claims({"url": document.url, "text": document.content or ""}):
                    exists = db.scalar(select(ResearchClaim.id).where(ResearchClaim.document_id == document.id, ResearchClaim.claim == item["claim"]))
                    if not exists:
                        db.add(ResearchClaim(document_id=document.id, claim=item["claim"]))
            db.flush()
            _heartbeat_or_raise(db, run_id, lease_token)
            _complete(db, current, lease_token, claims=len(_claims(db, run_id)))
        claims = _claims(db, run_id)

        current = _stage(db, run_id, "verify", lease_token)
        if current.status != "completed":
            _heartbeat_or_raise(db, run_id, lease_token)
            current.status, current.started_at = "running", datetime.now(timezone.utc)
            for claim in claims:
                _heartbeat_or_raise(db, run_id, lease_token)
                if claim.verifications:
                    continue
                metadata = claim.document.source_metadata or {}
                quality = float(metadata.get("source_quality", 0.0) or 0.0)
                cluster = canonical_source_cluster(claim.document.url)
                peer_clusters = {canonical_source_cluster(peer.document.url) for peer in claims
                                 if peer.claim == claim.claim and peer.id != claim.id}
                result = verify_claim({"claim": claim.claim}, methodology_available=bool(metadata.get("methodology_available")),
                    source_quality=quality, fetched_at=claim.document.fetched_at, source_cluster=cluster,
                    independent_clusters=len(peer_clusters))
                claim.status = result["status"]
                verification = ResearchVerification(claim_id=claim.id, status=result["status"], reason=result["verification_reason"],
                    methodology_available=bool(metadata.get("methodology_available")), source_quality=quality,
                    freshness_score=result["freshness_score"], independence_score=result["independence_score"], provenance=result["provenance"])
                db.add(verification); db.flush()
                db.add(ResearchVerificationAttempt(claim_id=claim.id, verification_id=verification.id, source_cluster=cluster,
                    status=result["status"], freshness_score=result["freshness_score"], independence_score=result["independence_score"], provenance=result["provenance"]))
            _heartbeat_or_raise(db, run_id, lease_token)
            _complete(db, current, lease_token, verifications=len(claims), output={"claim_ids": [claim.id for claim in claims]})

        current = _stage(db, run_id, "cluster", lease_token)
        if current.status != "completed":
            _heartbeat_or_raise(db, run_id, lease_token)
            current.status, current.started_at = "running", datetime.now(timezone.utc)
            contradiction_pairs: list[list[int]] = []
            for claim in claims:
                _heartbeat_or_raise(db, run_id, lease_token)
                claim.source_cluster = canonical_source_cluster(claim.document.url)
            for index, claim in enumerate(claims):
                for other in claims[index + 1:]:
                    if contradicts(claim.claim, other.claim):
                        first_id, second_id = sorted((claim.id, other.id))
                        exists = db.scalar(select(ResearchClaimContradiction.id).where(
                            ResearchClaimContradiction.claim_id == first_id,
                            ResearchClaimContradiction.contradicts_claim_id == second_id))
                        if not exists:
                            db.add(ResearchClaimContradiction(claim_id=first_id, contradicts_claim_id=second_id,
                                                              reason="same normalized claim with opposite polarity"))
                        contradiction_pairs.append([first_id, second_id])
            _heartbeat_or_raise(db, run_id, lease_token)
            _complete(db, current, lease_token, claims=len(claims), output={"contradictions": contradiction_pairs})
        return _documents(db, run_id)
    except Exception as exc:
        stage_name = current.stage if current is not None else None
        db.rollback()
        if stage_name is not None and not isinstance(exc, ResearchLeaseLost):
            failed = _stage(db, run_id, stage_name, lease_token)
            failed.status = "failed"
            failed.error = {"type": type(exc).__name__, "message": str(exc)}
            # Failure checkpoints are artifacts too; do not let a former owner
            # overwrite a run reclaimed after its lease expired.
            if lease_token is not None and not heartbeat(db, run_id, lease_token, commit=False):
                db.rollback()
            else:
                db.commit()
        raise
