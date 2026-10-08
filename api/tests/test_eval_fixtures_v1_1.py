"""Regression eval fixtures for deterministic v1.1 policy behavior.

These cases deliberately invoke only local engines and services.  They make no
network or provider calls, and all source data is checked into the fixture file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Evidence as ORMEvidence, EvidenceSource, Hypothesis, Project
from app.engines.economics import calculate_economics
from app.engines.evidence import Evidence
from app.engines.verdict import evaluate_verdict
from app.services.evidence_normalization import normalize_research_results
from app.services.research import ResearchResult


@pytest.fixture(scope="module")
def eval_cases() -> dict:
    fixture_path = Path(__file__).parent / "fixtures" / "eval_v1_1.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert payload["version"] == "v1.1"
    return payload["cases"]


def test_eval_v1_1_no_evidence_passes_only_as_unproven(eval_cases: dict):
    """Pass condition: no evidence cannot become a positive or negative verdict."""
    case = eval_cases["no-evidence"]

    result = evaluate_verdict([Evidence(**item) for item in case["evidence"]])

    expected = case["expected"]
    assert result["verdict"] == expected["verdict"]
    assert result["rule"] == expected["rule"]
    assert result["support_score"] == expected["support_score"]
    assert result["coverage"] == expected["coverage"]
    assert set(expected["required_unknowns"]).issubset(result["unknowns"])


def test_eval_v1_1_material_contradiction_passes_as_no_go(eval_cases: dict):
    """Pass condition: a material, usable contradiction takes precedence."""
    case = eval_cases["contradiction"]

    result = evaluate_verdict([Evidence(**item) for item in case["evidence"]])

    expected = case["expected"]
    assert result["verdict"] == expected["verdict"]
    assert result["rule"] == expected["rule"]
    assert result["decisive_facts"][0]["direction"] == expected["decisive_direction"]


def test_eval_v1_1_expensive_build_keeps_capital_and_ltv_assumptions_separate(eval_cases: dict):
    """Pass condition: staged build cost is totalled but cannot invent retention/LTV."""
    case = eval_cases["expensive-build-trap"]

    result = calculate_economics(case["scenarios"], capital_steps=case["capital_steps"])

    expected = case["expected"]
    scenario = result["scenarios"][0]
    assert result["capital_plan"]["total_required"] == expected["total_required"]
    assert [step["name"] for step in result["capital_plan"]["steps"]] == [
        "prototype", "regulated integration", "launch"
    ]
    assert set(expected["required_unknowns"]).issubset(result["unknowns"])
    assert scenario["metrics"]["ltv_simple"] is expected["ltv_simple"]
    assert scenario["sensitivity"]["status"] == expected["sensitivity_status"]


def test_eval_v1_1_bad_tam_without_churn_cannot_produce_ltv(eval_cases: dict):
    """Pass condition: an unsupported TAM claim does not hide missing churn."""
    case = eval_cases["bad-tam-unknown-churn"]

    result = calculate_economics(case["scenarios"])

    expected = case["expected"]
    scenario = result["scenarios"][0]
    assert set(expected["required_unknowns"]).issubset(result["unknowns"])
    assert scenario["metrics"]["ltv_simple"] is expected["ltv_simple"]
    assert scenario["sensitivity"]["status"] == expected["sensitivity_status"]


def test_eval_v1_1_duplicate_sources_preserve_provenance_without_double_counting(eval_cases: dict):
    """Pass condition: duplicate URLs/pages yield one evidence item per publisher."""
    case = eval_cases["duplicate-sources"]
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        project = Project(name="v1.1 duplicate-source eval")
        hypothesis = Hypothesis(project=project, statement="Demand exists")
        session.add(hypothesis)
        session.commit()
        results = [ResearchResult(**item) for item in case["results"]]

        summary = normalize_research_results(session, project=project, hypothesis=hypothesis, results=results)
        session.commit()

        expected = case["expected"]
        assert summary.sources_created == expected["sources_created"]
        assert summary.evidence_created == expected["evidence_created"]
        assert summary.results_skipped == expected["results_skipped"]
        report = session.scalar(select(EvidenceSource).where(EvidenceSource.url.endswith("/report")))
        assert report is not None
        assert len(report.source_metadata["research_results"]) == expected["provenance_count"]
        evidence = session.scalar(select(ORMEvidence))
        assert evidence is not None
        assert evidence.source_cluster == expected["source_cluster"]

        repeated = normalize_research_results(session, project=project, hypothesis=hypothesis, results=results)
        session.commit()
        assert repeated.sources_created == 0
        assert repeated.evidence_created == 0
        assert repeated.evidence_reused == 1
        assert len(list(session.scalars(select(ORMEvidence)))) == 1
    finally:
        session.close()
        Base.metadata.drop_all(engine)
