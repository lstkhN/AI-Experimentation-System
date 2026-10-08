from app.engines.project_verdict import evaluate_project_verdict


def test_project_verdict_without_evidence_is_unproven():
    result = evaluate_project_verdict([
        {
            "hypothesis_id": 1,
            "statement": "Customers will pay",
            "importance": 0.8,
            "verdict": "UNPROVEN",
            "coverage": 0,
            "support_score": 50,
            "rule": "insufficient_or_inconclusive_evidence",
            "unknowns": ["no_evidence"],
            "decisive_facts": [],
        }
    ], None)

    assert result["verdict"] == "UNPROVEN"
    assert result["evidence_coverage"] == 0
    assert "no_evidence" in result["unknowns"]
    assert result["economics"]["status"] == "missing"
    assert result["language_metadata"] == {"code": "en", "source": "project_intake"}
    assert result["icp"]["status"] == "unknown"
    assert {gap["section"] for gap in result["data_gaps"]} == {
        "icp", "market", "competitor", "monetization", "risk_map",
    }


def test_project_verdict_is_deterministic_and_kills_high_priority_no_go():
    hypotheses = [{
        "hypothesis_id": 7,
        "statement": "Demand exists",
        "importance": 0.9,
        "verdict": "NO-GO-FOR-NOW",
        "coverage": 50,
        "support_score": 10,
        "rule": "material_contradiction",
        "unknowns": [],
        "decisive_facts": [{"source_cluster": "customers", "weight": 0.6}],
    }]

    first = evaluate_project_verdict(hypotheses, None)
    second = evaluate_project_verdict(hypotheses, None)

    assert first == second
    assert first["verdict"] == "NO-GO-FOR-NOW"
    assert first["kill_gates"] == [{
        "gate": "high_priority_hypothesis_no_go", "hypothesis_id": 7,
        "reason": "A high-priority hypothesis has a NO-GO-FOR-NOW verdict.",
    }]


def test_extended_report_marks_search_snippets_as_candidates_and_supplies_tests():
    result = evaluate_project_verdict([], None, intake={"name": "Minimal", "description": "A concise idea"},
        research_results=[{"title": "Search result", "url": "https://example.test", "content": "Unverified claim"}])

    assert result["idea_summary"]["description"] == "A concise idea"
    assert result["market_findings"] == [{"title": "Search result", "url": "https://example.test",
        "snippet": "Unverified claim", "status": "candidate", "evidence_status": "unverified_search_snippet"}]
    assert result["evidence_quality"]["status"] == "unknown"
    assert result["next_recommended_tests"]
