"""Deterministic, decision-ready experiment templates."""
from __future__ import annotations

from typing import Any


def _rules(metric: str, unit: str, minimum: int, passed: str, partial: str, failed: str, stop: str) -> dict[str, Any]:
    return {"target": {"metric": metric, "unit": unit}, "sample": {"minimum": minimum, "unit": unit}, "pass_rule": {"operator": ">=", "threshold": passed}, "partial_rule": {"range": partial}, "fail_rule": {"range": failed}, "stop_rule": stop}


def _template(key: str, name: str, category: str, description: str, metric: str, unit: str, minimum: int, passed: str, partial: str, failed: str, stop: str) -> dict[str, Any]:
    return {"template_key": key, "name": name, "category": category, "description": description, "rules": _rules(metric, unit, minimum, passed, partial, failed, stop), "version": 1}


# Kept in source so an empty local/test database has the same catalog as production.
# Each template has an explicit sample, pass/partial/fail boundary, and stop rule.
TEMPLATES: tuple[dict[str, Any], ...] = (
    _template("problem_interviews_v1", "Problem interviews", "problem", "Validate that a painful recurring problem exists.", "participants reporting recurring pain", "interviews", 10, "7 of 10", "4-6 of 10", "0-3 of 10", "Stop after 10 interviews or 3 consecutive no-pain interviews."),
    _template("problem_survey_v1", "Problem survey", "problem", "Quantify problem prevalence in a defined segment.", "respondents reporting the problem", "qualified responses", 100, "60%", "30%-59.99%", "<30%", "Stop at 100 qualified responses or when 95% confidence excludes the partial band."),
    _template("landing_page_v1", "Landing page demand test", "demand", "Measure qualified intent from a concise value proposition.", "qualified conversion rate", "unique visitors", 200, "10%", "5%-9.99%", "<5%", "Stop at 300 visitors or after 200 when a boundary is conclusive."),
    _template("smoke_test_v1", "Smoke test", "demand", "Test acquisition-channel demand before building the product.", "qualified lead rate", "ad clicks", 150, "12%", "6%-11.99%", "<6%", "Stop at 250 clicks or when 20 qualified leads are collected."),
    _template("fake_door_v1", "Fake-door feature test", "solution", "Measure demand for a not-yet-built feature entry point.", "feature-click rate", "eligible users", 200, "8%", "4%-7.99%", "<4%", "Stop at 300 users or after 200 when a boundary is conclusive."),
    _template("prototype_usability_v1", "Prototype usability test", "solution", "Check whether target users can complete the core workflow.", "participants completing the core task", "usability sessions", 8, "6 of 8", "4-5 of 8", "0-3 of 8", "Stop after 8 sessions or 3 consecutive task failures."),
    _template("concierge_v1", "Concierge pilot", "solution", "Deliver the proposed outcome manually before automating it.", "participants completing the workflow", "pilot customers", 10, "5 of 10", "3-4 of 10", "0-2 of 10", "Stop after 10 pilots or 3 consecutive failed completions."),
    _template("wizard_of_oz_v1", "Wizard-of-Oz test", "solution", "Simulate the product behind the scenes to validate the promised outcome.", "customers receiving the promised outcome", "pilot customers", 10, "6 of 10", "3-5 of 10", "0-2 of 10", "Stop after 10 pilots or when delivery cannot meet the promise 3 times."),
    _template("mvp_pilot_v1", "MVP pilot", "retention", "Validate repeated use of a minimum viable product.", "customers active in week four", "activated pilot customers", 20, "50%", "25%-49.99%", "<25%", "Stop after 20 activations or when 10 customers churn before week four."),
    _template("preorder_v1", "Pre-order test", "willingness_to_pay", "Validate payment intent with a refundable or real pre-order.", "paid or refundable commitments", "qualified prospects", 100, "10 commitments", "5-9 commitments", "0-4 commitments", "Stop at 100 prospects or after 10 commitments."),
    _template("pricing_interviews_v1", "Pricing interview", "pricing", "Test whether buyers accept a stated price and purchase process.", "buyers accepting target price", "qualified buyer interviews", 20, "8 of 20", "4-7 of 20", "0-3 of 20", "Stop after 20 interviews or 5 explicit price rejections."),
    _template("paid_pilot_v1", "Paid pilot", "willingness_to_pay", "Validate a paid delivery and renewal path with real buyers.", "customers paying for a pilot", "qualified opportunities", 20, "4 of 20", "2-3 of 20", "0-1 of 20", "Stop after 20 opportunities or 4 paid pilots."),
)

TEMPLATES_BY_KEY = {template["template_key"]: template for template in TEMPLATES}
CATEGORY_TEMPLATE_KEYS = {"problem": "problem_interviews_v1", "customer": "problem_interviews_v1", "demand": "landing_page_v1", "channel": "smoke_test_v1", "solution": "fake_door_v1", "retention": "mvp_pilot_v1", "willingness_to_pay": "preorder_v1", "pricing": "pricing_interviews_v1"}


def template_for_category(category: str) -> dict[str, Any]:
    return TEMPLATES_BY_KEY[CATEGORY_TEMPLATE_KEYS.get(category, "landing_page_v1")]
