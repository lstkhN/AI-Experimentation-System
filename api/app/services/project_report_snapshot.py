"""Persist deterministic, decision-report snapshots from current project state."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (AnalysisRun, CapitalPlan, Competitor, EconomicsModel, ExperimentProposal,
                           ExperimentRun, Hypothesis, ICPSegment, MarketEntity, MonetizationAssumption,
                           Project, ProjectVerdict, Verdict)
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
    snapshot = db.scalar(select(EconomicsModel).where(EconomicsModel.project_id == project_id)
                         .order_by(EconomicsModel.created_at.desc(), EconomicsModel.id.desc()).limit(1))
    if snapshot is None:
        return None, None
    return {"snapshot_id": snapshot.id, "inputs": snapshot.economics_inputs, "result": snapshot.result, "reliability": snapshot.reliability}, snapshot


def save_project_report_snapshot(db: Session, project: Project, *, analysis_run: AnalysisRun | None = None) -> ProjectVerdict:
    """Create an immutable current report snapshot without any LLM arithmetic."""
    economics, economics_model = _economics(project.id, db)
    run = analysis_run or db.scalar(select(AnalysisRun).where(AnalysisRun.project_id == project.id)
                                    .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc()).limit(1))
    research = (run.result or {}).get("research_results", []) if run else []
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
