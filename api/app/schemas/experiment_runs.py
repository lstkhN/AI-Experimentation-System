from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExperimentRunCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    proposal_id: int | None = Field(default=None, gt=0)
    forecast: dict[str, Any] = Field(default_factory=dict)


class ExperimentRunUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    forecast: dict[str, Any] | None = None


class ExperimentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    proposal_id: int | None
    title: str
    forecast: dict[str, Any]
    status: str
    evaluation: dict[str, Any] | None
    created_at: datetime
    approved_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    stopped_at: datetime | None


class ApprovalCreate(BaseModel):
    actor: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    experiment_run_id: int
    decision: str
    actor: str | None
    note: str | None
    created_at: datetime


class MeasurementCreate(BaseModel):
    metric: str = Field(min_length=1, max_length=100)
    value: float
    unit: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None


class MeasurementUpdate(BaseModel):
    metric: str | None = Field(default=None, min_length=1, max_length=100)
    value: float | None = None
    unit: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None


class MeasurementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    experiment_run_id: int
    metric: str
    value: float
    unit: str | None
    metadata_: dict[str, Any] | None = Field(serialization_alias="metadata")
    observed_at: datetime
    created_at: datetime


class ActualVsForecastRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    experiment_run_id: int
    result: dict[str, Any]
    created_at: datetime
    updated_at: datetime
