from datetime import date, timedelta

from app.engines.evidence import Evidence, effective_weight, freshness_factor, score_evidence


def test_candidates_do_not_contribute_until_explicitly_verified():
    candidate = Evidence("E5", "supporting", source_cluster="publisher", evidence_status="candidate")
    assert effective_weight(candidate) == 0
    assert score_evidence([candidate])["coverage"] == 0
    assert score_evidence([candidate])["unverified_candidates"] == 1


def test_clustered_pages_are_penalized_relative_to_independent_sources():
    clustered = [
        Evidence("E5", "supporting", source_cluster="one-publisher"),
        Evidence("E5", "supporting", source_cluster="one-publisher"),
    ]
    independent = [
        Evidence("E5", "supporting", source_cluster="publisher-a"),
        Evidence("E5", "supporting", source_cluster="publisher-b"),
    ]
    assert score_evidence(clustered)["support_mass"] < score_evidence(independent)["support_mass"]


def test_freshness_uses_category_specific_half_lives():
    today = date(2026, 1, 1)
    old = today - timedelta(days=180)
    assert freshness_factor(old, "pricing", today) < freshness_factor(old, "retention", today)
