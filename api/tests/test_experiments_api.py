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


def test_templates_are_deterministic_and_include_decision_rules():
    client, engine = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "Test"}).json()
        response = client.get(f"/api/v1/projects/{project['id']}/experiments/templates")
        assert response.status_code == 200
        templates = response.json()
        assert len(templates) == 12
        assert [item["template_key"] for item in templates] == [
            "problem_interviews_v1", "problem_survey_v1", "landing_page_v1", "smoke_test_v1",
            "fake_door_v1", "prototype_usability_v1", "concierge_v1", "wizard_of_oz_v1",
            "mvp_pilot_v1", "preorder_v1", "pricing_interviews_v1", "paid_pilot_v1",
        ]
        for template in templates:
            assert {"target", "sample", "pass_rule", "partial_rule", "fail_rule", "stop_rule"} <= template["rules"].keys()
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_propose_and_recommend_are_project_isolated():
    client, engine = _client()
    try:
        first = client.post("/api/v1/projects", json={"name": "First"}).json()
        second = client.post("/api/v1/projects", json={"name": "Second"}).json()
        hypothesis = client.post(f"/api/v1/projects/{second['id']}/hypotheses", json={
            "statement": "Buyers have a sufficiently painful recurring problem", "importance": 0.9,
        }).json()
        forbidden = client.post(f"/api/v1/projects/{first['id']}/experiments/propose", json={
            "template_key": "problem_interviews_v1", "hypothesis_id": hypothesis["id"],
        })
        assert forbidden.status_code == 404
        proposal = client.post(f"/api/v1/projects/{second['id']}/experiments/propose", json={
            "template_key": "problem_interviews_v1", "hypothesis_id": hypothesis["id"],
        })
        assert proposal.status_code == 201
        assert client.get(f"/api/v1/projects/{first['id']}/experiments").json() == []
        recommendation = client.get(f"/api/v1/projects/{second['id']}/experiments/recommend-next-test")
        assert recommendation.status_code == 200
        assert recommendation.json()["hypothesis_id"] is None
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
