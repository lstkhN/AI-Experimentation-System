from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExperimentTemplateRead(BaseModel):
    template_key: str
    name: str
    category: str
    description: str
    rules: dict[str, Any]
    version: int


class ExperimentProposalCreate(BaseModel):
    template_key: str = Field(min_length=1, max_length=100)
    hypothesis_id: int | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    rationale: str | None = Field(default=None, max_length=2000)


class ExperimentProposalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    rationale: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern="^(proposed|accepted|rejected|completed)$")


class ExperimentProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    hypothesis_id: int | None
    template_key: str
    title: str
    rationale: str | None
    rules: dict[str, Any]
    status: str
    created_at: datetime


class NextTestRecommendation(BaseModel):
    hypothesis_id: int | None
    template: ExperimentTemplateRead
    rationale: str
