from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import AuditEvent, Base
from app.db.session import get_db
from app.main import app


def test_key_writes_create_audit_events_without_changing_responses():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            project = client.post("/api/v1/projects", json={"name": "Audited project"})
            assert project.status_code == 201
            project_id = project.json()["id"]

            run = client.post(f"/api/v1/projects/{project_id}/analysis-runs", json={"inputs": {"goal": "test"}})
            assert run.status_code == 202
            run_id = run.json()["id"]
            executed = client.post(f"/api/v1/projects/{project_id}/analysis-runs/{run_id}/execute")
            assert executed.status_code == 200
            assert executed.json()["status"] == "completed"
            # Worker completion automatically persists a decision report even without manual evidence.
            report = client.get(f"/api/v1/projects/{project_id}/verdict")
            assert report.status_code == 200
            assert report.json()["idea_summary"]["name"] == "Audited project"
            assert report.json()["next_recommended_tests"]

            hypothesis = client.get(f"/api/v1/projects/{project_id}/hypotheses").json()[0]
            evidence = client.post(f"/api/v1/projects/{project_id}/evidence", json={
                "hypothesis_id": hypothesis["id"], "content": "Customer interview", "tier": "E5",
            })
            assert evidence.status_code == 201
            verdict = client.post(f"/api/v1/projects/{project_id}/hypotheses/{hypothesis['id']}/verdict")
            assert verdict.status_code == 201
            economics = client.post(f"/api/v1/projects/{project_id}/economics/calculate", json={
                "scenarios": [{"price": 100, "variable_cost": 20}],
            })
            assert economics.status_code == 200
            assert "snapshot_id" in economics.json()

        with factory() as db:
            events = list(db.scalars(select(AuditEvent).order_by(AuditEvent.id)))

        assert [event.event_type for event in events] == [
            "project.created",
            "analysis_run.created",
            "analysis_run.completed",
            "evidence.created",
            "verdict.created",
            "economics.snapshot.created",
        ]
        assert all(event.project_id == project_id for event in events)
        assert events[1].payload == {"inputs": {"goal": "test"}, "status": "queued"}
        assert events[2].payload["hypotheses_created"] == 5
        assert events[-1].payload == {"currency": "USD", "scenario_count": 1}
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
