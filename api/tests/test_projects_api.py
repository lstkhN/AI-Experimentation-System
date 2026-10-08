import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import engine as session_engine, get_db
from app.main import app


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_sqlite_session_engine_enables_foreign_keys():
    if session_engine.dialect.name != "sqlite":
        pytest.skip("foreign-key pragma only applies to SQLite")
    with session_engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_create_and_list_projects(client):
    created = client.post(
        "/api/v1/projects",
        json={"name": "Pricing experiment", "description": "Validate willingness to pay."},
    )

    assert created.status_code == 201
    assert created.json()["id"] == 1
    assert created.json()["name"] == "Pricing experiment"
    assert created.json()["description"] == "Validate willingness to pay."

    listed = client.get("/api/v1/projects")

    assert listed.status_code == 200
    assert [project["name"] for project in listed.json()] == ["Pricing experiment"]


def test_project_history_is_chronological_and_project_isolated(client):
    first = client.post("/api/v1/projects", json={"name": "First"}).json()
    second = client.post("/api/v1/projects", json={"name": "Second"}).json()
    run = client.post(f"/api/v1/projects/{first['id']}/analysis-runs", json={"inputs": {"owner": "first"}})
    assert run.status_code == 202

    history = client.get(f"/api/v1/projects/{first['id']}/history")

    assert history.status_code == 200
    assert [event["event_type"] for event in history.json()] == ["project.created", "analysis_run.created"]
    assert all(event["project_id"] == first["id"] for event in history.json())
    assert client.get(f"/api/v1/projects/{second['id']}/history").json()[0]["payload"] == {"name": "Second"}
    assert client.get("/api/v1/projects/999/history").status_code == 404


def test_delete_project_cascades_owned_records_and_keeps_other_projects(client):
    first = client.post("/api/v1/projects", json={"name": "Delete me"}).json()
    second = client.post("/api/v1/projects", json={"name": "Keep me"}).json()
    run = client.post(f"/api/v1/projects/{first['id']}/analysis-runs", json={}).json()
    hypothesis = client.post(
        f"/api/v1/projects/{first['id']}/hypotheses", json={"statement": "Owned assumption"}
    ).json()
    assert client.post(f"/api/v1/projects/{first['id']}/evidence", json={
        "hypothesis_id": hypothesis["id"], "content": "Owned evidence",
    }).status_code == 201

    deleted = client.delete(f"/api/v1/projects/{first['id']}")

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get("/api/v1/projects").json() == [second]
    # Project-scoped reads prove the aggregate and its audit trail were removed;
    # the unrelated project remains accessible.
    assert client.get(f"/api/v1/projects/{first['id']}").status_code == 404
    assert client.get(f"/api/v1/projects/{first['id']}/history").status_code == 404
    assert client.get(f"/api/v1/projects/{first['id']}/export/json").status_code == 404
    assert client.get(f"/api/v1/projects/{first['id']}/analysis-runs/{run['id']}").status_code == 404
    assert client.get(f"/api/v1/projects/{first['id']}/hypotheses").status_code == 404
    assert client.get(f"/api/v1/projects/{second['id']}").json()["name"] == "Keep me"
    assert client.delete(f"/api/v1/projects/{first['id']}").status_code == 404


def test_create_project_accepts_intake_context(client):
    response = client.post(
        "/api/v1/projects",
        json={"name": "AI recruiter", "geography": "EU", "business_type": "B2B SaaS", "budget": 1000, "deadline_days": 30, "language": "ru", "known_facts": ["3 interviews"]},
    )
    assert response.status_code == 201
    assert response.json()["language"] == "ru"
    assert response.json()["budget"] == 1000


def test_create_project_requires_a_name(client):
    response = client.post("/api/v1/projects", json={"name": ""})

    assert response.status_code == 422


def test_analysis_run_lifecycle_starts_queued(client):
    project = client.post("/api/v1/projects", json={"name": "Test idea"}).json()
    created = client.post(f"/api/v1/projects/{project['id']}/analysis-runs", json={"inputs": {"goal": "validate demand"}})
    assert created.status_code == 202
    assert created.json()["status"] == "queued"
    assert created.json()["inputs"]["goal"] == "validate demand"


def test_analysis_run_requires_existing_project(client):
    response = client.post("/api/v1/projects/999/analysis-runs", json={})
    assert response.status_code == 404


