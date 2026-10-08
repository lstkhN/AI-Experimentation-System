from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class HypothesisCriticality(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    FATAL = "FATAL"

class HypothesisCreate(BaseModel):
    statement: str = Field(min_length=10)
    category: str = Field(default="problem", min_length=1, max_length=50)
    importance: float = Field(default=0.5, ge=0, le=1)
    criticality: HypothesisCriticality = HypothesisCriticality.NORMAL
    is_blocking: bool = False

class HypothesisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    analysis_run_id: int | None
    statement: str
    category: str
    importance: float
    criticality: HypothesisCriticality
    is_blocking: bool
    status: str
    created_at: datetime
