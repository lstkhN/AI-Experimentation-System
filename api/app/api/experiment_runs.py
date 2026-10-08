"""Project-isolated, local-only experiment lifecycle APIs."""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import ActualVsForecast, ExperimentApproval, ExperimentMeasurement, ExperimentProposal, ExperimentRun, Project
from app.db.session import get_db
from app.engines.experiment_evaluation import evaluate
from app.schemas.experiment_runs import (ActualVsForecastRead, ApprovalCreate, ApprovalRead,
    ExperimentRunCreate, ExperimentRunRead, ExperimentRunUpdate, MeasurementCreate,
    MeasurementRead, MeasurementUpdate)
from app.services.audit import record_audit_event
from app.services.project_report_snapshot import save_project_report_snapshot

router = APIRouter(prefix="/api/v1/projects/{project_id}/experiment-runs", tags=["experiment-runs"])


def _project(project_id: int, db: Session) -> None:
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")


def _run(project_id: int, run_id: int, db: Session) -> ExperimentRun:
    _project(project_id, db)
    run = db.scalar(select(ExperimentRun).where(ExperimentRun.id == run_id, ExperimentRun.project_id == project_id))
    if run is None:
        raise HTTPException(404, "Experiment run not found")
    return run


def _require(run: ExperimentRun, current: str) -> None:
    if run.status != current:
        raise HTTPException(409, f"Experiment run must be {current}; it is {run.status}")


def _audit(db: Session, project_id: int, event: str, run: ExperimentRun, payload: dict | None = None) -> None:
    record_audit_event(db, project_id=project_id, event_type=event, entity_type="experiment_run", entity_id=run.id, payload=payload)


@router.post("", response_model=ExperimentRunRead, status_code=status.HTTP_201_CREATED)
def create_run(project_id: int, data: ExperimentRunCreate, db: Annotated[Session, Depends(get_db)]):
    _project(project_id, db)
    if data.proposal_id is not None and db.scalar(select(ExperimentProposal).where(ExperimentProposal.id == data.proposal_id, ExperimentProposal.project_id == project_id)) is None:
        raise HTTPException(404, "Experiment proposal not found")
    run = ExperimentRun(project_id=project_id, **data.model_dump())
    db.add(run); db.flush()
    _audit(db, project_id, "experiment_run.proposed", run, {"forecast": run.forecast})
    db.commit(); db.refresh(run)
    return run


@router.get("", response_model=list[ExperimentRunRead])
def list_runs(project_id: int, db: Annotated[Session, Depends(get_db)]):
    _project(project_id, db)
    return list(db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project_id).order_by(ExperimentRun.id)))


@router.get("/{run_id:int}", response_model=ExperimentRunRead)
def get_run(project_id: int, run_id: int, db: Annotated[Session, Depends(get_db)]):
    return _run(project_id, run_id, db)


@router.patch("/{run_id:int}", response_model=ExperimentRunRead)
def update_run(project_id: int, run_id: int, data: ExperimentRunUpdate, db: Annotated[Session, Depends(get_db)]):
    run = _run(project_id, run_id, db); _require(run, "proposed")
    changes = data.model_dump(exclude_unset=True)
    for name, value in changes.items(): setattr(run, name, value)
    _audit(db, project_id, "experiment_run.updated", run, changes)
    db.commit(); db.refresh(run)
    return run


