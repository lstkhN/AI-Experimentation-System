from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
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
        assert body["formula_version"] == "economics-mvp-v1"
        assert body["provenance"]["llm_used"] is False
        assert body["provenance"]["seed"] == 9
        assert set(body["scenarios"][0]["payback_months"]) == {"p10", "p50", "p90"}
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
