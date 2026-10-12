"""Durable capital intelligence endpoints."""
from __future__ import annotations
from typing import Annotated
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db.models import CapitalAllocation, CapitalGate, CapitalPlan, EconomicsModel, Evidence, ExperimentRun, Hypothesis, Project
from app.db.session import get_db
from app.engines.capital_allocator import allocate_capital
from app.schemas.capital import AllocationRequest, CapitalPlanCreate, GateEvaluationRequest
from app.services.audit import record_audit_event

router = APIRouter(prefix="/api/v1/projects/{project_id}/capital-plans", tags=["capital-intelligence"])

# The brief's € notation is a reference ladder.  Amounts are in the plan's
# requested currency; no conversion is performed by the allocator.
FORMAL_LADDER = (
    ("€0: establish decision baseline", 0, "Persist reliable economics and clear fatal/adverse findings."),
    ("€100: validate demand", 100, "Collect verified evidence before the first paid test."),
    ("€500: repeat validated test", 500, "A completed experiment must meet its forecast."),
    ("€1000: scale only after replication", 1000, "Two completed experiments must meet their forecasts."),
)


def _formal_gates():
    from app.schemas.capital import CapitalGateCreate, UnlockCondition
    return [CapitalGateCreate(name=name, recommended_spend=spend, unlock_conditions=[
        UnlockCondition(metric="economics_reliable", operator="==", value=1),
        UnlockCondition(metric="fatal_hypotheses", operator="==", value=0),
        UnlockCondition(metric="adverse_evidence", operator="==", value=0),
        UnlockCondition(metric="failed_experiments", operator="==", value=0),
        *([UnlockCondition(metric="verified_evidence_count", operator=">=", value=1)] if spend >= 100 else []),
        *([UnlockCondition(metric="passed_experiments", operator=">=", value=1)] if spend >= 500 else []),
        *([UnlockCondition(metric="passed_experiments", operator=">=", value=2)] if spend >= 1000 else []),
    ]) for name, spend, _learning in FORMAL_LADDER]


def _persisted_metrics(project_id: int, db: Session) -> dict[str, float]:
    """Resolve gate inputs from durable project records, never caller claims."""
    verified = db.scalar(select(func.count(Evidence.id)).where(
        Evidence.source.has(project_id=project_id), Evidence.evidence_status == "verified"
    )) or 0
    adverse = db.scalar(select(func.count(Evidence.id)).where(
        Evidence.source.has(project_id=project_id), Evidence.evidence_status == "verified",
        Evidence.direction == "contradicting"
    )) or 0
    fatal = db.scalar(select(func.count(Hypothesis.id)).where(
        Hypothesis.project_id == project_id, Hypothesis.criticality == "FATAL"
    )) or 0
    completed = list(db.scalars(select(ExperimentRun).where(
        ExperimentRun.project_id == project_id, ExperimentRun.status == "completed"
    )))
    outcomes = [(item.evaluation or {}).get("outcome") for item in completed]
    passed = sum(outcome in {"met", "passed", "success"} for outcome in outcomes)
    failed = sum(outcome in {"below_forecast", "failed", "not_met", "failure"} for outcome in outcomes)
    latest_economics = db.scalar(select(EconomicsModel).where(
        EconomicsModel.project_id == project_id
    ).order_by(EconomicsModel.id.desc()).limit(1))
    return {
        "verified_evidence_count": float(verified), "blocking_hypotheses": float(fatal),
        "fatal_hypotheses": float(fatal), "adverse_evidence": float(adverse),
        "completed_experiments": float(len(completed)), "passed_experiments": float(passed),
        "failed_experiments": float(failed),
        "economics_reliable": float(latest_economics is not None and latest_economics.reliability == "RELIABLE"),
    }


def _evaluate_plan(plan: CapitalPlan, project_id: int, manual_metrics: dict[str, float], db: Session) -> list[dict]:
    derived_metrics = _persisted_metrics(project_id, db)
    # System-derived metrics are authoritative; only non-reserved manual metrics are accepted.
    derived_metrics.update({key: value for key, value in manual_metrics.items() if key not in derived_metrics})
    global_blockers = [name for name in ("fatal_hypotheses", "adverse_evidence", "failed_experiments") if derived_metrics[name] > 0]
    if not derived_metrics["economics_reliable"]:
        global_blockers.append("insufficient_economics_reliability")
    predecessor_unlocked = True
    output = []
    for gate in plan.gates:
        checks = []
        for condition in gate.unlock_condition or []:
            actual = derived_metrics.get(condition["metric"])
            passed = actual is not None and _comparison(actual, condition["operator"], condition["value"])
            checks.append({**condition, "actual": actual, "passed": passed})
        passed = predecessor_unlocked and not global_blockers and all(check["passed"] for check in checks)
        gate.status = "UNLOCKED" if passed else "LOCKED"
        gate.evaluation = {"passed": passed, "checks": checks, "blockers": global_blockers,
                           "blocked_by_previous_gate": not predecessor_unlocked,
                           "metrics": derived_metrics}
        output.append({"gate_id": gate.id, "name": gate.name, "status": gate.status, "evaluation": gate.evaluation})
        predecessor_unlocked = passed
    return output


