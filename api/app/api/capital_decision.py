"""Decision-oriented aliases for capital intelligence."""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import CapitalGate, CapitalPlan, Project
from app.db.session import get_db
from app.schemas.capital import CapitalPlanCreate, GateEvaluationRequest, AllocationRequest
from app.api.capital import create_plan, _plan, evaluate_gates, allocate

router = APIRouter(prefix="/api/v1/projects/{project_id}/capital", tags=["capital-decision"])

@router.post("/plan")
def plan_alias(project_id: int, data: CapitalPlanCreate, db: Annotated[Session, Depends(get_db)]):
    return create_plan(project_id, data, db)

@router.get("/plan/{plan_id}")
def get_plan_alias(project_id: int, plan_id: int, db: Annotated[Session, Depends(get_db)]):
    from app.api.capital import _serialize
    return _serialize(_plan(project_id, plan_id, db))

@router.post("/plan/{plan_id}/allocate")
def allocate_alias(project_id: int, plan_id: int, data: AllocationRequest, db: Annotated[Session, Depends(get_db)]):
    return allocate(project_id, plan_id, data, db)

@router.post("/plan/{plan_id}/gates/evaluate")
def evaluate_alias(project_id: int, plan_id: int, data: GateEvaluationRequest, db: Annotated[Session, Depends(get_db)]):
    return evaluate_gates(project_id, plan_id, data, db)

@router.post("/gates/{gate_id}/evaluate")
def evaluate_gate_alias(project_id: int, gate_id: int, data: GateEvaluationRequest, db: Annotated[Session, Depends(get_db)]):
    gate = db.get(CapitalGate, gate_id)
    if gate is None: raise HTTPException(404, "Capital gate not found")
    plan = _plan(project_id, gate.capital_plan_id, db)
    result = evaluate_gates(project_id, plan.id, data, db)
    return next((item for item in result["gates"] if item["gate_id"] == gate_id), result)
