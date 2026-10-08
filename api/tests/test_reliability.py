from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import AnalysisRun, AuditEvent, Base, Project, Verdict
from app.db.session import get_db
from app.main import app
from app.services.research import ResearchResult
from app.services.run_execution import execute_claimed_run
from app.settings import AnalysisSettings
from app.workers.run_worker import claim_run


def test_analysis_settings_are_typed_and_read_from_environment(monkeypatch):
    monkeypatch.setenv("ANALYSIS_COST_CAP_USD", "1.25")
    monkeypatch.setenv("ANALYSIS_MAX_RESEARCH_CALLS", "3")
    settings = AnalysisSettings.from_env()
    assert settings.cost_cap_usd == Decimal("1.25")
    assert settings.max_research_calls == 3


def test_cost_cap_persists_usage_and_audit_record():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    project = Project(name="Cost limited")
    db.add(project)
    db.flush()
    run = AnalysisRun(project_id=project.id, status="queued")
    db.add(run)
    db.commit()
    claimed = claim_run(db, run.id)

    class Research:
        is_configured = True
        def search(self, _query):
            return [ResearchResult("Source", "https://example.test", "text")]

    class LLM:
        is_configured = True
        last_usage = {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200, "cost_usd": 1.0}
        def generate_hypotheses(self, _context, _research):
            return [{"statement": "Will not be saved"}]

    result = execute_claimed_run(
        db, claimed, research_provider=Research(), orchestrator=LLM(),
        settings=AnalysisSettings(cost_cap_usd=Decimal("0.50"), max_research_calls=1, max_tool_calls=2),
    )
    assert result.status == "failed"
    assert result.result["usage"]["research_calls"] == 1
    assert result.result["cost_usd"] == 1.0
    event = db.scalar(select(AuditEvent).where(AuditEvent.entity_id == run.id))
    assert event.payload["error_code"] == "analysis_limit_exceeded"
    assert event.payload["usage"]["tool_calls"] == 2
    db.close()
    engine.dispose()


def test_starter_run_persists_unproven_verdicts_instead_of_inventing_evidence():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    project = Project(name="No evidence")
    db.add(project)
    db.flush()
    run = AnalysisRun(project_id=project.id, status="queued")
    db.add(run)
    db.commit()
    claimed = claim_run(db, run.id)

    class Provider:
        is_configured = False

    class LLM:
        is_configured = False
        last_usage = {}

    completed = execute_claimed_run(db, claimed, research_provider=Provider(), orchestrator=LLM())
    assert completed.status == "completed"
    assert completed.result["verdicts"]
    assert {item["verdict"] for item in completed.result["verdicts"]} == {"UNPROVEN"}
    assert {item.verdict for item in db.scalars(select(Verdict)).all()} == {"UNPROVEN"}
    db.close()
    engine.dispose()


def test_health_is_liveness_and_ready_checks_migration(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('test-revision')"))

    def override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr("app.main._alembic_head_revision", lambda: "test-revision")
    try:
        with TestClient(app) as client:
            assert client.get("/health").json()["status"] == "ok"
            ready = client.get("/ready")
            assert ready.status_code == 200
            assert ready.json()["revision"] == "test-revision"
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
