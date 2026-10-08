"""Deterministic disclosure of report sections that have no structured inputs."""
from __future__ import annotations

from typing import Literal

ReportSection = Literal["icp", "market", "competitor", "monetization", "risk_map"]
LanguageCode = Literal["en", "ru"]


class StructuredReportGapsService:
    """Produce disclosures, not inferred business facts.

    The current intake and evidence models do not capture these report areas in
    structured form.  Keeping this inventory static makes that limitation
    visible without treating free-form text, hypotheses, or economics inputs as
    validated facts about any of the areas.
    """

    _missing_fields: dict[ReportSection, tuple[str, ...]] = {
        "icp": ("target_customer_profile", "buyer_role_and_job_to_be_done", "segment_size_and_priority"),
        "market": ("market_definition", "market_size_and_growth", "geography_specific_demand"),
        "competitor": ("competitor_set", "alternative_solutions", "competitive_differentiation"),
        "monetization": ("pricing_and_packaging", "willingness_to_pay", "revenue_model_validation"),
        "risk_map": ("risk_register", "probability_and_impact", "mitigations_and_owners"),
    }

    def build(self, language: LanguageCode, manual_records: dict[ReportSection, list] | None = None) -> dict:
        """Overlay attributable manual records onto the standard gap inventory."""
        manual_records = manual_records or {}
        sections = {
            section: ({
                "status": "collected",
                "records": manual_records[section],
                "data_gaps": [],
            } if manual_records.get(section) else {
                "status": "unknown",
                "data_gaps": [
                    {
                        "section": section,
                        "field": field,
                        "status": "unknown",
                        "reason": "not_collected_as_structured_data",
                    }
                    for field in fields
                ],
            })
            for section, fields in self._missing_fields.items()
        }
        return {
            "language_metadata": {"code": language, "source": "project_intake"},
            **sections,
            "data_gaps": [gap for section in sections.values() for gap in section["data_gaps"]],
        }


def build_structured_report_gaps(language: LanguageCode, manual_records: dict[ReportSection, list] | None = None) -> dict:
    return StructuredReportGapsService().build(language, manual_records)