def _plan(project_id: int, plan_id: int, db: Session) -> CapitalPlan:
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")
    plan = db.scalar(select(CapitalPlan).where(CapitalPlan.id == plan_id, CapitalPlan.project_id == project_id))
    if plan is None:
        raise HTTPException(404, "Capital plan not found")
    return plan


def _serialize(plan: CapitalPlan) -> dict:
    learning_by_name = {name: learning for name, _spend, learning in FORMAL_LADDER}
    return {"id": plan.id, "project_id": plan.project_id, "currency": plan.currency,
            "available_budget": plan.available_budget, "recommended_spend": plan.recommended_spend,
            "gates": [{"id": gate.id, "sequence": gate.sequence, "name": gate.name,
                       "recommended_spend": gate.recommended_spend, "unlock_conditions": gate.unlock_condition or [],
                       "learning_condition": learning_by_name.get(gate.name),
                       "status": gate.status, "evaluation": gate.evaluation} for gate in plan.gates],
            "allocations": [{"id": allocation.id, "gate_id": allocation.capital_gate_id,
                             "requested_spend": allocation.requested_spend, "allocated_spend": allocation.allocated_spend,
                             "status": allocation.status, "created_at": allocation.created_at.isoformat()}
                            for allocation in plan.allocations]}


@router.get("")
def list_plans(project_id: int, db: Annotated[Session, Depends(get_db)]):
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")
    plans = db.scalars(select(CapitalPlan).where(CapitalPlan.project_id == project_id).order_by(CapitalPlan.id.desc())).all()
    return [_serialize(plan) for plan in plans]