def test_execute_run_creates_starter_hypotheses(client):
    project = client.post("/api/v1/projects", json={"name": "AI assistant", "description": "Automate proposals"}).json()
    run = client.post(f"/api/v1/projects/{project['id']}/analysis-runs", json={}).json()
    executed = client.post(f"/api/v1/projects/{project['id']}/analysis-runs/{run['id']}/execute")
    assert executed.status_code == 200
    assert executed.json()["status"] == "completed"
    assert executed.json()["result"]["hypotheses_created"] == 5
    hypotheses = client.get(f"/api/v1/projects/{project['id']}/hypotheses")
    assert hypotheses.status_code == 200
    assert len(hypotheses.json()) == 5
    assert hypotheses.json()[0]["category"] == "problem"
    assert hypotheses.json()[0]["importance"] == 0.9


def test_russian_project_gets_russian_starter_hypotheses(client):
    project = client.post("/api/v1/projects", json={"name": "Помощник", "language": "ru"}).json()
    run = client.post(f"/api/v1/projects/{project['id']}/analysis-runs", json={}).json()

    executed = client.post(f"/api/v1/projects/{project['id']}/analysis-runs/{run['id']}/execute")

    assert executed.status_code == 200
    statements = [item["statement"] for item in client.get(f"/api/v1/projects/{project['id']}/hypotheses").json()]
    assert any("клиент" in statement.lower() for statement in statements)


def test_normalize_run_evidence_endpoint_is_idempotent(client, monkeypatch):
    from app.api import runs
    from app.services.research import ResearchResult

    class ResearchProvider:
        is_configured = True

        def search(self, _query):
            return [
                ResearchResult("Report", "https://example.test/report?utm_source=test", "Demand is growing", 0.9),
                ResearchResult("Other report", "https://example.test/other", "More demand", 0.8),
            ]

    class Orchestrator:
        is_configured = True

        def generate_hypotheses(self, _context, _research):
            return [{"statement": "Customers will pay"}]

    monkeypatch.setattr(runs, "TavilyResearchProvider", ResearchProvider)
    monkeypatch.setattr(runs, "OpenAIOrchestrator", Orchestrator)
    project = client.post("/api/v1/projects", json={"name": "Test idea"}).json()
    run = client.post(f"/api/v1/projects/{project['id']}/analysis-runs", json={}).json()
    assert client.post(f"/api/v1/projects/{project['id']}/analysis-runs/{run['id']}/execute").status_code == 200
    hypothesis = client.get(f"/api/v1/projects/{project['id']}/hypotheses").json()[0]
    endpoint = f"/api/v1/projects/{project['id']}/analysis-runs/{run['id']}/normalize-evidence"

    normalized = client.post(endpoint, json={"hypothesis_id": hypothesis["id"]})
    assert normalized.status_code == 200
    # Provider runs persist normalized source claims before computing their
    # verdict; the explicit endpoint is therefore a safe idempotent replay.
    assert normalized.json() == {
        "sources_created": 0,
        "evidence_created": 0,
        "evidence_reused": 1,
        "results_skipped": 0,
        "hypotheses_normalized": 1,
    }
    repeated = client.post(endpoint, json={"hypothesis_id": hypothesis["id"]})
    assert repeated.status_code == 200
    assert repeated.json()["evidence_reused"] == 1
    assert repeated.json()["evidence_created"] == 0


def test_hypothesis_category_and_importance_are_persisted_and_returned(client):
    project = client.post("/api/v1/projects", json={"name": "Test idea"}).json()
    created = client.post(
        f"/api/v1/projects/{project['id']}/hypotheses",
        json={
            "statement": "Customers will pay to eliminate this recurring problem.",
            "category": "willingness_to_pay",
            "importance": 0.85,
        },
    )

    assert created.status_code == 201
    assert created.json()["category"] == "willingness_to_pay"
    assert created.json()["importance"] == 0.85
    listed = client.get(f"/api/v1/projects/{project['id']}/hypotheses")
    assert listed.json()[0]["category"] == "willingness_to_pay"
    assert listed.json()[0]["importance"] == 0.85


def test_hypothesis_defaults_and_validation(client):
    project = client.post("/api/v1/projects", json={"name": "Test idea"}).json()
    created = client.post(
        f"/api/v1/projects/{project['id']}/hypotheses",
        json={"statement": "Customers have this recurring problem."},
    )

    assert created.status_code == 201
    assert created.json()["category"] == "problem"
    assert created.json()["importance"] == 0.5
    invalid = client.post(
        f"/api/v1/projects/{project['id']}/hypotheses",
        json={"statement": "Customers have this recurring problem.", "importance": 1.1},
    )
    assert invalid.status_code == 422


