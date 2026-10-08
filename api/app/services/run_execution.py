"""Execution of an already leased analysis run."""
from __future__ import annotations

from decimal import Decimal
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnalysisRun, Evidence, EvidenceCandidate, EvidenceLink, EvidenceSource, Hypothesis, Project, Verdict
from app.engines.evidence import Evidence as EngineEvidence
from app.engines.verdict import VerdictEngine
from app.services.audit import record_audit_event
from app.services.evidence_normalization import canonical_url, normalize_research_results, source_cluster
from app.services.hypothesis_generator import starter_hypotheses
from app.services.openai_orchestrator import OpenAIOrchestrator
from app.services.project_report_snapshot import save_project_report_snapshot
from app.services.research import ResearchResult, TavilyResearchProvider
from app.services.research_pipeline.orchestration import run_research_pipeline
from app.settings import AnalysisSettings
from app.workers.run_worker import complete_run, fail_run, heartbeat


class AnalysisLimitExceeded(ValueError):
    """A per-run external-call or cost limit was reached."""


def _usage(research_calls: int = 0, tool_calls: int = 0, llm_usage: dict | None = None) -> dict[str, object]:
    llm = llm_usage or {}
    cost = llm.get("cost_usd", 0.0)
    return {
        "research_calls": research_calls,
        "tool_calls": tool_calls,
        "llm": {
            "prompt_tokens": int(llm.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(llm.get("completion_tokens", 0) or 0),
            "total_tokens": int(llm.get("total_tokens", 0) or 0),
        },
        "cost_usd": float(cost) if isinstance(cost, (int, float)) else 0.0,
    }


def execute_claimed_run(db: Session, run: AnalysisRun, *, research_provider=None,
                        orchestrator=None, settings: AnalysisSettings | None = None) -> AnalysisRun:
    """Execute an owned run while enforcing call and spend limits.

    Usage is stored in ``result`` and repeated in the audit event so the run is
    inspectable even after provider implementations change.
    """
    if run.status != "running" or not run.lease_token:
        return run
    token = run.lease_token
    project = db.get(Project, run.project_id)
    settings = settings or AnalysisSettings.from_env()
    provider = research_provider or TavilyResearchProvider()
    llm = orchestrator or OpenAIOrchestrator(settings=settings)
    research_calls = tool_calls = 0
    usage = _usage()
    try:
        if provider.is_configured and llm.is_configured:
            if settings.max_research_calls < 1:
                raise AnalysisLimitExceeded("research call limit reached")
            if settings.max_tool_calls < 2:
                raise AnalysisLimitExceeded("tool call limit reached")
            query = " ".join(part for part in (project.name, project.description or "") if part)
            # The pipeline writes stage checkpoints and source artifacts before synthesis,
            # so a retried leased run resumes completed research stages.
            documents = run_research_pipeline(db, run, provider, query, lease_token=token)
            # An empty completed search is authoritative; never issue a second provider request.
            research = [
                ResearchResult(title=item.title or item.url, url=item.url, content=item.content or "",
                               source_metadata=item.source_metadata)
                for item in documents
            ]
            research_calls, tool_calls = 1, 1
            context = {
                "name": project.name, "description": project.description, "geography": project.geography,
                "business_type": project.business_type, "budget": project.budget, "deadline_days": project.deadline_days,
                "language": project.language, "known_facts": project.known_facts or [], "run_inputs": run.inputs or {},
            }
            # Refresh ownership immediately before and after the potentially long LLM call.
            if not heartbeat(db, run.id, token):
                return db.get(AnalysisRun, run.id)
            items = llm.generate_hypotheses(context, research)
            if not heartbeat(db, run.id, token):
                return db.get(AnalysisRun, run.id)
            tool_calls += 1
            usage = _usage(research_calls, tool_calls, getattr(llm, "last_usage", None))
            if Decimal(str(usage["cost_usd"])) > settings.cost_cap_usd:
                raise AnalysisLimitExceeded("analysis cost cap exceeded")
            if not items:
                raise ValueError("empty hypothesis response")
            result: dict[str, object] = {
                "mode": "provider", "research_results": [item.to_dict() for item in research],
                "hypothesis_details": items,
            }
        else:
            items = starter_hypotheses(project)
            result = {"mode": "starter"}
        if not heartbeat(db, run.id, token):
            return db.get(AnalysisRun, run.id)
        usage = _usage(research_calls, tool_calls, getattr(llm, "last_usage", None))
        result.update(hypotheses_created=len(items), hypotheses=[item["statement"] for item in items], usage=usage, cost_usd=usage["cost_usd"])
        hypotheses: list[Hypothesis] = []
        for item in items:
            importance = item.get("importance", 0.5)
            importance = float(importance) if isinstance(importance, (int, float)) and 0 <= importance <= 1 else 0.5
            hypothesis = Hypothesis(project_id=run.project_id, analysis_run_id=run.id, statement=item["statement"],
                                    category=str(item.get("category", "problem")), importance=importance)
            db.add(hypothesis)
            hypotheses.append(hypothesis)
        db.flush()
        # A provider run persists its source claims before rendering verdicts;
        # starter mode intentionally produces UNPROVEN verdicts rather than
        # inventing research evidence.
        if provider.is_configured and llm.is_configured:
            # Persist extracted claims as reviewable candidates before any normalization.
            # Candidate status is deliberate: snippets never become decision evidence automatically.
            for hypothesis in hypotheses:
                for source in research:
                    claim = getattr(source, "content", None) or getattr(source, "snippet", None) or ""
                    if claim:
                        source_url = getattr(source, "url", None)
                        normalized_url = canonical_url(source_url) if source_url else None
                        db.add(EvidenceCandidate(project_id=run.project_id, hypothesis_id=hypothesis.id,
                            claim=str(claim), source_name=str(getattr(source, "title", None) or source_url or "research source"),
                            url=source_url, source_quality=0.0,
                            source_cluster=source_cluster(normalized_url) if normalized_url else "unknown"))
                normalize_research_results(db, project=project, hypothesis=hypothesis, results=research, analysis_run_id=run.id)
        db.flush()
        verdict_summaries = []
        for hypothesis in hypotheses:
            rows = db.scalars(select(Evidence).join(EvidenceLink).join(EvidenceSource).where(
                EvidenceLink.hypothesis_id == hypothesis.id, EvidenceSource.project_id == run.project_id
            )).all()
            evaluated = VerdictEngine().evaluate([EngineEvidence(
                tier=row.tier, direction=row.direction, relevance=row.relevance, source_quality=row.source_quality,
                observed_on=row.observed_on, category=row.category, source_cluster=row.source_cluster, independent=row.independent,
                evidence_status=row.evidence_status,
            ) for row in rows])
            db.add(Verdict(hypothesis_id=hypothesis.id, analysis_run_id=run.id, verdict=evaluated["verdict"],
                           rationale=json.dumps(evaluated, sort_keys=True)))
            verdict_summaries.append({"hypothesis_id": hypothesis.id, "verdict": evaluated["verdict"], "unknowns": evaluated["unknowns"]})
        result["verdicts"] = verdict_summaries
        # Make provider candidates available to the snapshot before conditional completion writes the final run row.
        run.result = result
        # Completion always leaves a decision-ready deterministic snapshot;
        # starter mode deliberately remains UNPROVEN rather than requiring evidence up front.
        save_project_report_snapshot(db, project, analysis_run=run)
        if complete_run(db, run.id, token, result, commit=False):
            record_audit_event(db, project_id=run.project_id, event_type="analysis_run.completed", entity_type="analysis_run",
                               entity_id=run.id, payload={"status": "completed", "hypotheses_created": len(items), "mode": result["mode"], "usage": usage, "cost_usd": usage["cost_usd"]})
            db.commit()
        else:
            db.rollback()
    except Exception as exc:
        usage = _usage(research_calls, tool_calls, getattr(llm, "last_usage", None))
        limit_exceeded = isinstance(exc, AnalysisLimitExceeded)
        error = {"code": "analysis_limit_exceeded" if limit_exceeded else "provider_failure", "stage": "research_or_synthesis", "type": type(exc).__name__}
        failure_result = {"mode": "provider", "usage": usage, "cost_usd": usage["cost_usd"]}
        if fail_run(db, run.id, token, error, commit=False, result=failure_result, terminal=limit_exceeded):
            record_audit_event(db, project_id=run.project_id, event_type="analysis_run.failed", entity_type="analysis_run",
                               entity_id=run.id, payload={"error_code": error["code"], "usage": usage, "cost_usd": usage["cost_usd"]})
            db.commit()
        else:
            db.rollback()
    db.expire_all()
    return db.get(AnalysisRun, run.id)
