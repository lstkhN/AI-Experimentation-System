from app.services.report_gaps import build_structured_report_gaps


def test_structured_report_gaps_are_explicit_and_deterministic():
    first = build_structured_report_gaps("ru")
    second = build_structured_report_gaps("ru")

    assert first == second
    assert first["language_metadata"] == {"code": "ru", "source": "project_intake"}
    assert set(first) >= {"icp", "market", "competitor", "monetization", "risk_map", "data_gaps"}
    assert {gap["section"] for gap in first["data_gaps"]} == {
        "icp", "market", "competitor", "monetization", "risk_map",
    }
    assert all(gap["status"] == "unknown" for gap in first["data_gaps"])
    assert all(gap["reason"] == "not_collected_as_structured_data" for gap in first["data_gaps"])
    assert all(first[section]["status"] == "unknown" for section in (
        "icp", "market", "competitor", "monetization", "risk_map",
    ))
