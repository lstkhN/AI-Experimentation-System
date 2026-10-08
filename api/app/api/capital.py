"""Durable capital intelligence endpoints."""
from __future__ import annotations
from typing import Annotated
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db.models import CapitalAllocation, CapitalGate, CapitalPlan, Evidence, ExperimentRun, Hypothesis, Project
from app.db.session import get_db
from app.engines.capital_allocator import allocate_capital
from app.schemas.capital import AllocationRequest, CapitalPlanCreate, GateEvaluationRequest
from app.services.audit import record_audit_event

router = APIRouter(prefix="/api/v1/projects/{project_id}/capital-plans", tags=["capital-intelligence"])


def _plan(project_id: int, plan_id: int, db: Session) -> CapitalPlan:
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")
    plan = db.scalar(select(CapitalPlan).where(CapitalPlan.id == plan_id, CapitalPlan.project_id == project_id))
    if plan is None:
        raise HTTPException(404, "Capital plan not found")
    return plan


def _serialize(plan: CapitalPlan) -> dict:
    return {"id": plan.id, "project_id": plan.project_id, "currency": plan.currency,
            "available_budget": plan.available_budget, "recommended_spend": plan.recommended_spend,
            "gates": [{"id": gate.id, "sequence": gate.sequence, "name": gate.name,
                       "recommended_spend": gate.recommended_spend, "unlock_conditions": gate.unlock_condition or [],
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
            gates = list(data.gates)
            if not gates:
                critical = list(db.scalars(select(Hypothesis).where(Hypothesis.project_id == project_id, Hypothesis.is_blocking.is_(True)).order_by(Hypothesis.importance.desc())))
                from app.schemas.capital import CapitalGateCreate, UnlockCondition
                gates = [CapitalGateCreate(name=f"Validate: {item.statement[:70]}", recommended_spend=0, unlock_conditions=[UnlockCondition(metric="blocking_hypotheses", operator="<=", value=0)]) for item in critical]
                if not gates:
                    gates = [CapitalGateCreate(name="Evidence validation", recommended_spend=0, unlock_conditions=[UnlockCondition(metric="verified_evidence_count", operator=">=", value=1)])]
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
    # Resolve common gate metrics from persisted decision inputs. Caller metrics
    # may refine these values but cannot bypass project scoping.
    verified_evidence = db.scalar(select(func.count(Evidence.id)).where(Evidence.source.has(project_id=project_id), Evidence.evidence_status == "verified")) or 0
    blocking_hypotheses = db.scalar(select(func.count(Hypothesis.id)).where(Hypothesis.project_id == project_id, Hypothesis.is_blocking.is_(True))) or 0
    completed_runs = list(db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project_id, ExperimentRun.status == "completed")))
    passed_experiments = sum(1 for item in completed_runs if (item.evaluation or {}).get("outcome") in {"met", "passed", "success"})
    derived_metrics = {"verified_evidence_count": float(verified_evidence), "blocking_hypotheses": float(blocking_hypotheses), "completed_experiments": float(len(completed_runs)), "passed_experiments": float(passed_experiments)}
    # System-derived metrics are authoritative; only non-reserved manual metrics are accepted.
    reserved = set(derived_metrics)
    derived_metrics.update({key: value for key, value in data.metrics.items() if key not in reserved})
    predecessor_unlocked = True
    output = []
    for gate in plan.gates:
        checks = []
        for condition in gate.unlock_condition or []:
            actual = derived_metrics.get(condition["metric"])
            passed = actual is not None and _comparison(actual, condition["operator"], condition["value"])
            checks.append({**condition, "actual": actual, "passed": passed})
        passed = predecessor_unlocked and all(check["passed"] for check in checks)
        gate.status = "UNLOCKED" if passed else "LOCKED"
        gate.evaluation = {"passed": passed, "checks": checks, "blocked_by_previous_gate": not predecessor_unlocked}
        output.append({"gate_id": gate.id, "name": gate.name, "status": gate.status, "evaluation": gate.evaluation})
        predecessor_unlocked = passed
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
            requested_budget = plan.available_budget if data.available_budget is None else data.available_budget
            if requested_budget > plan.available_budget:
                raise HTTPException(422, "available_budget cannot exceed the capital plan budget")
            committed = db.scalar(select(func.coalesce(func.sum(CapitalAllocation.allocated_spend), 0)).where(CapitalAllocation.capital_plan_id == plan.id)) or 0
            # A gate can be funded in several passes, but never receives its
            # already committed spend again.
            gate_committed = dict(db.execute(select(CapitalAllocation.capital_gate_id, func.coalesce(func.sum(CapitalAllocation.allocated_spend), 0)).where(CapitalAllocation.capital_plan_id == plan.id).group_by(CapitalAllocation.capital_gate_id)).all())
            available = min(max(0.0, plan.available_budget - float(committed)), requested_budget)
            result = allocate_capital(available, [{"gate_id": gate.id, "recommended_spend": max(0.0, gate.recommended_spend - float(gate_committed.get(gate.id, 0))), "gate_unlocked": gate.status == "UNLOCKED"} for gate in plan.gates])
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