@router.delete("/{run_id:int}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(project_id: int, run_id: int, db: Annotated[Session, Depends(get_db)]):
    run = _run(project_id, run_id, db); _require(run, "proposed")
    _audit(db, project_id, "experiment_run.deleted", run)
    db.delete(run); db.commit()
    return Response(status_code=204)


@router.post("/{run_id:int}/approvals", response_model=ApprovalRead, status_code=status.HTTP_201_CREATED)
def approve(project_id: int, run_id: int, data: ApprovalCreate, db: Annotated[Session, Depends(get_db)]):
    run = _run(project_id, run_id, db); _require(run, "proposed")
    approval = ExperimentApproval(experiment_run_id=run.id, decision="approved", **data.model_dump())
    run.status, run.approved_at = "approved", datetime.now(timezone.utc)
    db.add(approval); db.flush()
    _audit(db, project_id, "experiment_run.approved", run, {"approval_id": approval.id, "actor": approval.actor})
    db.commit(); db.refresh(approval)
    return approval


@router.get("/{run_id:int}/approvals", response_model=list[ApprovalRead])
def list_approvals(project_id: int, run_id: int, db: Annotated[Session, Depends(get_db)]):
    run = _run(project_id, run_id, db)
    return list(db.scalars(select(ExperimentApproval).where(ExperimentApproval.experiment_run_id == run.id).order_by(ExperimentApproval.id)))


@router.post("/{run_id:int}/start", response_model=ExperimentRunRead)
def start(project_id: int, run_id: int, db: Annotated[Session, Depends(get_db)]):
    run = _run(project_id, run_id, db); _require(run, "approved")
    run.status, run.started_at = "running", datetime.now(timezone.utc)
    _audit(db, project_id, "experiment_run.started", run)
    db.commit(); db.refresh(run); return run


@router.post("/{run_id:int}/stop", response_model=ExperimentRunRead)
def stop(project_id: int, run_id: int, db: Annotated[Session, Depends(get_db)]):
    run = _run(project_id, run_id, db)
    if run.status not in {"proposed", "approved", "running"}:
        raise HTTPException(409, f"Experiment run cannot be stopped from {run.status}")
    run.status, run.stopped_at = "stopped", datetime.now(timezone.utc)
    _audit(db, project_id, "experiment_run.stopped", run)
    db.commit(); db.refresh(run); return run


@router.post("/{run_id:int}/measurements", response_model=MeasurementRead, status_code=status.HTTP_201_CREATED)
def create_measurement(project_id: int, run_id: int, data: MeasurementCreate, db: Annotated[Session, Depends(get_db)]):
    run = _run(project_id, run_id, db); _require(run, "running")
    measurement = ExperimentMeasurement(experiment_run_id=run.id, metric=data.metric, value=data.value, unit=data.unit, metadata_=data.metadata)
    db.add(measurement); db.flush()
    _audit(db, project_id, "experiment_measurement.created", run, {"measurement_id": measurement.id, "metric": measurement.metric, "value": measurement.value})
    db.commit(); db.refresh(measurement); return measurement


@router.get("/{run_id:int}/measurements", response_model=list[MeasurementRead])
def list_measurements(project_id: int, run_id: int, db: Annotated[Session, Depends(get_db)]):
    run = _run(project_id, run_id, db)
    return list(db.scalars(select(ExperimentMeasurement).where(ExperimentMeasurement.experiment_run_id == run.id).order_by(ExperimentMeasurement.id)))


def _measurement(project_id: int, run_id: int, measurement_id: int, db: Session) -> tuple[ExperimentRun, ExperimentMeasurement]:
    run = _run(project_id, run_id, db)
    item = db.scalar(select(ExperimentMeasurement).where(ExperimentMeasurement.id == measurement_id, ExperimentMeasurement.experiment_run_id == run.id))
    if item is None: raise HTTPException(404, "Measurement not found")
    return run, item


@router.patch("/{run_id:int}/measurements/{measurement_id:int}", response_model=MeasurementRead)
def update_measurement(project_id: int, run_id: int, measurement_id: int, data: MeasurementUpdate, db: Annotated[Session, Depends(get_db)]):
    run, item = _measurement(project_id, run_id, measurement_id, db); _require(run, "running")
    changes = data.model_dump(exclude_unset=True)
    if "metadata" in changes: changes["metadata_"] = changes.pop("metadata")
    for name, value in changes.items(): setattr(item, name, value)
    _audit(db, project_id, "experiment_measurement.updated", run, {"measurement_id": item.id, **changes})
    db.commit(); db.refresh(item); return item


@router.delete("/{run_id:int}/measurements/{measurement_id:int}", status_code=status.HTTP_204_NO_CONTENT)
def delete_measurement(project_id: int, run_id: int, measurement_id: int, db: Annotated[Session, Depends(get_db)]):
    run, item = _measurement(project_id, run_id, measurement_id, db); _require(run, "running")
    _audit(db, project_id, "experiment_measurement.deleted", run, {"measurement_id": item.id})
    db.delete(item); db.commit(); return Response(status_code=204)


@router.post("/{run_id:int}/evaluate", response_model=ActualVsForecastRead)
def evaluate_run(project_id: int, run_id: int, db: Annotated[Session, Depends(get_db)]):
    _project(project_id, db)
    # Row locks serialize evaluators on databases that support them. SQLite
    # ignores FOR UPDATE, so the unique constraint and recovery below provide
    # the same idempotent outcome there.
    statement = select(ExperimentRun).where(
        ExperimentRun.id == run_id, ExperimentRun.project_id == project_id
    )
    if db.get_bind().dialect.name != "sqlite":
        statement = statement.with_for_update()
    run = db.scalar(statement)
    if run is None:
        raise HTTPException(404, "Experiment run not found")
    existing = db.scalar(select(ActualVsForecast).where(ActualVsForecast.experiment_run_id == run.id))
    if existing is not None:
        return existing
    _require(run, "running")
    result = evaluate(run.forecast, [(m.metric, m.value) for m in run.measurements])
    report = ActualVsForecast(experiment_run_id=run.id, result=result)
    run.status, run.evaluation, run.completed_at = "completed", result, datetime.now(timezone.utc)
    db.add(report)
    try:
        db.flush()
    except IntegrityError:
        # A SQLite evaluator can race between the initial read and insert.
        # Reset this failed transaction and return the winner's durable report
        # rather than surfacing a uniqueness error to an idempotent caller.
        db.rollback()
        existing = db.scalar(select(ActualVsForecast).where(ActualVsForecast.experiment_run_id == run_id))
        if existing is not None:
            return existing
        raise
    # Experiment outcomes immediately refresh the immutable decision report.
    save_project_report_snapshot(db, db.get(Project, project_id))
    _audit(db, project_id, "experiment_run.completed", run, {"actual_vs_forecast_id": report.id, "outcome": result["outcome"]})
    db.commit(); db.refresh(report); return report


@router.get("/{run_id:int}/actual-vs-forecast", response_model=ActualVsForecastRead)
def actual_vs_forecast(project_id: int, run_id: int, db: Annotated[Session, Depends(get_db)]):
    run = _run(project_id, run_id, db)
    report = db.scalar(select(ActualVsForecast).where(ActualVsForecast.experiment_run_id == run.id))
    if report is None: raise HTTPException(404, "Actual-vs-forecast report not found")
    return report