def test_manual_evidence_is_linked_to_hypothesis(client):
    project = client.post("/api/v1/projects", json={"name": "Test idea"}).json()
    hypothesis = client.post(f"/api/v1/projects/{project['id']}/hypotheses", json={"statement": "Customers have this recurring problem"}).json()
    evidence = client.post(f"/api/v1/projects/{project['id']}/evidence", json={
        "hypothesis_id": hypothesis["id"], "content": "Customer paid for a workaround", "tier": "E5", "source_cluster": "customer-1"
    })
    assert evidence.status_code == 201
    assert evidence.json()["tier"] == "E5"


def test_verdict_is_persisted_from_linked_evidence_and_latest_is_returned(client):
    project = client.post("/api/v1/projects", json={"name": "Test idea"}).json()
    hypothesis = client.post(
        f"/api/v1/projects/{project['id']}/hypotheses",
        json={"statement": "Customers repeatedly pay for this problem"},
    ).json()
    # This evidence belongs to the project but is not linked to the hypothesis,
    # so it must not be included in its verdict.
    client.post(f"/api/v1/projects/{project['id']}/evidence", json={
        "content": "Unrelated supporting observation", "tier": "E6", "source_cluster": "unlinked"
    })
    client.post(f"/api/v1/projects/{project['id']}/evidence", json={
        "hypothesis_id": hypothesis["id"],
        "content": "Customer paid for a workaround",
        "direction": "contradicting",
        "tier": "E5",
        "source_cluster": "customer-1",
    })
    endpoint = f"/api/v1/projects/{project['id']}/hypotheses/{hypothesis['id']}/verdict"

    created = client.post(endpoint)

    assert created.status_code == 201
    assert created.json()["verdict"] == "NO-GO-FOR-NOW"
    assert created.json()["decisive_facts"] == [{
        "direction": "contradicting", "tier": "E5", "category": "problem",
        "source_cluster": "customer-1", "weight": 0.6,
    }]
    assert created.json()["id"]
    latest = client.get(endpoint)
    assert latest.status_code == 200
    assert latest.json() == created.json()


def test_project_verdict_with_no_evidence_is_unproven_and_persisted(client):
    project = client.post("/api/v1/projects", json={"name": "No evidence"}).json()
    hypothesis = client.post(
        f"/api/v1/projects/{project['id']}/hypotheses",
        json={"statement": "Customers will pay", "importance": 0.9},
    ).json()
    # Keep the existing hypothesis-verdict flow intact; the project engine
    # consumes its immutable snapshot rather than inventing evidence.
    assert client.post(
        f"/api/v1/projects/{project['id']}/hypotheses/{hypothesis['id']}/verdict"
    ).status_code == 201

    created = client.post(f"/api/v1/projects/{project['id']}/verdict")

    assert created.status_code == 201
    body = created.json()
    assert body["verdict"] == "UNPROVEN"
    assert body["evidence_coverage"] == 0
    assert "no_evidence" in body["unknowns"]
    assert body["kill_gates"] == []
    latest = client.get(f"/api/v1/projects/{project['id']}/verdict")
    assert latest.status_code == 200
    assert latest.json() == body


def test_project_verdict_reports_structured_unknowns_in_project_language(client):
    project = client.post("/api/v1/projects", json={"name": "Unknowns", "language": "ru"}).json()

    response = client.post(f"/api/v1/projects/{project['id']}/verdict")

    assert response.status_code == 201
    report = response.json()
    assert report["language_metadata"] == {"code": "ru", "source": "project_intake"}
    assert report["competitor"] == {
        "status": "unknown",
        "data_gaps": [
            {"section": "competitor", "field": "competitor_set", "status": "unknown", "reason": "not_collected_as_structured_data"},
            {"section": "competitor", "field": "alternative_solutions", "status": "unknown", "reason": "not_collected_as_structured_data"},
            {"section": "competitor", "field": "competitive_differentiation", "status": "unknown", "reason": "not_collected_as_structured_data"},
        ],
    }
    assert {gap["section"] for gap in report["data_gaps"]} == {
        "icp", "market", "competitor", "monetization", "risk_map",
    }


def test_project_verdict_isolated_to_requested_project(client):
    first = client.post("/api/v1/projects", json={"name": "Included"}).json()
    second = client.post("/api/v1/projects", json={"name": "Excluded"}).json()
    included = client.post(
        f"/api/v1/projects/{first['id']}/hypotheses",
        json={"statement": "Included assumption", "importance": 0.5},
    ).json()
    excluded = client.post(
        f"/api/v1/projects/{second['id']}/hypotheses",
        json={"statement": "Excluded assumption", "importance": 0.9},
    ).json()
    client.post(f"/api/v1/projects/{second['id']}/evidence", json={
        "hypothesis_id": excluded["id"], "content": "Contradicting fact",
        "direction": "contradicting", "tier": "E5", "source_cluster": "excluded",
    })
    assert client.post(
        f"/api/v1/projects/{second['id']}/hypotheses/{excluded['id']}/verdict"
    ).status_code == 201

    result = client.post(f"/api/v1/projects/{first['id']}/verdict")

    assert result.status_code == 201
    body = result.json()
    assert [item["hypothesis_id"] for item in body["ranked_assumptions"]] == [included["id"]]
    assert body["kill_gates"] == []
    assert client.post("/api/v1/projects/999/verdict").status_code == 404