@router.post("")
def create_plan(project_id: int, data: CapitalPlanCreate, db: Annotated[Session, Depends(get_db)], idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    # SQLite turns competing read-then-write transactions into transient
    # "database is locked" errors. Retrying the *whole* transaction is
    # essential: retrying only commit would reuse a stale idempotency read.
    for attempt in range(5):
        try:
            if db.get(Project, project_id) is None:
                raise HTTPException(404, "Project not found")
            if idempotency_key:
                previous = db.scalar(select(CapitalPlan).where(CapitalPlan.project_id == project_id, CapitalPlan.idempotency_key == idempotency_key))
                if previous is not None:
                    return _serialize(previous)
            gates = list(data.gates) or _formal_gates()
            plan = CapitalPlan(project_id=project_id, currency=data.currency.upper(), available_budget=data.available_budget,
                               recommended_spend=sum(gate.recommended_spend for gate in gates), idempotency_key=idempotency_key)
            db.add(plan); db.flush()
            for sequence, gate in enumerate(gates, 1):
                db.add(CapitalGate(capital_plan_id=plan.id, sequence=sequence, name=gate.name,
                                   recommended_spend=gate.recommended_spend,
                                   unlock_condition=[item.model_dump() for item in gate.unlock_conditions], status="LOCKED"))
            record_audit_event(db, project_id=project_id, event_type="capital_plan.created", entity_type="capital_plan",
                               entity_id=plan.id, payload={"available_budget": plan.available_budget, "recommended_spend": plan.recommended_spend})
            db.commit(); db.refresh(plan)
            return _serialize(plan)
        except IntegrityError:
            db.rollback()
            previous = db.scalar(select(CapitalPlan).where(CapitalPlan.project_id == project_id, CapitalPlan.idempotency_key == idempotency_key)) if idempotency_key else None
            if previous is not None:
                return _serialize(previous)
            raise
        except OperationalError:
            db.rollback()
            if attempt == 4:
                raise
            time.sleep(.01 * (attempt + 1))


@router.get("/{plan_id}")
def get_plan(project_id: int, plan_id: int, db: Annotated[Session, Depends(get_db)]):
    return _serialize(_plan(project_id, plan_id, db))


def _comparison(actual: float, operator: str, expected: float) -> bool:
    return {">=": actual >= expected, ">": actual > expected, "<=": actual <= expected, "<": actual < expected, "==": actual == expected}[operator]


@router.post("/{plan_id}/gates/evaluate")
def evaluate_gates(project_id: int, plan_id: int, data: GateEvaluationRequest, db: Annotated[Session, Depends(get_db)]):
    plan = _plan(project_id, plan_id, db)
    output = _evaluate_plan(plan, project_id, data.metrics, db)
    record_audit_event(db, project_id=project_id, event_type="capital_gate.evaluated", entity_type="capital_plan", entity_id=plan.id, payload={"metrics": data.metrics})
    db.commit()
    return {"plan_id": plan.id, "gates": output}


@router.post("/{plan_id}/allocate")
def allocate(project_id: int, plan_id: int, data: AllocationRequest, db: Annotated[Session, Depends(get_db)], idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    for attempt in range(5):
        try:
            plan = db.scalar(select(CapitalPlan).where(CapitalPlan.id == plan_id, CapitalPlan.project_id == project_id).with_for_update())
            if plan is None:
                raise HTTPException(404, "Capital plan not found")
            if idempotency_key:
                previous = db.scalar(select(CapitalAllocation).where(CapitalAllocation.capital_plan_id == plan_id, CapitalAllocation.idempotency_key == idempotency_key))
                if previous is not None:
                    return {"plan_id": plan_id, "replayed": True, **(previous.result or {})}
            # Re-evaluate from durable facts inside the allocation transaction so
            # stale gate evaluations cannot fund a newly blocked project. Preserve
            # previously supplied non-system metrics (for example interview
            # counts), while refreshing all authoritative persisted metrics.
            persisted_metric_names = set(_persisted_metrics(project_id, db))
            manual_metrics = {}
            for gate in plan.gates:
                saved_metrics = (gate.evaluation or {}).get("metrics", {})
                manual_metrics.update({key: value for key, value in saved_metrics.items() if key not in persisted_metric_names})
            _evaluate_plan(plan, project_id, manual_metrics, db)
            requested_budget = plan.available_budget if data.available_budget is None else data.available_budget
            if requested_budget > plan.available_budget:
                raise HTTPException(422, "available_budget cannot exceed the capital plan budget")
            # ``reserved_budget`` is atomically claimed below. Summing
            # allocations is not safe under concurrent SQLite transactions.
            gate_committed = dict(db.execute(select(CapitalAllocation.capital_gate_id, func.coalesce(func.sum(CapitalAllocation.allocated_spend), 0)).where(CapitalAllocation.capital_plan_id == plan.id).group_by(CapitalAllocation.capital_gate_id)).all())
            available = min(max(0.0, plan.available_budget - float(plan.reserved_budget)), requested_budget)
            result = allocate_capital(
                available,
                [{"gate_id": gate.id, "recommended_spend": max(0.0, gate.recommended_spend - float(gate_committed.get(gate.id, 0))), "gate_unlocked": gate.status == "UNLOCKED"} for gate in plan.gates],
                candidate_experiments=[item.model_dump() for item in data.candidate_experiments] if any(gate.status == "UNLOCKED" for gate in plan.gates) else [],
            )
            reservation = sum(item["allocated_spend"] for item in result["allocations"])
            if reservation and db.execute(
                update(CapitalPlan)
                .where(CapitalPlan.id == plan.id, CapitalPlan.reserved_budget + reservation <= CapitalPlan.available_budget)
                .values(reserved_budget=CapitalPlan.reserved_budget + reservation)
            ).rowcount != 1:
                db.rollback()
                if attempt == 4:
                    raise HTTPException(409, "capital budget changed concurrently")
                time.sleep(.01 * (attempt + 1))
                continue
            for index, item in enumerate(result["allocations"]):
                db.add(CapitalAllocation(capital_plan_id=plan.id, capital_gate_id=item["gate_id"], requested_spend=item["requested_spend"], allocated_spend=item["allocated_spend"], status=item["status"], result=result, idempotency_key=idempotency_key if index == 0 else None))
            record_audit_event(db, project_id=project_id, event_type="capital_plan.allocated", entity_type="capital_plan", entity_id=plan.id, payload=result)
            db.commit()
            return {"plan_id": plan.id, **result}
        except IntegrityError:
            db.rollback()
            previous = db.scalar(select(CapitalAllocation).where(CapitalAllocation.capital_plan_id == plan_id, CapitalAllocation.idempotency_key == idempotency_key)) if idempotency_key else None
            if previous is not None:
                return {"plan_id": plan_id, "replayed": True, **(previous.result or {})}
            raise
        except OperationalError:
            db.rollback()
            if attempt == 4:
                raise
            time.sleep(.01 * (attempt + 1))
