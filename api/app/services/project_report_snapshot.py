"""Persist deterministic, decision-report snapshots from current project state."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (AnalysisRun, CapitalPlan, Competitor, EconomicsModel, ExperimentProposal,
                           ExperimentRun, Hypothesis, ICPSegment, MarketEntity, MonetizationAssumption,
                           Project, ProjectVerdict, ResearchClaim, ResearchClaimContradiction, ResearchDocument,
                           ResearchStageRun, RiskMapEntry, Verdict)
from app.engines.project_verdict import ProjectVerdictEngine


def _hypothesis_inputs(project_id: int, db: Session) -> list[dict[str, Any]]:
    hypotheses = list(db.scalars(select(Hypothesis).where(Hypothesis.project_id == project_id).order_by(Hypothesis.id)))
    rows = list(db.scalars(select(Verdict).join(Hypothesis, Verdict.hypothesis_id == Hypothesis.id)
                           .where(Hypothesis.project_id == project_id)
                           .order_by(Hypothesis.id, Verdict.created_at.desc(), Verdict.id.desc())))
    latest: dict[int, Verdict] = {}
    for row in rows:
        latest.setdefault(row.hypothesis_id, row)
    output = []
    for hypothesis in hypotheses:
        item: dict[str, Any] = {"hypothesis_id": hypothesis.id, "statement": hypothesis.statement,
            "importance": hypothesis.importance, "criticality": hypothesis.criticality, "is_blocking": hypothesis.is_blocking,
            "verdict": None, "coverage": 0, "support_score": 50,
            "rule": "missing_hypothesis_verdict", "unknowns": ["missing_hypothesis_verdict"], "decisive_facts": []}
        if stored := latest.get(hypothesis.id):
            try:
                snapshot = json.loads(stored.rationale or "{}")
            except json.JSONDecodeError:
                snapshot = {}
            item.update({key: snapshot.get(key, item[key]) for key in item if key not in {"hypothesis_id", "statement", "importance", "criticality", "is_blocking"}})
            item["verdict"] = stored.verdict
        output.append(item)
    return output


def _economics(project_id: int, db: Session) -> tuple[dict[str, Any] | None, EconomicsModel | None]:
    # VOI is persisted for audit/history, but it must not become the primary
    # unit-economics snapshot used by verdicts and capital gates.
    snapshots = db.scalars(
        select(EconomicsModel).where(EconomicsModel.project_id == project_id)
        .order_by(EconomicsModel.created_at.desc(), EconomicsModel.id.desc())
    ).all()
    snapshot = next(
        (item for item in snapshots if not isinstance(item.result, dict) or "value_of_information" not in item.result),
        None,
    )
    if snapshot is None:
        return None, None
    return {"snapshot_id": snapshot.id, "inputs": snapshot.economics_inputs, "result": snapshot.result, "reliability": snapshot.reliability}, snapshot


def _persisted_research(db: Session, run: AnalysisRun | None) -> list[dict[str, Any]]:
    """Render durable documents (and their stage checkpoint) for a report."""
    if run is None:
        return []
    stages = {stage.id: stage for stage in db.scalars(select(ResearchStageRun).where(
        ResearchStageRun.analysis_run_id == run.id
    ))}
    documents = list(db.scalars(select(ResearchDocument).where(
        ResearchDocument.analysis_run_id == run.id
    ).order_by(ResearchDocument.id)))
    if documents:
        claims = list(db.scalars(select(ResearchClaim).join(ResearchDocument).where(
            ResearchDocument.analysis_run_id == run.id
        )))
        contradictions = {link.claim_id for link in db.scalars(select(ResearchClaimContradiction).join(
            ResearchClaim, ResearchClaimContradiction.claim_id == ResearchClaim.id).join(
            ResearchDocument, ResearchClaim.document_id == ResearchDocument.id).where(
            ResearchDocument.analysis_run_id == run.id
        ))} | {link.contradicts_claim_id for link in db.scalars(select(ResearchClaimContradiction).join(
            ResearchClaim, ResearchClaimContradiction.claim_id == ResearchClaim.id).join(
            ResearchDocument, ResearchClaim.document_id == ResearchDocument.id).where(
            ResearchDocument.analysis_run_id == run.id
        ))}
        by_document: dict[int, list[dict[str, Any]]] = {}
        for claim in claims:
            verification = claim.verifications[0] if claim.verifications else None
            by_document.setdefault(claim.document_id, []).append({"claim": claim.claim, "status": claim.status,
                "source_cluster": claim.source_cluster, "contradicted": claim.id in contradictions,
                "verification": None if verification is None else {"freshness_score": verification.freshness_score,
                    "independence_score": verification.independence_score, "provenance": verification.provenance}})
        return [{
            "title": document.title or document.url, "url": document.url, "content": document.content or "",
            "fetched_at": document.fetched_at.isoformat() if document.fetched_at else None,
            "source_metadata": document.source_metadata, "claims": by_document.get(document.id, []),
            "stage": stages[document.stage_run_id].stage if document.stage_run_id in stages else None,
            "stage_status": stages[document.stage_run_id].status if document.stage_run_id in stages else None,
        } for document in documents]
    # Compatibility with reports produced before durable research artifacts.
    return (run.result or {}).get("research_results", [])


def save_project_report_snapshot(db: Session, project: Project, *, analysis_run: AnalysisRun | None = None) -> ProjectVerdict:
    """Create an immutable current report snapshot without any LLM arithmetic."""
    economics, economics_model = _economics(project.id, db)
    run = analysis_run or db.scalar(select(AnalysisRun).where(AnalysisRun.project_id == project.id)
                                    .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc()).limit(1))
    research = _persisted_research(db, run)
    proposals = {item.id: item for item in db.scalars(select(ExperimentProposal).where(
        ExperimentProposal.project_id == project.id).order_by(ExperimentProposal.id))}
    experiments = [{"id": item.id, "proposal_id": item.proposal_id, "status": item.status, "title": item.title,
                    "rationale": proposals[item.proposal_id].rationale if item.proposal_id in proposals else None,
                    "template_key": proposals[item.proposal_id].template_key if item.proposal_id in proposals else None,
                    "outcome": (item.evaluation or {}).get("outcome", "unknown")}
                   for item in db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project.id)
                                          .order_by(ExperimentRun.id))]
    # Proposals are alternatives even before an operator creates a run.
    experiments.extend({"id": item.id, "status": item.status, "title": item.title,
                        "rationale": item.rationale, "template_key": item.template_key, "outcome": "not_run"}
                       for item in proposals.values() if not any(run.get("proposal_id") == item.id for run in experiments))
    market_context = {
        "market_entities": list(db.scalars(select(MarketEntity).where(MarketEntity.project_id == project.id).order_by(MarketEntity.id))),
        "competitors": list(db.scalars(select(Competitor).where(Competitor.project_id == project.id).order_by(Competitor.id))),
        "icp_segments": list(db.scalars(select(ICPSegment).where(ICPSegment.project_id == project.id).order_by(ICPSegment.id))),
        "monetization_assumptions": list(db.scalars(select(MonetizationAssumption).where(MonetizationAssumption.project_id == project.id).order_by(MonetizationAssumption.id))),
        "risk_map": list(db.scalars(select(RiskMapEntry).where(RiskMapEntry.project_id == project.id).order_by(RiskMapEntry.id))),
    }
    latest_capital_plan = db.scalar(select(CapitalPlan).where(CapitalPlan.project_id == project.id)
                                     .order_by(CapitalPlan.created_at.desc(), CapitalPlan.id.desc()).limit(1))
    capital_plan = None if latest_capital_plan is None else {
        "currency": latest_capital_plan.currency, "available_budget": latest_capital_plan.available_budget,
        "recommended_spend": latest_capital_plan.recommended_spend,
        "gates": [{"id": gate.id, "name": gate.name, "recommended_spend": gate.recommended_spend,
                   "status": gate.status, "unlock_conditions": gate.unlock_condition or []}
                  for gate in latest_capital_plan.gates],
    }
    intake = {key: getattr(project, key) for key in ("name", "description", "geography", "business_type", "budget", "deadline_days", "known_facts")}
    def provenance_rows(rows):
        return [{key: value for key, value in {
            "id": row.id, "project_id": row.project_id,
            **{column.name: getattr(row, column.name) for column in row.__table__.columns
               if column.name not in {"id", "project_id", "created_at", "updated_at"}},
        }.items() if value is not None} for row in rows]
    provenance = {
        "project": intake,
        "market_context": {key: provenance_rows(value) for key, value in market_context.items()},
        "research": research,
        "experiments": experiments,
        "economics_snapshot_id": economics_model.id if economics_model else None,
    }
    result = ProjectVerdictEngine().evaluate(_hypothesis_inputs(project.id, db), economics, project.language,
                                             intake=intake, research_results=research, experiment_results=experiments,
                                             market_context=market_context, capital_plan=capital_plan)
    if run:
        result["analysis_run_id"] = run.id
    persisted = ProjectVerdict(project_id=project.id,
                               economics_model_id=economics_model.id if economics_model else None,
                               verdict=result["verdict"], decision=result["decision"], result=result,
                               provenance_snapshot=provenance)
    db.add(persisted)
    db.flush()
    return persisted
