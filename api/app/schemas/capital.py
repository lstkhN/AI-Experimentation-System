"""Capital intelligence API contracts."""
from pydantic import BaseModel, Field, model_validator


class UnlockCondition(BaseModel):
    """A deterministic metric threshold; all supplied conditions must pass."""
    metric: str = Field(min_length=1, max_length=100)
    operator: str = Field(default=">=", pattern=r"^(>=|>|<=|<|==)$")
    value: float


class CapitalGateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    recommended_spend: float = Field(ge=0)
    unlock_conditions: list[UnlockCondition] = Field(default_factory=list, max_length=50)


class CapitalPlanCreate(BaseModel):
    available_budget: float = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    gates: list[CapitalGateCreate] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_gate_names(self):
        if len({gate.name for gate in self.gates}) != len(self.gates):
            raise ValueError("gate names must be unique")
        return self


class GateEvaluationRequest(BaseModel):
    metrics: dict[str, float] = Field(default_factory=dict)


class AllocationRequest(BaseModel):
    available_budget: float | None = Field(default=None, ge=0)
