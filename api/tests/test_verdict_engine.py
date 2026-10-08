from app.engines.evidence import Evidence
from app.engines.verdict import VerdictEngine, evaluate_verdict


def test_no_evidence_is_unproven_and_lists_evidence_gaps():
    result = evaluate_verdict([])

    assert result["verdict"] == "UNPROVEN"
    assert result["support_score"] == 50
    assert result["coverage"] == 0
    assert result["data_quality"] == "LOW"
    assert result["decisive_facts"] == []
    assert "no_evidence" in result["unknowns"]


def test_independent_strong_support_is_promising():
    result = evaluate_verdict([
        Evidence("E5", "supporting", source_quality=1, source_cluster="interviews"),
        Evidence("E5", "supporting", source_quality=1, source_cluster="transactions"),
    ])

    assert result["verdict"] == "PROMISING"
    assert result["rule"] == "supported_with_sufficient_coverage"
    assert result["data_quality"] == "HIGH"
    assert [fact["source_cluster"] for fact in result["decisive_facts"]] == ["interviews", "transactions"]


def test_material_high_quality_contradiction_is_no_go_for_now():
    result = evaluate_verdict([
        Evidence("E5", "contradicting", source_cluster="failed-sales"),
    ])

    assert result["verdict"] == "NO-GO-FOR-NOW"
    assert result["rule"] == "material_contradiction"
    assert result["decisive_facts"][0]["direction"] == "contradicting"


def test_inconclusive_evidence_stays_unproven_and_exposes_unknowns():
    result = VerdictEngine().evaluate([
        Evidence("E2", "supporting", source_quality=0.5, source_cluster="one-source"),
    ])

    assert result["verdict"] == "UNPROVEN"
    assert "insufficient_coverage" in result["unknowns"]
    assert "low_data_quality" in result["unknowns"]
    assert "insufficient_independent_sources" in result["unknowns"]


def test_mixed_evidence_with_a_negative_balance_is_weak():
    result = evaluate_verdict([
        Evidence("E4", "contradicting", source_cluster="a"),
        Evidence("E4", "contradicting", source_cluster="b"),
        Evidence("E5", "supporting", source_cluster="c"),
    ])

    assert result["verdict"] == "WEAK"
    assert result["rule"] == "net_contradiction_without_no_go_confidence"
