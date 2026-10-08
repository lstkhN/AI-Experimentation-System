"""Project-scoped unit economics and capital-plan endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EconomicParameter, EconomicsModel, Project
from app.db.session import get_db
from app.engines.economics import FORMULA_VERSION, calculate_economics, simulate_economics
from app.schemas.economics import CapitalPlanRequest, EconomicsCalculateRequest, EconomicsSimulationRequest
from app.services.audit import record_audit_event

router = APIRouter(prefix="/api/v1/projects/{project_id}/economics", tags=["economics"])


def _calculate(request: EconomicsCalculateRequest | CapitalPlanRequest) -> dict:
    payload = request.model_dump()
    sensitivity = payload.pop("sensitivity", None)
    return calculate_economics(
        scenarios=payload["scenarios"],
        sensitivity_rates=sensitivity["monthly_churn_rates"] if sensitivity else None,
        capital_steps=payload["capital_steps"],
        currency=payload["currency"],
    )


def _save(project_id: int, request: EconomicsCalculateRequest | CapitalPlanRequest | EconomicsSimulationRequest, result: dict, db: Session) -> EconomicsModel:
    inputs = request.model_dump()
    # Every value entered through this API is user supplied; retaining that
    # provenance and the formula revision makes a snapshot reproducible.
    inputs["formula_version"] = result.get("formula_version", "v1.1")
    parameter_sources = {
        scenario.get("name", "base"): scenario.get("parameter_provenance", {})
        for scenario in inputs.get("scenarios", [])
    }
    inputs["input_provenance"] = {
        "default": "user_input",
        "parameters": parameter_sources,
        "simulation": "deterministic_seeded_rng" if isinstance(request, EconomicsSimulationRequest) else "not_used",
    }
    snapshot = EconomicsModel(
        project_id=project_id,
        economics_inputs=inputs,
        result=result,
        reliability=result.get("reliability", "INSUFFICIENT_CRITICAL_INPUTS"),
    )
    db.add(snapshot)
    db.flush()
    # Persist one auditable record per submitted economic parameter.
    for scenario in inputs.get("scenarios", []):
        provenance = scenario.get("parameter_provenance", {}) or {}
        for name, raw in scenario.items():
            if name in {"name", "parameter_provenance"} or isinstance(raw, (dict, list)):
                continue
            value = raw if isinstance(raw, (int, float)) else None
            source = provenance.get(name, {}) if isinstance(provenance.get(name, {}), dict) else {}
            db.add(EconomicParameter(
                economics_model_id=snapshot.id, name=name, base=value,
                source_type=source.get("source_type", "user_input"), source_id=source.get("source_id"),
                confidence=source.get("confidence", "LOW" if not source else "MEDIUM"),
                user_supplied=not bool(source.get("source_type") not in (None, "user_input")),
                observed=bool(source.get("observed", False)), benchmark=bool(source.get("benchmark", False)),
                inferred=bool(source.get("inferred", False)),
            ))
    record_audit_event(
        db,
        project_id=project_id,
        event_type="economics.snapshot.created",
        entity_type="economics_snapshot",
        entity_id=snapshot.id,
        payload={"currency": request.currency, "scenario_count": len(request.scenarios)},
    )
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.post("/calculate")
def calculate(project_id: int, request: EconomicsCalculateRequest, db: Annotated[Session, Depends(get_db)]) -> dict:
    """Calculate scenarios and save the exact assumptions/result as a snapshot."""
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    result = _calculate(request)
    snapshot = _save(project_id, request, result, db)
    return {"snapshot_id": snapshot.id, **result}


@router.post("/simulate")
def simulate(project_id: int, request: EconomicsSimulationRequest, db: Annotated[Session, Depends(get_db)]) -> dict:
    """Run a reproducible, non-LLM Monte Carlo economics simulation and save it."""
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    payload = request.model_dump()
    result = simulate_economics(**payload)
    snapshot = _save(project_id, request, result, db)
    record_audit_event(
        db, project_id=project_id, event_type="economics.simulation.created",
        entity_type="economics_snapshot", entity_id=snapshot.id,
        payload={"iterations": request.iterations, "seed": request.seed, "formula_version": FORMULA_VERSION},
    )
    db.commit()
    return {"snapshot_id": snapshot.id, **result}


@router.post("/capital-plan")
def create_capital_plan(project_id: int, request: CapitalPlanRequest, db: Annotated[Session, Depends(get_db)]) -> dict:
    """Save a capital plan; economics scenarios are optional for a funding-only plan."""
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    result = _calculate(request)
    snapshot = _save(project_id, request, result, db)
    return {"snapshot_id": snapshot.id, **result["capital_plan"], "scenarios": result["scenarios"], "unknowns": result["unknowns"], "reliability": result["reliability"]}


@router.get("/capital-plan")
def get_capital_plan(project_id: int, db: Annotated[Session, Depends(get_db)]) -> dict:
    """Return the latest saved capital-plan snapshot for a project."""
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    snapshots = db.scalars(
        select(EconomicsModel)
        .where(EconomicsModel.project_id == project_id)
        .order_by(EconomicsModel.id.desc())
    ).all()
    snapshot = next((item for item in snapshots if isinstance(item.result, dict) and "capital_plan" in item.result), None)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Capital plan not found")
    result = snapshot.result
    return {
        "snapshot_id": snapshot.id,
        **result["capital_plan"],
        "scenarios": result.get("scenarios", []),
        "unknowns": result.get("unknowns", []),
        "reliability": snapshot.reliability,
    }