def test_verdict_endpoints_do_not_expose_hypotheses_from_another_project(client):
    first_project = client.post("/api/v1/projects", json={"name": "First idea"}).json()
    second_project = client.post("/api/v1/projects", json={"name": "Second idea"}).json()
    hypothesis = client.post(
        f"/api/v1/projects/{second_project['id']}/hypotheses",
        json={"statement": "Only the second project owns this hypothesis"},
    ).json()
    endpoint = f"/api/v1/projects/{first_project['id']}/hypotheses/{hypothesis['id']}/verdict"

    assert client.post(endpoint).status_code == 404
    assert client.get(endpoint).status_code == 404


def test_markdown_export_includes_project_data_and_escapes_unsafe_markup(client):
    project = client.post("/api/v1/projects", json={
        "name": "<script>Export</script>",
        "description": "A # risky *description*",
        "geography": "EU",
        "known_facts": ["fact <img src=x onerror=alert(1)>"],
    }).json()
    hypothesis = client.post(
        f"/api/v1/projects/{project['id']}/hypotheses",
        json={"statement": "Customers will pay for <b>this</b> product"},
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/evidence", json={
        "hypothesis_id": hypothesis["id"],
        "source_name": "<em>Customer</em>",
        "url": "https://example.test/<unsafe>",
        "content": "Evidence *with* <script>alert(1)</script>",
        "tier": "E5",
    })
    run = client.post(
        f"/api/v1/projects/{project['id']}/analysis-runs",
        json={"inputs": {"prompt": "<script>input</script>"}},
    ).json()
    assert client.post(
        f"/api/v1/projects/{project['id']}/hypotheses/{hypothesis['id']}/verdict"
    ).status_code == 201

    response = client.get(f"/api/v1/projects/{project['id']}/export/markdown")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "## Project Intake" in response.text
    assert "## Hypotheses" in response.text
    assert "## Evidence Summary" in response.text
    assert "## Latest Verdicts" in response.text
    assert "## Analysis Runs" in response.text
    assert f"### Run {run['id']}" in response.text
    assert "<script>" not in response.text
    assert "&lt;script&gt;Export&lt;/script&gt;" in response.text
    assert r"\*with\*" in response.text
    assert r"&lt;img src\=x onerror\=alert\(1\)&gt;" in response.text


def test_markdown_export_isolated_to_requested_project(client):
    first = client.post("/api/v1/projects", json={"name": "Included project"}).json()
    second = client.post("/api/v1/projects", json={"name": "Excluded project"}).json()
    first_hypothesis = client.post(
        f"/api/v1/projects/{first['id']}/hypotheses",
        json={"statement": "This hypothesis belongs to the included project"},
    ).json()
    client.post(
        f"/api/v1/projects/{first['id']}/evidence",
        json={"hypothesis_id": first_hypothesis["id"], "content": "Included evidence"},
    )
    client.post(f"/api/v1/projects/{first['id']}/analysis-runs", json={"inputs": {"owner": "first"}})

    excluded_hypothesis = client.post(
        f"/api/v1/projects/{second['id']}/hypotheses",
        json={"statement": "This hypothesis belongs to the excluded project"},
    ).json()
    client.post(
        f"/api/v1/projects/{second['id']}/evidence",
        json={"hypothesis_id": excluded_hypothesis["id"], "content": "Excluded evidence"},
    )
    client.post(f"/api/v1/projects/{second['id']}/analysis-runs", json={"inputs": {"owner": "second"}})
    assert client.post(
        f"/api/v1/projects/{second['id']}/hypotheses/{excluded_hypothesis['id']}/verdict"
    ).status_code == 201

    exported = client.get(f"/api/v1/projects/{first['id']}/export/markdown")

    assert exported.status_code == 200
    assert "Included project" in exported.text
    assert "Included evidence" in exported.text
    assert "Excluded project" not in exported.text
    assert "Excluded evidence" not in exported.text
    assert "excluded project" not in exported.text


def test_markdown_export_returns_404_for_missing_project(client):
    assert client.get("/api/v1/projects/999/export/markdown").status_code == 404
