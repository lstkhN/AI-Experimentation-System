"""Project-scoped CRUD for manually supplied strategic context."""
from typing import Annotated, Type
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Competitor, ICPSegment, MarketEntity, MonetizationAssumption, Project, RiskMapEntry
from app.db.session import get_db
from app.schemas.strategy import (CompetitorCreate, CompetitorRead, ICPSegmentCreate, ICPSegmentRead,
    MarketEntityCreate, MarketEntityRead, MonetizationAssumptionCreate, MonetizationAssumptionRead,
    RiskMapEntryCreate, RiskMapEntryRead)
from app.services.audit import record_audit_event

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["strategy"])


def _project(project_id: int, db: Session) -> None:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")


def _get(model: Type, project_id: int, entity_id: int, db: Session):
    item = db.get(model, entity_id)
    if item is None or item.project_id != project_id:
        raise HTTPException(status_code=404, detail="Record not found")
    return item


def _create(model: Type, entity_type: str, project_id: int, data, db: Session):
    _project(project_id, db)
    item = model(project_id=project_id, **data.model_dump())
    db.add(item); db.flush()
    record_audit_event(db, project_id=project_id, event_type=f"{entity_type}.created", entity_type=entity_type, entity_id=item.id,
                       payload={"provenance": "manual", "source_reference": item.source_reference})
    db.commit(); db.refresh(item)
    return item


def _replace(model: Type, entity_type: str, project_id: int, entity_id: int, data, db: Session):
    item = _get(model, project_id, entity_id, db)
    for key, value in data.model_dump().items(): setattr(item, key, value)
    record_audit_event(db, project_id=project_id, event_type=f"{entity_type}.updated", entity_type=entity_type, entity_id=item.id,
                       payload={"provenance": "manual", "source_reference": item.source_reference})
    db.commit(); db.refresh(item)
    return item


def _delete(model: Type, entity_type: str, project_id: int, entity_id: int, db: Session):
    item = _get(model, project_id, entity_id, db)
    record_audit_event(db, project_id=project_id, event_type=f"{entity_type}.deleted", entity_type=entity_type, entity_id=item.id, payload={"provenance": "manual"})
    db.delete(item); db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# Explicit routes preserve discoverable resource names while sharing only mechanical CRUD.
@router.get("/market-entities", response_model=list[MarketEntityRead])
def list_market_entities(project_id: int, db: Annotated[Session, Depends(get_db)]): _project(project_id, db); return list(db.scalars(select(MarketEntity).where(MarketEntity.project_id == project_id).order_by(MarketEntity.id)))
@router.post("/market-entities", response_model=MarketEntityRead, status_code=201)
def create_market_entity(project_id: int, data: MarketEntityCreate, db: Annotated[Session, Depends(get_db)]): return _create(MarketEntity, "market_entity", project_id, data, db)
@router.put("/market-entities/{entity_id}", response_model=MarketEntityRead)
def update_market_entity(project_id: int, entity_id: int, data: MarketEntityCreate, db: Annotated[Session, Depends(get_db)]): return _replace(MarketEntity, "market_entity", project_id, entity_id, data, db)
@router.delete("/market-entities/{entity_id}", status_code=204)
def delete_market_entity(project_id: int, entity_id: int, db: Annotated[Session, Depends(get_db)]): return _delete(MarketEntity, "market_entity", project_id, entity_id, db)

def _routes(prefix, model, create_schema, read_schema, entity_type):
    # FastAPI route registration must happen at module load; this helper avoids repeated CRUD semantics.
    router.add_api_route(f"/{prefix}", lambda project_id, db: (_project(project_id, db), list(db.scalars(select(model).where(model.project_id == project_id).order_by(model.id))))[1], methods=["GET"], response_model=list[read_schema], name=f"list_{prefix}")
    router.add_api_route(f"/{prefix}", lambda project_id, data, db: _create(model, entity_type, project_id, data, db), methods=["POST"], response_model=read_schema, status_code=201, name=f"create_{prefix}")
    router.add_api_route(f"/{prefix}/{{entity_id}}", lambda project_id, entity_id, data, db: _replace(model, entity_type, project_id, entity_id, data, db), methods=["PUT"], response_model=read_schema, name=f"update_{prefix}")
    router.add_api_route(f"/{prefix}/{{entity_id}}", lambda project_id, entity_id, db: _delete(model, entity_type, project_id, entity_id, db), methods=["DELETE"], status_code=204, name=f"delete_{prefix}")

