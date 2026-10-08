from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import AnalysisRun, Base, EconomicsModel, ExperimentProposal, ProjectVerdict
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
    return TestClient(app), engine, factory


def test_report_is_project_isolated_and_export_matches_report():
    client, engine, factory = _client()
    try:
        first = client.post("/api/v1/projects", json={"name": "First"}).json()
        second = client.post("/api/v1/projects", json={"name": "Second"}).json()
        first_hypothesis = client.post(f"/api/v1/projects/{first['id']}/hypotheses", json={
            "statement": "First only", "importance": 0.9,
        }).json()
        second_hypothesis = client.post(f"/api/v1/projects/{second['id']}/hypotheses", json={
            "statement": "Second secret", "importance": 0.1,
        }).json()
        assert client.post(f"/api/v1/projects/{first['id']}/evidence", json={
            "hypothesis_id": first_hypothesis["id"], "content": "First evidence", "source_name": "First source",
        }).status_code == 201
        assert client.post(f"/api/v1/projects/{second['id']}/evidence", json={
            "hypothesis_id": second_hypothesis["id"], "content": "Second secret evidence", "source_name": "Second source",
        }).status_code == 201

        db = factory()
        try:
            run = AnalysisRun(project_id=first["id"], status="completed", inputs={"run": "first"}, result={})
            economics = EconomicsModel(project_id=first["id"], economics_inputs={"price": 10}, result={})
            db.add_all([run, economics])
            db.flush()
            db.add_all([
                ExperimentProposal(project_id=first["id"], template_key="landing_page_v1", title="First test", rules={}),
                ExperimentProposal(project_id=second["id"], template_key="landing_page_v1", title="Secret test", rules={}),
                ProjectVerdict(project_id=first["id"], economics_model_id=economics.id, verdict="go", result={
                    "verdict": "go", "decisive_facts": [{"fact": "First fact"}], "unknowns": ["First unknown"],
                    "ranked_assumptions": [{"assumption": "First assumption"}],
                }),
            ])
            db.commit()
        finally:
            db.close()

        report = client.get(f"/api/v1/projects/{first['id']}/report")
        assert report.status_code == 200
        body = report.json()
        assert body["latest_run"]["inputs"] == {"run": "first"}
        assert body["latest_economics"]["economics_inputs"] == {"price": 10}
        assert [item["statement"] for item in body["hypotheses"]] == ["First only"]
        assert [item["content"] for item in body["evidence"]] == ["First evidence"]
        assert [item["title"] for item in body["experiments"]] == ["First test"]
        assert body["decisive_facts"] == [{"fact": "First fact"}]
        assert body["unknowns"] == ["First unknown"]
        assert body["ranked_assumptions"] == [{"assumption": "First assumption"}]
        assert body["language_metadata"] == {"code": "en", "source": "project_intake"}
        assert body["project_verdict"]["market"]["status"] == "unknown"
        assert {gap["section"] for gap in body["data_gaps"]} == {
            "icp", "market", "competitor", "monetization", "risk_map",
        }
        assert client.get(f"/api/v1/projects/{first['id']}/export/json").json() == body
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_report_for_empty_project_has_explicit_empty_sections():
    client, engine, _factory = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "Empty"}).json()
        response = client.get(f"/api/v1/projects/{project['id']}/report")
        assert response.status_code == 200
        body = response.json()
        assert body["latest_run"] is None
        assert body["latest_economics"] is None
        assert body["project_verdict"] is None
        assert body["icp"]["status"] == "unknown"
        assert len(body["data_gaps"]) == 15
        for key in ("hypotheses", "verdicts", "evidence", "experiments", "decisive_facts", "unknowns", "ranked_assumptions"):
            assert body[key] == []
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
