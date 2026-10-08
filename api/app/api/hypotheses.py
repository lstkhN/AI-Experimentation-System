from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Hypothesis, Project
from app.db.session import get_db
from app.schemas.hypotheses import HypothesisCreate, HypothesisRead

router = APIRouter(prefix="/api/v1/projects/{project_id}/hypotheses", tags=["hypotheses"])

def project_or_404(project_id: int, db: Session) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@router.post("", response_model=HypothesisRead, status_code=status.HTTP_201_CREATED)
def create_hypothesis(project_id: int, data: HypothesisCreate, db: Annotated[Session, Depends(get_db)]):
    project_or_404(project_id, db)
    hypothesis = Hypothesis(
        project_id=project_id,
        statement=data.statement,
        category=data.category,
        importance=data.importance,
        criticality=data.criticality.value,
        is_blocking=data.is_blocking,
    )
    db.add(hypothesis)
    db.commit()
    db.refresh(hypothesis)
    return hypothesis

@router.get("", response_model=list[HypothesisRead])
def list_hypotheses(project_id: int, db: Annotated[Session, Depends(get_db)]):
    project_or_404(project_id, db)
    return list(db.scalars(select(Hypothesis).where(Hypothesis.project_id == project_id).order_by(Hypothesis.id)))
