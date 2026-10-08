from app.engines.economics import calculate_economics
from app.engines.project_verdict import evaluate_project_verdict


def _hypothesis(**overrides):
    item = {
        "hypothesis_id": 1, "statement": "Customers will pay", "importance": 0.2,
        "criticality": "NORMAL", "is_blocking": False, "verdict": "PROMISING",
        "coverage": 100, "support_score": 90, "rule": "supported", "unknowns": [], "decisive_facts": [],
    }
    item.update(overrides)
    return item


def _reliable_economics():
    return {
        "snapshot_id": 1,
        "reliability": "RELIABLE",
        "inputs": {"scenarios": [{"name": "base", "cac": 20}]},
        "result": {"scenarios": [{"name": "base", "metrics": {"ltv_simple": 100, "months_to_payback": 1}}], "unknowns": []},
    }


def test_blocking_or_fatal_unproven_hypothesis_prevents_go():
    for criticality, is_blocking in (("NORMAL", True), ("FATAL", False)):
        result = evaluate_project_verdict([_hypothesis(criticality=criticality, is_blocking=is_blocking, verdict="UNPROVEN")], _reliable_economics())
        assert result["verdict"] == "UNPROVEN"
        assert result["decision"] == "VALIDATE"
        assert result["action"] == "validate_critical_assumptions"
        assert result["unresolved_critical_hypotheses"] == [{"hypothesis_id": 1, "criticality": criticality, "is_blocking": is_blocking}]


def test_insufficient_economics_inputs_cannot_produce_go():
    economics = {"snapshot_id": 1, "reliability": "INSUFFICIENT_CRITICAL_INPUTS", "inputs": {}, "result": {"scenarios": [], "unknowns": []}}
    result = evaluate_project_verdict([_hypothesis()], economics)
    assert result["verdict"] == "UNPROVEN"
    assert result["decision"] == "VALIDATE"
    assert result["economics"]["reliability"] == "INSUFFICIENT_CRITICAL_INPUTS"


def test_decision_report_separates_market_viability_experiments_and_capital():
    result = evaluate_project_verdict(
        [_hypothesis()], _reliable_economics(),
        market_context={"market_entities": [{"name": "market"}], "icp_segments": [{"name": "ICP"}],
                        "competitors": [{"name": "competitor"}], "monetization_assumptions": []},
        experiment_results=[{"id": 1, "title": "Landing page", "status": "approved"},
                            {"id": 2, "title": "Survey", "status": "rejected", "rationale": "Too slow"}],
        capital_plan={"currency": "USD", "available_budget": 1000, "recommended_spend": 200,
                      "gates": [{"id": 1, "name": "Validate", "status": "LOCKED", "recommended_spend": 200}]},
    )
    assert result["decision"] == "GO"
    assert result["market_attractiveness"]["status"] == "assessed"
    assert result["business_viability"]["status"] == "viable"
    assert result["experiment_comparison"]["selected"][0]["title"] == "Landing page"
    assert result["experiment_comparison"]["why_not_alternatives"][0]["why_not"] == "Too slow"
    assert result["capital_recommendation"]["status"] == "gated"


def test_economics_reliability_requires_churn_and_cac():
    assert calculate_economics([{"name": "base", "price": 100, "variable_cost": 20, "monthly_churn": None, "cac": None}])["reliability"] == "INSUFFICIENT_CRITICAL_INPUTS"
    assert calculate_economics([{"name": "base", "price": 100, "variable_cost": 20, "monthly_churn": .1, "cac": 50}])["reliability"] == "RELIABLE"
