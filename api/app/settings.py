"""Typed runtime limits for analysis provider calls."""
from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field


class AnalysisSettings(BaseModel):
    """Limits are deliberately read once per run, making a run auditable."""

    cost_cap_usd: Decimal = Field(default=Decimal("2"), ge=0)
    max_research_calls: int = Field(default=1, ge=0)
    max_tool_calls: int = Field(default=2, ge=0)
    # USD per million tokens. Defaults are the public gpt-4o-mini prices.
    openai_input_cost_per_million_usd: Decimal = Field(default=Decimal("0.15"), ge=0)
    openai_output_cost_per_million_usd: Decimal = Field(default=Decimal("0.60"), ge=0)

    @classmethod
    def from_env(cls) -> "AnalysisSettings":
        def value(name: str, default: str) -> str:
            return os.getenv(name, default)

        try:
            return cls(
                cost_cap_usd=Decimal(value("ANALYSIS_COST_CAP_USD", "2")),
                max_research_calls=int(value("ANALYSIS_MAX_RESEARCH_CALLS", "1")),
                max_tool_calls=int(value("ANALYSIS_MAX_TOOL_CALLS", "2")),
                openai_input_cost_per_million_usd=Decimal(value("OPENAI_INPUT_COST_PER_MILLION_USD", "0.15")),
                openai_output_cost_per_million_usd=Decimal(value("OPENAI_OUTPUT_COST_PER_MILLION_USD", "0.60")),
            )
        except (ValueError, InvalidOperation) as exc:
            raise ValueError("Invalid analysis reliability settings") from exc
