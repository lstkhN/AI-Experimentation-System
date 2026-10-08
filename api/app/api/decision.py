"""Action-oriented project decision resource."""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Project, ProjectVerdict
from app.db.session import get_db
from app.api.project_verdicts import _serialize

router = APIRouter(prefix="/api/v1/projects/{project_id}/decision", tags=["decision"])

@router.get("")
def get_decision(project_id: int, db: Annotated[Session, Depends(get_db)]):
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")
    snapshot = db.scalar(select(ProjectVerdict).where(ProjectVerdict.project_id == project_id).order_by(ProjectVerdict.created_at.desc(), ProjectVerdict.id.desc()).limit(1))
    if snapshot is None:
        raise HTTPException(404, "Project decision not found")
    return _serialize(snapshot, db)
