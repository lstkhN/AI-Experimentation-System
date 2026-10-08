from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.main import app
from app.services.openai_orchestrator import OpenAIOrchestrator
from app.services.research import ResearchResult


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


def test_markdown_export_includes_persisted_evidence_and_capital_plan():
    client, engine = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "Exportable", "description": "<script>unsafe()</script>"}).json()
        hypothesis = client.post(f"/api/v1/projects/{project['id']}/hypotheses", json={
            "statement": "Buyers will pay", "category": "willingness_to_pay", "importance": 0.9,
        }).json()
        evidence = client.post(f"/api/v1/projects/{project['id']}/evidence", json={
            "hypothesis_id": hypothesis["id"], "content": "A buyer paid a deposit", "tier": "E5",
            "source_name": "Interview", "url": "https://example.test/deposit",
        })
        assert evidence.status_code == 201
        plan = client.post(f"/api/v1/projects/{project['id']}/economics/capital-plan", json={
            "currency": "EUR", "capital_steps": [{"name": "Paid offer", "amount": 100,
            "expected_learning": "Measure WTP", "unlock_condition": "Two paid pilots"}],
        })
        assert plan.status_code == 200

        json_export = client.get(f"/api/v1/projects/{project['id']}/export/json")
        assert json_export.status_code == 200
        assert json_export.json()["format_version"] == "v1.1"
        report = json_export.json()
        assert report["economics_models"][0]["economics_inputs"]["formula_version"] == "v1.1"
        assert [event["event_type"] for event in report["audit_events"]] == [
            "project.created", "evidence.created", "economics.snapshot.created",
        ]

        other = client.post("/api/v1/projects", json={"name": "Not exported"}).json()
        assert client.post(f"/api/v1/projects/{other['id']}/evidence", json={
            "content": "Other project evidence",
        }).status_code == 201
        isolated = client.get(f"/api/v1/projects/{project['id']}/export/json").json()
        assert isolated["project"]["id"] == project["id"]
        assert "Not exported" not in str(isolated)
        assert "Other project evidence" not in str(isolated)

        exported = client.get(f"/api/v1/projects/{project['id']}/export/markdown")
        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith("text/markdown")
        assert "# Exportable" in exported.text
        printable = client.get(f"/api/v1/projects/{project['id']}/export/html")
        assert printable.status_code == 200
        assert printable.headers["content-type"].startswith("text/html")
        assert "Print / Save as PDF" in printable.text
        # Stored report text must be inert in the print document.
        assert "<script>unsafe()</script>" not in printable.text
        assert "&amp;lt;script&amp;gt;unsafe()&amp;lt;/script&amp;gt;" in printable.text
        assert "A buyer paid a deposit" in exported.text
        assert "Paid offer" in exported.text and "Expected learning" in exported.text
        assert "Formula version" in exported.text and "v1\\.1" in exported.text
        assert "## Structured Data Gaps" in exported.text
        assert "icp.target\\_customer\\_profile" in exported.text
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_openai_retries_transient_error_then_uses_configured_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_FALLBACK_MODEL", "luna")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "1")
    calls = []

    class Completions:
        def create(self, *, model, **_kwargs):
            calls.append(model)
            if model == "terra":
                raise TimeoutError("temporary outage")
            return type("Response", (), {
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "choices": [type("Choice", (), {"message": type("Message", (), {
                    "content": '{"hypotheses": [{"category": "problem", "statement": "Pain exists"}]}'
                })()})()],
            })()

    client = type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
    orchestrator = OpenAIOrchestrator(api_key="key", model="terra", client=client)
    orchestrator._sleep = lambda _seconds: None
    result = orchestrator.generate_hypotheses({"name": "Idea"}, [ResearchResult("Source", "https://x.test", "fact")])

    assert result == [{"category": "problem", "statement": "Pain exists"}]
    assert calls == ["terra", "terra", "luna"]
