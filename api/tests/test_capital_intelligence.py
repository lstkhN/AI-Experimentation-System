from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.main import app
from app.engines.capital_allocator import allocate_capital
from app.engines.experiment_economics import calculate_experiment_economics


def test_pure_engines_are_deterministic_and_sequential():
    assert calculate_experiment_economics(estimated_cost=100, success_probability=.5, upside=300, learning_value=10)["recommended_spend"] == 100
    result = allocate_capital(150, [{"recommended_spend": 100, "gate_unlocked": True}, {"recommended_spend": 100, "gate_unlocked": True}])
    assert [item["status"] for item in result["allocations"]] == ["ALLOCATED", "PARTIAL"]


def test_capital_plan_gate_evaluation_and_allocation():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine); factory = sessionmaker(bind=engine)
    def override():
        db = factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override
    client = TestClient(app)
    try:
        project = client.post("/api/v1/projects", json={"name": "Capital"}).json()
        response = client.post(f"/api/v1/projects/{project['id']}/capital-plans", json={"available_budget": 150, "gates": [
            {"name": "learn", "recommended_spend": 100, "unlock_conditions": [{"metric": "interviews", "operator": ">=", "value": 10}]},
            {"name": "scale", "recommended_spend": 100},
        ]})
        assert response.status_code == 200
        plan_id = response.json()["id"]
        assert client.post(f"/api/v1/projects/{project['id']}/capital-plans/{plan_id}/gates/evaluate", json={"metrics": {"interviews": 10}}).json()["gates"][0]["status"] == "UNLOCKED"
        allocation = client.post(f"/api/v1/projects/{project['id']}/capital-plans/{plan_id}/allocate", json={}).json()
        assert [item["status"] for item in allocation["allocations"]] == ["ALLOCATED", "PARTIAL"]
    finally:
        client.close(); app.dependency_overrides.clear(); Base.metadata.drop_all(engine); engine.dispose()
