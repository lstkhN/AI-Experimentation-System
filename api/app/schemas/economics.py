"""Request schemas for project economics and capital planning."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ParameterProvenance(BaseModel):
    source_type: Literal["user_input", "verified_evidence", "benchmark", "inference"] = "user_input"
    source_id: str | None = None
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    observed: bool = False
    benchmark: bool = False
    inferred: bool = False


class UnitEconomicsScenario(BaseModel):
    """A named set of assumptions; monetary values use the request currency."""

    name: str = Field(default="base", min_length=1, max_length=100)
    price: float = Field(gt=0)
    variable_cost: float = Field(ge=0)
    monthly_churn: float | None = Field(default=None, gt=0, lt=1)
    cac: float | None = Field(default=None, ge=0)
    fixed_monthly_cost: float = Field(default=0, ge=0)
    target_ltv_cac_ratio: float = Field(default=3, gt=0)
    # Optional per-assumption source/reference, retained in immutable snapshots.
    parameter_provenance: dict[str, ParameterProvenance] = Field(default_factory=dict)


class ChurnSensitivity(BaseModel):
    """Explicit churn assumptions used for a deterministic sensitivity table."""

    monthly_churn_rates: list[float] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_rates(self) -> "ChurnSensitivity":
        if any(not 0 < rate < 1 for rate in self.monthly_churn_rates):
            raise ValueError("monthly_churn_rates must contain values between 0 and 1")
        if len(set(self.monthly_churn_rates)) != len(self.monthly_churn_rates):
            raise ValueError("monthly_churn_rates must not contain duplicates")
        return self


class CapitalStep(BaseModel):
    """One planned funding tranche or spend gate."""

    name: str = Field(min_length=1, max_length=100)
    amount: float = Field(ge=0)
    month: int | None = Field(default=None, ge=0)
    trigger: str | None = Field(default=None, max_length=500)
    purpose: str | None = Field(default=None, max_length=500)
    expected_learning: str | None = Field(default=None, max_length=500)
    unlock_condition: str | None = Field(default=None, max_length=500)


class EconomicsCalculateRequest(BaseModel):
    scenarios: list[UnitEconomicsScenario] = Field(min_length=1, max_length=50)
    sensitivity: ChurnSensitivity | None = None
    capital_steps: list[CapitalStep] = Field(default_factory=list, max_length=100)
    currency: str = Field(default="USD", min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_scenario_names(self) -> "EconomicsCalculateRequest":
        names = [scenario.name for scenario in self.scenarios]
        if len(set(names)) != len(names):
            raise ValueError("scenario names must be unique")
        return self


class Distribution(BaseModel):
    """A fully specified numeric distribution for the deterministic simulator."""

    kind: Literal["fixed", "uniform", "triangular", "normal"] = "fixed"
    value: float | None = None
    low: float | None = None
    high: float | None = None
    mode: float | None = None
    mean: float | None = None
    stddev: float | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_common_kind_aliases(cls, value):
        if isinstance(value, dict):
            value = value.copy()
            if "kind" not in value:
                value["kind"] = value.get("distribution", value.get("type", "fixed"))
        return value

    @model_validator(mode="after")
    def validate_parameters(self) -> "Distribution":
        if self.kind == "fixed" and self.value is None:
            raise ValueError("fixed distribution requires value")
        if self.kind == "uniform" and (self.low is None or self.high is None or self.low > self.high):
            raise ValueError("uniform distribution requires low <= high")
        if self.kind == "triangular" and (self.low is None or self.mode is None or self.high is None or not self.low <= self.mode <= self.high):
            raise ValueError("triangular distribution requires low <= mode <= high")
        if self.kind == "normal" and (self.mean is None or self.stddev is None or self.stddev < 0):
            raise ValueError("normal distribution requires mean and non-negative stddev")
        return self


class SimulationScenario(BaseModel):
    """One explicit set of distributions; all money values use request currency."""

    name: str = Field(default="base", min_length=1, max_length=100)
    price: Distribution
    variable_cost: Distribution
    monthly_churn: Distribution
    cac: Distribution
    fixed_monthly_cost: Distribution = Field(default_factory=lambda: Distribution(value=0))
    parameter_provenance: dict[str, ParameterProvenance] = Field(default_factory=dict)


class EconomicsSimulationRequest(BaseModel):
    scenarios: list[SimulationScenario] = Field(min_length=1, max_length=50)
    iterations: int = Field(default=5000, ge=1, le=100_000)
    # A default seed makes omitted-seed requests reproducible too.
    seed: int = 0
    capital_steps: list[CapitalStep] = Field(default_factory=list, max_length=100)
    currency: str = Field(default="USD", min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_scenario_names(self) -> "EconomicsSimulationRequest":
        names = [scenario.name for scenario in self.scenarios]
        if len(set(names)) != len(names):
            raise ValueError("scenario names must be unique")
        return self


class CapitalPlanRequest(BaseModel):
    """Calculate and save a capital plan, optionally with economics assumptions."""

    capital_steps: list[CapitalStep] = Field(default_factory=list, max_length=100)
    scenarios: list[UnitEconomicsScenario] = Field(default_factory=list, max_length=50)
    sensitivity: ChurnSensitivity | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_scenario_names(self) -> "CapitalPlanRequest":
        names = [scenario.name for scenario in self.scenarios]
        if len(set(names)) != len(names):
            raise ValueError("scenario names must be unique")
        return self
