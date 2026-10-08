"""Project-scoped experiment proposal and deterministic next-test APIs."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExperimentProposal, Hypothesis, Project
from app.db.session import get_db
from app.schemas.experiments import (
    ExperimentProposalCreate,
    ExperimentProposalRead,
    ExperimentProposalUpdate,
    ExperimentTemplateRead,
    NextTestRecommendation,
)
from app.services.audit import record_audit_event
from app.services.experiment_templates import TEMPLATES, TEMPLATES_BY_KEY, template_for_category

router = APIRouter(prefix="/api/v1/projects/{project_id}/experiments", tags=["experiments"])


def _project_or_404(project_id: int, db: Session) -> None:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/templates", response_model=list[ExperimentTemplateRead])
def list_templates(project_id: int, db: Annotated[Session, Depends(get_db)]):
    _project_or_404(project_id, db)
    return list(TEMPLATES)


@router.post("/propose", response_model=ExperimentProposalRead, status_code=status.HTTP_201_CREATED)
def propose_experiment(
    project_id: int, data: ExperimentProposalCreate, db: Annotated[Session, Depends(get_db)]
) -> ExperimentProposal:
    _project_or_404(project_id, db)
    template = TEMPLATES_BY_KEY.get(data.template_key)
    if template is None:
        raise HTTPException(status_code=422, detail="Unknown experiment template")
    hypothesis = None
    if data.hypothesis_id is not None:
        hypothesis = db.scalar(select(Hypothesis).where(
            Hypothesis.id == data.hypothesis_id, Hypothesis.project_id == project_id
        ))
        if hypothesis is None:
            # Never disclose whether another project's hypothesis exists.
            raise HTTPException(status_code=404, detail="Hypothesis not found")
    proposal = ExperimentProposal(
        project_id=project_id,
        hypothesis_id=data.hypothesis_id,
        template_key=template["template_key"],
        title=data.title or template["name"],
        rationale=data.rationale,
        rules=template["rules"],
    )
    db.add(proposal)
    db.flush()
    record_audit_event(
        db, project_id=project_id, event_type="experiment.proposed",
        entity_type="experiment_proposal", entity_id=proposal.id,
        payload={"template_key": proposal.template_key, "hypothesis_id": proposal.hypothesis_id},
    )
    db.commit()
    db.refresh(proposal)
    return proposal


@router.get("", response_model=list[ExperimentProposalRead])
def list_proposals(project_id: int, db: Annotated[Session, Depends(get_db)]):
    _project_or_404(project_id, db)
    return list(db.scalars(select(ExperimentProposal).where(
        ExperimentProposal.project_id == project_id
    ).order_by(ExperimentProposal.id)))


@router.get("/{proposal_id:int}", response_model=ExperimentProposalRead)
def get_proposal(project_id: int, proposal_id: int, db: Annotated[Session, Depends(get_db)]):
    _project_or_404(project_id, db)
    proposal = db.scalar(select(ExperimentProposal).where(
        ExperimentProposal.id == proposal_id, ExperimentProposal.project_id == project_id
    ))
    if proposal is None:
        raise HTTPException(status_code=404, detail="Experiment proposal not found")
    return proposal


@router.patch("/{proposal_id:int}", response_model=ExperimentProposalRead)
def update_proposal(
    project_id: int, proposal_id: int, data: ExperimentProposalUpdate, db: Annotated[Session, Depends(get_db)]
):
    _project_or_404(project_id, db)
    proposal = db.scalar(select(ExperimentProposal).where(
        ExperimentProposal.id == proposal_id, ExperimentProposal.project_id == project_id
    ))
    if proposal is None:
        raise HTTPException(status_code=404, detail="Experiment proposal not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(proposal, field, value)
    record_audit_event(db, project_id=project_id, event_type="experiment.proposal.updated",
                       entity_type="experiment_proposal", entity_id=proposal.id,
                       payload=data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(proposal)
    return proposal


@router.delete("/{proposal_id:int}", status_code=status.HTTP_204_NO_CONTENT)
def delete_proposal(project_id: int, proposal_id: int, db: Annotated[Session, Depends(get_db)]) -> Response:
    _project_or_404(project_id, db)
    proposal = db.scalar(select(ExperimentProposal).where(
        ExperimentProposal.id == proposal_id, ExperimentProposal.project_id == project_id
    ))
    if proposal is None:
        raise HTTPException(status_code=404, detail="Experiment proposal not found")
    record_audit_event(db, project_id=project_id, event_type="experiment.proposal.deleted",
                       entity_type="experiment_proposal", entity_id=proposal.id,
                       payload={"template_key": proposal.template_key})
    db.delete(proposal)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/recommend-next-test", response_model=NextTestRecommendation)
def recommend_next_test(project_id: int, db: Annotated[Session, Depends(get_db)]):
    """Choose the highest-priority unproposed hypothesis with stable tie-breaks."""
    _project_or_404(project_id, db)
    proposed_hypothesis_ids = select(ExperimentProposal.hypothesis_id).where(
        ExperimentProposal.project_id == project_id,
        ExperimentProposal.hypothesis_id.is_not(None),
    )
    hypothesis = db.scalar(select(Hypothesis).where(
        Hypothesis.project_id == project_id,
        Hypothesis.id.not_in(proposed_hypothesis_ids),
    ).order_by(Hypothesis.importance.desc(), Hypothesis.id.asc()))
    if hypothesis is None:
        template = template_for_category("demand")
        return {"hypothesis_id": None, "template": template,
                "rationale": "No unproposed project hypothesis remains; validate baseline demand."}
    template = template_for_category(hypothesis.category)
    return {"hypothesis_id": hypothesis.id, "template": template,
            "rationale": f"Selected highest-importance unproposed hypothesis ({hypothesis.importance:g})."}
