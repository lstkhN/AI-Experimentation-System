from datetime import date, timedelta
from app.engines.evidence import Evidence, effective_weight, score_evidence

def test_no_evidence_has_neutral_direction_and_zero_coverage():
    result = score_evidence([])
    assert result["support_score"] == 50
    assert result["coverage"] == 0
    assert result["data_quality"] == "LOW"

def test_support_and_contradiction_are_separate():
    result = score_evidence([
        Evidence("E5", "supporting", source_cluster="a"),
        Evidence("E3", "contradicting", source_cluster="b"),
    ])
    assert result["support_score"] > 50
    assert result["coverage"] > 0
    assert result["source_clusters"] == 2

def test_old_evidence_decays():
    now = date(2026, 10, 6)
    fresh = Evidence("E4", "supporting", observed_on=now, category="pricing")
    old = Evidence("E4", "supporting", observed_on=now - timedelta(days=180), category="pricing")
    assert effective_weight(old, now) < effective_weight(fresh, now)

def test_high_quality_guardrail_requires_independent_clusters_and_behavior():
    one = [Evidence("E3", "supporting", source_quality=1, source_cluster="a")]
    two = [Evidence("E4", "supporting", source_quality=1, source_cluster="a"), Evidence("E4", "supporting", source_quality=1, source_cluster="b")]
    assert score_evidence(one)["data_quality"] != "HIGH"
    assert score_evidence(two)["data_quality"] == "HIGH"
