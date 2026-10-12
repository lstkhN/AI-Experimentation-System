from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AuditEvent, EconomicParameter, EconomicsModel, Evidence, EvidenceSource
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.main import app


def _client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app), engine


def test_calculate_economics_persists_snapshot_and_churn_sensitivity():
    client, engine = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "Economics"}).json()
        response = client.post(f"/api/v1/projects/{project['id']}/economics/calculate", json={
            "scenarios": [{"name": "base", "price": 100, "variable_cost": 20, "monthly_churn": 0.1, "cac": 120}],
            "sensitivity": {"monthly_churn_rates": [0.2, 0.05]},
            "capital_steps": [{"name": "MVP", "amount": 1000, "month": 0}],
        })
        assert response.status_code == 200
        body = response.json()
        assert body["scenarios"][0]["metrics"]["ltv_simple"] == 800
        assert [x["monthly_churn"] for x in body["scenarios"][0]["sensitivity"]["values"]] == [0.05, 0.2]
        assert body["capital_plan"]["total_required"] == 1000

        plan = client.get(f"/api/v1/projects/{project['id']}/economics/capital-plan")
        assert plan.status_code == 200
        assert plan.json()["snapshot_id"] == body["snapshot_id"]
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_calculation_reliability_requires_project_verified_evidence_ids():
    client, engine = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "Provenance"}).json()
        fields = ("price", "variable_cost", "monthly_churn", "cac", "fixed_monthly_cost", "target_ltv_cac_ratio")
        scenario = {
            "price": 100, "variable_cost": 20, "monthly_churn": 0.1, "cac": 120,
            "fixed_monthly_cost": 0, "target_ltv_cac_ratio": 3,
            "parameter_provenance": {
                field: {"source_type": "verified_evidence", "source_id": "999", "confidence": "HIGH", "observed": True}
                for field in fields
            },
        }
        assert client.post(f"/api/v1/projects/{project['id']}/economics/calculate", json={"scenarios": [scenario]}).json()["reliability"] == "HEURISTIC"
        with Session(engine) as db:
            source = EvidenceSource(project_id=project["id"], identity_key="economics-source", name="Verified")
            db.add(source)
            db.flush()
            evidence = Evidence(source_id=source.id, content="verified economics input", evidence_status="verified")
            db.add(evidence)
            db.commit()
            evidence_id = str(evidence.id)
        for provenance in scenario["parameter_provenance"].values():
            provenance["source_id"] = evidence_id
        response = client.post(f"/api/v1/projects/{project['id']}/economics/calculate", json={"scenarios": [scenario]})
        assert response.status_code == 200
        assert response.json()["reliability"] == "RELIABLE"
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_unknown_churn_is_explicit_and_capital_plan_can_be_saved_without_scenarios():
    client, engine = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "Unknown churn"}).json()
        calculated = client.post(f"/api/v1/projects/{project['id']}/economics/calculate", json={
            "scenarios": [{"price": 100, "variable_cost": 30}],
        })
        assert calculated.status_code == 200
        scenario = calculated.json()["scenarios"][0]
        assert scenario["metrics"]["ltv_simple"] is None
        assert scenario["sensitivity"] == {"status": "requires_assumption", "unknowns": ["monthly_churn"], "values": []}

        plan = client.post(f"/api/v1/projects/{project['id']}/economics/capital-plan", json={
            "capital_steps": [{"name": "Discovery", "amount": 500, "trigger": "10 interviews"}],
            "currency": "EUR",
        })
        assert plan.status_code == 200
        assert plan.json()["currency"] == "EUR"
        assert plan.json()["total_required"] == 500
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_simulation_api_is_seeded_and_persists_provenance():
    client, engine = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "Simulation"}).json()
        payload = {
            "seed": 9, "iterations": 50,
            "scenarios": [{
                "price": {"kind": "uniform", "low": 90, "high": 110},
                "variable_cost": {"value": 20}, "monthly_churn": {"value": .1},
                "cac": {"value": 120}, "fixed_monthly_cost": {"value": 800},
            }],
        }
        response = client.post(f"/api/v1/projects/{project['id']}/economics/simulate", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["formula_version"] == "economics-decision-v2"
        assert body["provenance"]["llm_used"] is False
        assert body["provenance"]["seed"] == 9
        assert set(body["scenarios"][0]["payback_months"]) == {"p10", "p50", "p90"}
        assert body["reliability"] == "HEURISTIC"
        legacy_voi = body["scenarios"][0]["value_of_information"]
        assert legacy_voi["status"] == "HEURISTIC"
        assert legacy_voi["method"] == "deterministic_evsi_evpi_heuristic_fallback"
        assert body["decision_contract"]["threshold"]["critical_parameters"] == ["price", "variable_cost", "monthly_churn", "cac", "fixed_monthly_cost"]
        with Session(engine) as db:
            price = db.query(EconomicParameter).filter_by(name="price").one()
            assert price.scenario_name == "base"
            assert price.distribution == {"kind": "uniform", "value": None, "low": 90.0, "high": 110.0, "mode": None, "mean": None, "stddev": None}
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_value_of_information_api_is_seeded_persists_snapshot_and_audit_event():
    client, engine = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "VOI"}).json()
        payload = {
            "prior_alpha": 2, "prior_beta": 8, "decision_threshold": .3,
            "upside": 1000, "downside": -300, "iterations": 500, "seed": 7,
            "experiments": [{"name": "landing", "sample_size": 100, "cost": 50}],
        }
        first = client.post(f"/api/v1/projects/{project['id']}/economics/value-of-information", json=payload)
        second = client.post(f"/api/v1/projects/{project['id']}/economics/value-of-information", json=payload)
        assert first.status_code == second.status_code == 200
        first_body, second_body = first.json(), second.json()
        assert first_body["snapshot_id"] != second_body["snapshot_id"]
        assert {key: value for key, value in first_body.items() if key != "snapshot_id"} == {
            key: value for key, value in second_body.items() if key != "snapshot_id"
        }
        experiment = first_body["experiments"][0]
        assert 0 <= experiment["evsi_gross"] <= first_body["evpi"]
        assert experiment["evsi_net"] == experiment["evsi_gross"] - payload["experiments"][0]["cost"]
        with Session(engine) as db:
            snapshot = db.get(EconomicsModel, first_body["snapshot_id"])
            assert snapshot.reliability == "HEURISTIC"
            assert snapshot.economics_inputs["value_of_information"] == payload
            assert snapshot.economics_inputs["formula_version"] == "economics-decision-v2"
            assert snapshot.result["value_of_information"].get("snapshot_id") is None
            event = db.query(AuditEvent).filter_by(
                entity_id=snapshot.id, event_type="economics.value_of_information.calculated"
            ).one()
            assert event.entity_type == "economics_snapshot"
            assert event.payload["snapshot_id"] == snapshot.id
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_get_value_of_information_returns_latest_snapshot_and_empty_state():
    client, engine = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "Saved VOI"}).json()
        path = f"/api/v1/projects/{project['id']}/economics/value-of-information"
        assert client.get(path).status_code == 404
        first = client.post(path, json={
            "prior_alpha": 2, "prior_beta": 8, "decision_threshold": .3,
            "upside": 1000, "downside": -300, "experiments": [{"name": "first", "sample_size": 20, "cost": 10}],
            "iterations": 100, "seed": 3,
        }).json()
        latest = client.post(path, json={
            "prior_alpha": 2, "prior_beta": 8, "decision_threshold": .3,
            "upside": 1000, "downside": -300, "experiments": [{"name": "latest", "sample_size": 30, "cost": 20}],
            "iterations": 100, "seed": 4,
        }).json()
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["snapshot_id"] == latest["snapshot_id"]
        assert response.json()["snapshot_id"] != first["snapshot_id"]
        assert response.json()["experiments"][0]["name"] == "latest"
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_value_of_information_does_not_replace_primary_economics_for_verdict():
    client, engine = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "VOI verdict ordering"}).json()
        economics = client.post(f"/api/v1/projects/{project['id']}/economics/calculate", json={
            "scenarios": [{"name": "base", "price": 100, "variable_cost": 20, "monthly_churn": 0.1, "cac": 120}],
        })
        assert economics.status_code == 200
        voi = client.post(f"/api/v1/projects/{project['id']}/economics/value-of-information", json={
            "prior_alpha": 2, "prior_beta": 8, "decision_threshold": .3,
            "upside": 1000, "downside": -300,
            "experiments": [{"name": "landing", "sample_size": 20, "cost": 10}],
            "iterations": 100, "seed": 3,
        })
        assert voi.status_code == 200
        verdict = client.post(f"/api/v1/projects/{project['id']}/verdict")
        assert verdict.status_code == 201
        assert verdict.json()["economics"]["snapshot_id"] == economics.json()["snapshot_id"]
        assert verdict.json()["economics"]["snapshot_id"] != voi.json()["snapshot_id"]
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_value_of_information_api_validates_payload_and_project():
    client, engine = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "VOI validation"}).json()
        invalid = client.post(f"/api/v1/projects/{project['id']}/economics/value-of-information", json={
            "prior_alpha": 0, "prior_beta": 1, "decision_threshold": 1,
            "upside": 1, "downside": 0, "experiments": [],
        })
        assert invalid.status_code == 422
        missing = client.post("/api/v1/projects/999/economics/value-of-information", json={
            "prior_alpha": 1, "prior_beta": 1, "decision_threshold": .5,
            "upside": 1, "downside": 0, "experiments": [{"name": "test", "sample_size": 1, "cost": 0}],
        })
        assert missing.status_code == 404
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_project_economics_requires_existing_project():
    client, engine = _client()
    try:
        response = client.post("/api/v1/projects/999/economics/calculate", json={
            "scenarios": [{"price": 100, "variable_cost": 20}],
        })
        assert response.status_code == 404
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
