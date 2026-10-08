from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import AnalysisRun, Base, ProjectVerdict
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
        assert report["economics_models"][0]["economics_inputs"]["formula_version"] == "economics-decision-v2"
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
        assert "Formula version" in exported.text
        assert "## Structured Data Gaps" in exported.text
        assert "icp.target\\_customer\\_profile" in exported.text
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_russian_exports_hide_untranslated_evidence_and_localize_print_chrome():
    client, engine = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "Русский", "language": "ru"}).json()
        evidence = client.post(f"/api/v1/projects/{project['id']}/evidence", json={
            "content": "Raw English research content", "source_name": "Raw English source", "status": "verified",
        })
        assert evidence.status_code == 201

        markdown = client.get(f"/api/v1/projects/{project['id']}/export/markdown").text
        assert "## Сводка доказательств" in markdown
        assert "**Источник:** Источник" in markdown
        assert "**Содержание:** Содержание скрыто в RU" in markdown
        assert "Raw English research content" not in markdown
        assert "Raw English source" not in markdown

        printable = client.get(f"/api/v1/projects/{project['id']}/export/html").text
        assert '<html lang="ru">' in printable
        assert "Печать / Сохранить PDF" in printable
        assert "Отчёт по проекту" in printable

        for presentation in (markdown, printable):
            assert "профиль целевого клиента" in presentation
            assert "не собрано как структурированные данные" in presentation
            assert "Нет вручную введённых структурированных записей" in presentation
            assert "Unknown: no manually supplied structured records." not in presentation
            assert "target\\_customer\\_profile" not in presentation
            assert "not\\_collected\\_as\\_structured\\_data" not in presentation

        json_export = client.get(f"/api/v1/projects/{project['id']}/export/json").json()
        first_gap = json_export["data_gaps"][0]
        assert first_gap["field"] == "профиль целевого клиента"
        assert first_gap["reason"] == "не собрано как структурированные данные"
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_export_redacts_provider_snippets_and_unsafe_evidence_urls():
    client, engine = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "Русский", "language": "ru"}).json()
        with sessionmaker(bind=engine)() as db:
            db.add(AnalysisRun(project_id=project["id"], status="completed", result={
                "research_results": [{"snippet": "secret run snippet"}], "safe": "kept",
            }))
            db.add(ProjectVerdict(project_id=project["id"], verdict="UNPROVEN", decision="VALIDATE", result={
                "market_findings": [{"snippet": "secret market snippet"}], "decision": "VALIDATE",
            }))
            db.commit()
        evidence = client.post(f"/api/v1/projects/{project['id']}/evidence", json={
            "content": "proof", "source_name": "source", "url": "javascript:alert(1)",
        })
        assert evidence.status_code == 201
        exported = client.get(f"/api/v1/projects/{project['id']}/export/json")
        assert exported.status_code == 200
        assert "secret run snippet" not in exported.text
        assert "secret market snippet" not in exported.text
        markdown = client.get(f"/api/v1/projects/{project['id']}/export/markdown").text
        assert "javascript:alert" not in markdown
        assert "## Сводка доказательств" in markdown
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_russian_json_export_recursively_redacts_research_and_sanitizes_urls():
    client, engine = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "Русский", "language": "ru"}).json()
        with sessionmaker(bind=engine)() as db:
            db.add(AnalysisRun(project_id=project["id"], status="completed", result={
                "nested": {"research_payload": "secret research", "snippet_text": "secret snippet", "safe": "kept"},
                "links": {"unsafe_url": "javascript:alert(1)", "good_url": "https://example.test/proof"},
            }))
            db.commit()
        report = client.get(f"/api/v1/projects/{project['id']}/export/json").json()
        encoded = str(report)
        assert "secret research" not in encoded
        assert "secret snippet" not in encoded
        nested = report["analysis_runs"][0]["result"]["nested"]
        assert nested == {"safe": "kept"}
        assert report["analysis_runs"][0]["result"]["links"] == {
            "unsafe_url": None, "good_url": "https://example.test/proof",
        }
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_russian_markdown_export_localizes_catalogued_entity_headings_and_labels():
    client, engine = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "Русский", "language": "ru"}).json()
        hypothesis = client.post(f"/api/v1/projects/{project['id']}/hypotheses", json={
            "statement": "Проверить спрос", "category": "demand", "importance": 1,
        }).json()
        client.post(f"/api/v1/projects/{project['id']}/experiments/propose", json={
            "template_key": "landing_page_v1", "hypothesis_id": hypothesis["id"], "rationale": "test",
        })
        with sessionmaker(bind=engine)() as db:
            db.add(AnalysisRun(project_id=project["id"], status="completed", result={}))
            db.add(ProjectVerdict(project_id=project["id"], verdict="UNPROVEN", decision="VALIDATE", result={
                "market_attractiveness": {"status": "unknown"}, "business_viability": {"status": "unknown"},
            }))
            db.commit()
        markdown = client.get(f"/api/v1/projects/{project['id']}/export/markdown").text
        for label in ("### Гипотеза ", "### Эксперимент ", "### Запуск ", "**Правила:**",
                      "### Привлекательность рынка", "### Жизнеспособность бизнеса"):
            assert label in markdown
        assert "### Hypothesis " not in markdown
        assert "### Experiment " not in markdown
        assert "### Run " not in markdown
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_russian_exports_localize_manual_record_json_keys():
    client, engine = _client()
    try:
        project = client.post("/api/v1/projects", json={"name": "Русский", "language": "ru"}).json()
        created = client.post(f"/api/v1/projects/{project['id']}/market-entities", json={
            "name": "Рынок", "entity_type": "segment", "claim": "Ручная запись", "source_reference": "Интервью",
        })
        assert created.status_code == 201

        for presentation in (
            client.get(f"/api/v1/projects/{project['id']}/export/markdown").text,
            client.get(f"/api/v1/projects/{project['id']}/export/html").text,
        ):
            assert "Тип сущности" in presentation
            assert "Ссылка на источник" in presentation
            assert "entity\\_type" not in presentation
            assert "source\\_reference" not in presentation
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