# Explicit typed routes keep FastAPI request validation and OpenAPI bodies accurate.
@router.get("/competitors", response_model=list[CompetitorRead])
def list_competitors(project_id: int, db: Annotated[Session, Depends(get_db)]): _project(project_id, db); return list(db.scalars(select(Competitor).where(Competitor.project_id == project_id).order_by(Competitor.id)))
@router.post("/competitors", response_model=CompetitorRead, status_code=201)
def create_competitor(project_id: int, data: CompetitorCreate, db: Annotated[Session, Depends(get_db)]): return _create(Competitor, "competitor", project_id, data, db)
@router.put("/competitors/{entity_id}", response_model=CompetitorRead)
def update_competitor(project_id: int, entity_id: int, data: CompetitorCreate, db: Annotated[Session, Depends(get_db)]): return _replace(Competitor, "competitor", project_id, entity_id, data, db)
@router.delete("/competitors/{entity_id}", status_code=204)
def delete_competitor(project_id: int, entity_id: int, db: Annotated[Session, Depends(get_db)]): return _delete(Competitor, "competitor", project_id, entity_id, db)

@router.get("/icp-segments", response_model=list[ICPSegmentRead])
def list_icp(project_id: int, db: Annotated[Session, Depends(get_db)]): _project(project_id, db); return list(db.scalars(select(ICPSegment).where(ICPSegment.project_id == project_id).order_by(ICPSegment.id)))
@router.post("/icp-segments", response_model=ICPSegmentRead, status_code=201)
def create_icp(project_id: int, data: ICPSegmentCreate, db: Annotated[Session, Depends(get_db)]): return _create(ICPSegment, "icp_segment", project_id, data, db)
@router.put("/icp-segments/{entity_id}", response_model=ICPSegmentRead)
def update_icp(project_id: int, entity_id: int, data: ICPSegmentCreate, db: Annotated[Session, Depends(get_db)]): return _replace(ICPSegment, "icp_segment", project_id, entity_id, data, db)
@router.delete("/icp-segments/{entity_id}", status_code=204)
def delete_icp(project_id: int, entity_id: int, db: Annotated[Session, Depends(get_db)]): return _delete(ICPSegment, "icp_segment", project_id, entity_id, db)

@router.get("/monetization-assumptions", response_model=list[MonetizationAssumptionRead])
def list_monetization(project_id: int, db: Annotated[Session, Depends(get_db)]): _project(project_id, db); return list(db.scalars(select(MonetizationAssumption).where(MonetizationAssumption.project_id == project_id).order_by(MonetizationAssumption.id)))
@router.post("/monetization-assumptions", response_model=MonetizationAssumptionRead, status_code=201)
def create_monetization(project_id: int, data: MonetizationAssumptionCreate, db: Annotated[Session, Depends(get_db)]): return _create(MonetizationAssumption, "monetization_assumption", project_id, data, db)
@router.put("/monetization-assumptions/{entity_id}", response_model=MonetizationAssumptionRead)
def update_monetization(project_id: int, entity_id: int, data: MonetizationAssumptionCreate, db: Annotated[Session, Depends(get_db)]): return _replace(MonetizationAssumption, "monetization_assumption", project_id, entity_id, data, db)
@router.delete("/monetization-assumptions/{entity_id}", status_code=204)
def delete_monetization(project_id: int, entity_id: int, db: Annotated[Session, Depends(get_db)]): return _delete(MonetizationAssumption, "monetization_assumption", project_id, entity_id, db)

@router.get("/risk-map", response_model=list[RiskMapEntryRead])
def list_risks(project_id: int, db: Annotated[Session, Depends(get_db)]): _project(project_id, db); return list(db.scalars(select(RiskMapEntry).where(RiskMapEntry.project_id == project_id).order_by(RiskMapEntry.id)))
@router.post("/risk-map", response_model=RiskMapEntryRead, status_code=201)
def create_risk(project_id: int, data: RiskMapEntryCreate, db: Annotated[Session, Depends(get_db)]): return _create(RiskMapEntry, "risk_map_entry", project_id, data, db)
@router.put("/risk-map/{entity_id}", response_model=RiskMapEntryRead)
def update_risk(project_id: int, entity_id: int, data: RiskMapEntryCreate, db: Annotated[Session, Depends(get_db)]): return _replace(RiskMapEntry, "risk_map_entry", project_id, entity_id, data, db)
@router.delete("/risk-map/{entity_id}", status_code=204)
def delete_risk(project_id: int, entity_id: int, db: Annotated[Session, Depends(get_db)]): return _delete(RiskMapEntry, "risk_map_entry", project_id, entity_id, db)
