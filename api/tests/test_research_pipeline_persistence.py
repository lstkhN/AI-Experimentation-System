from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import warnings

import pytest

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.candidates import CandidateCreate, CandidatePromotion, create, promote
from app.db.models import AnalysisRun, Base, Evidence, EvidenceCandidate, EvidenceLink, EvidenceSource, Hypothesis, Project, ResearchClaim, ResearchDocument, ResearchStageRun, ResearchVerification
from app.services.project_report_snapshot import save_project_report_snapshot
from app.services.research import ResearchResult
from app.services.research_pipeline.orchestration import ResearchLeaseLost, provider_search, run_research_pipeline


class Provider:
    def __init__(self, results=None):
        self.calls = 0
        self.results = results if results is not None else [{"title": "Source", "url": "https://example.test/a", "content": "A durable claim", "source_metadata": {"source_quality": .8, "methodology_available": True}}]

    def search(self, query, *, max_results=5):
        self.calls += 1
        assert max_results == 10
        return self.results

    def fetch(self, url):
        return f"fetched: {url}"


class LegacyProvider:
    def search(self, query):
        return []


def _run(db):
    project = Project(name="P")
    db.add(project); db.flush()
    run = AnalysisRun(project_id=project.id)
    db.add(run); db.commit()
    return run.id


def test_pipeline_persists_checkpoints_and_resumes_after_reopen(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'research.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run_id = _run(db)
        provider = Provider()
        run_research_pipeline(db, db.get(AnalysisRun, run_id), provider, "query")
    with Session(engine) as db:
        assert {row.stage for row in db.scalars(select(ResearchStageRun)).all()} == {"search", "fetch", "extract", "claims", "verify", "cluster"}
        assert db.scalar(select(ResearchClaim)).source_cluster == "example.test"
        assert db.scalar(select(ResearchDocument)).content == "fetched: https://example.test/a"
        assert db.scalar(select(ResearchVerification)).status == "verified"
        run_research_pipeline(db, db.get(AnalysisRun, run_id), provider, "query")
        assert provider.calls == 1


def test_failed_stage_is_committed_and_resumes(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'failure.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run_id = _run(db)
        failing = Provider()
        failing.search = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline"))
        try:
            run_research_pipeline(db, db.get(AnalysisRun, run_id), failing, "query")
        except RuntimeError:
            pass
    with Session(engine) as db:
        failed = db.scalar(select(ResearchStageRun).where(ResearchStageRun.stage == "search"))
        assert failed.status == "failed" and failed.error["type"] == "RuntimeError"
        run_research_pipeline(db, db.get(AnalysisRun, run_id), Provider(), "query")
        assert db.scalar(select(ResearchStageRun).where(ResearchStageRun.stage == "search")).status == "completed"


def test_duplicate_provider_urls_are_deduplicated_before_persistence():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run_id = _run(db)
        result = {"title": "Source", "url": "https://example.test/duplicate", "content": "claim"}
        run_research_pipeline(db, db.get(AnalysisRun, run_id), Provider(results=[result, result]), "query")
        assert len(db.scalars(select(ResearchDocument)).all()) == 1


def test_pipeline_normalizes_nested_provider_metadata_before_persistence():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    metadata = {"retrieved": datetime(2025, 1, 1, tzinfo=timezone.utc),
                "nested": {"events": [datetime(2025, 1, 2), {"at": datetime(2025, 1, 3, tzinfo=timezone.utc)}]}}
    with Session(engine) as db:
        run_id = _run(db)
        run_research_pipeline(db, db.get(AnalysisRun, run_id), Provider(results=[{
            "title": "Source", "url": "https://example.test/metadata", "content": "claim", "source_metadata": metadata,
        }]), "query")
        assert db.scalar(select(ResearchDocument)).source_metadata == {
            "retrieved": "2025-01-01T00:00:00+00:00",
            "nested": {"events": ["2025-01-02T00:00:00", {"at": "2025-01-03T00:00:00+00:00"}]},
        }


def test_empty_completed_search_is_not_retried_and_provider_keyword_is_compatible():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run_id = _run(db)
        provider = Provider(results=[])
        assert run_research_pipeline(db, db.get(AnalysisRun, run_id), provider, "query") == []
        run_research_pipeline(db, db.get(AnalysisRun, run_id), provider, "query")
        assert provider.calls == 1
    assert provider_search(LegacyProvider(), "query", max_results=10) == []


def test_classified_promotion_is_idempotent_on_repeated_requests():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="P")
        db.add(project); db.flush()
        candidate = EvidenceCandidate(project_id=project.id, claim="claim", source_name="source", status="verified")
        db.add(candidate); db.commit()
        decision = CandidatePromotion(verification_reason="reviewed", direction="supporting", tier="E2", category="demand")
        first = promote(project.id, candidate.id, decision, db)
        second = promote(project.id, candidate.id, decision, db)
        assert first.id == second.id
        assert db.scalars(select(Evidence)).all()[0].category == "demand"


def test_promotion_derives_link_relation_from_contradicting_direction():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="P")
        hypothesis = Hypothesis(project=project, statement="Demand exists")
        db.add(hypothesis); db.flush()
        candidate = EvidenceCandidate(project_id=project.id, hypothesis_id=hypothesis.id, claim="claim", source_name="source", status="verified")
        db.add(candidate); db.commit()
        promote(project.id, candidate.id, CandidatePromotion(
            verification_reason="reviewed", direction="contradicting", tier="E2", category="demand"
        ), db)
        assert db.scalar(select(EvidenceLink)).relation == "contradicting"


def test_candidate_create_derives_source_cluster_from_canonical_url_even_when_overridden():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="P")
        db.add(project); db.commit()
        candidate = create(project.id, CandidateCreate(
            claim="claim", source_name="source", url="HTTPS://WWW.Example.Test/report?utm_source=newsletter#part",
            source_cluster="caller-override",
        ), db)
        assert candidate.source_cluster == "example.test"


def test_pipeline_fetches_and_persists_content_and_failure():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run_id = _run(db)
        provider = Provider()
        fetched_urls = []
        provider.fetch = lambda url: fetched_urls.append(url) or "retrieved page"
        run_research_pipeline(db, db.get(AnalysisRun, run_id), provider, "query")
        document = db.scalar(select(ResearchDocument))
        assert fetched_urls == ["https://example.test/a"]
        assert document.content == "retrieved page"
        assert document.fetched_at is not None

        failed_run_id = _run(db)
        failing = Provider()
        failing.fetch = lambda url: (_ for _ in ()).throw(RuntimeError("fetch offline"))
        with pytest.raises(RuntimeError, match="fetch offline"):
            run_research_pipeline(db, db.get(AnalysisRun, failed_run_id), failing, "query")
        failed = db.scalar(select(ResearchStageRun).where(
            ResearchStageRun.analysis_run_id == failed_run_id, ResearchStageRun.stage == "fetch"
        ))
        assert failed.status == "failed"
        assert failed.error == {"type": "RuntimeError", "message": "fetch offline"}


def test_candidate_promotion_uses_canonical_url_cluster_over_stored_override():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="P")
        db.add(project); db.flush()
        candidate = EvidenceCandidate(
            project_id=project.id, claim="claim", source_name="source",
            url="HTTPS://WWW.Example.Test/report?utm_source=newsletter#part",
            source_cluster="caller-override", status="verified",
        )
        db.add(candidate); db.commit()
        evidence = promote(project.id, candidate.id, CandidatePromotion(
            verification_reason="reviewed", direction="supporting", tier="E2", category="demand",
        ), db)
        assert evidence.source_cluster == "example.test"


def test_candidate_promotion_rejects_unrecognized_direction_or_tier():
    with pytest.raises(ValueError):
        CandidatePromotion(verification_reason="reviewed", direction="neutral", tier="E2", category="demand")
    with pytest.raises(ValueError):
        CandidatePromotion(verification_reason="reviewed", direction="supporting", tier="E0", category="demand")


def test_promotions_reuse_one_source_for_the_same_url():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="P")
        db.add(project); db.flush()
        candidates = [EvidenceCandidate(project_id=project.id, claim=f"claim {index}", source_name="source",
                                        url="https://example.test/source", status="verified") for index in range(2)]
        db.add_all(candidates); db.commit()
        decision = CandidatePromotion(verification_reason="reviewed", direction="supporting", tier="E2", category="demand")
        for candidate in candidates:
            promote(project.id, candidate.id, decision, db)
        assert len(db.scalars(select(EvidenceSource).where(EvidenceSource.project_id == project.id)).all()) == 1


def test_promotion_canonicalizes_urls_for_source_identity_and_persistence():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="P")
        db.add(project); db.flush()
        candidates = [EvidenceCandidate(project_id=project.id, claim=f"claim {index}", source_name="source",
                                        url=url, status="verified") for index, url in enumerate((
            "HTTPS://Example.Test/source/?utm_source=newsletter#section",
            "https://example.test/source",
        ))]
        db.add_all(candidates); db.commit()
        decision = CandidatePromotion(verification_reason="reviewed", direction="supporting", tier="E2", category="demand")
        for candidate in candidates:
            promote(project.id, candidate.id, decision, db)
        source = db.scalar(select(EvidenceSource).where(EvidenceSource.project_id == project.id))
        assert source.url == "https://example.test/source"
        assert len(db.scalars(select(EvidenceSource).where(EvidenceSource.project_id == project.id)).all()) == 1


def test_promotion_reuses_legacy_source_by_canonical_url():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="P")
        db.add(project); db.flush()
        legacy_source = EvidenceSource(
            project_id=project.id, identity_key="legacy:1", name="legacy source",
            url="HTTPS://Example.Test/source/?utm_source=newsletter#section", source_type="research",
        )
        candidate = EvidenceCandidate(
            project_id=project.id, claim="claim", source_name="source",
            url="https://example.test/source", status="verified",
        )
        db.add_all([legacy_source, candidate]); db.commit()

        decision = CandidatePromotion(verification_reason="reviewed", direction="supporting", tier="E2", category="demand")
        evidence = promote(project.id, candidate.id, decision, db)

        assert evidence.source_id == legacy_source.id
        assert len(db.scalars(select(EvidenceSource).where(EvidenceSource.project_id == project.id)).all()) == 1


def test_classified_promotion_is_idempotent_across_sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'promotion.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        project = Project(name="P")
        db.add(project); db.flush()
        candidate = EvidenceCandidate(project_id=project.id, claim="claim", source_name="source", status="verified")
        db.add(candidate); db.commit()
        project_id, candidate_id = project.id, candidate.id
    decision = CandidatePromotion(verification_reason="reviewed", direction="supporting", tier="E2", category="demand")
    # Separate sessions model independent requests; the database unique link
    # ensures both requests resolve to one evidence record.
    with sessions() as first_db:
        first_id = promote(project_id, candidate_id, decision, first_db).id
    with sessions() as second_db:
        assert promote(project_id, candidate_id, decision, second_db).id == first_id
        assert len(second_db.scalars(select(Evidence).where(Evidence.candidate_id == candidate_id)).all()) == 1


def test_research_result_serializes_datetime_for_json_persistence():
    result = ResearchResult(title="Source", url="https://example.test", content="claim",
                            fetched_at=datetime(2025, 1, 2, tzinfo=timezone.utc))
    assert result.to_dict()["fetched_at"] == "2025-01-02T00:00:00+00:00"


def test_report_snapshot_uses_persisted_documents_before_legacy_run_result():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run_id = _run(db)
        run = db.get(AnalysisRun, run_id)
        run.result = {"research_results": [{"url": "https://legacy.test", "content": "legacy"}]}
        stage = ResearchStageRun(analysis_run_id=run_id, stage="search", status="completed")
        db.add(stage); db.flush()
        db.add(ResearchDocument(project_id=run.project_id, analysis_run_id=run_id, stage_run_id=stage.id,
                                title="Durable", url="https://durable.test", content="durable"))
        snapshot = save_project_report_snapshot(db, db.get(Project, run.project_id), analysis_run=run)
        assert snapshot.provenance_snapshot["research"][0]["url"] == "https://durable.test"
        assert snapshot.provenance_snapshot["research"][0]["stage"] == "search"


def test_pipeline_requires_lease_token_for_running_run():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run_id = _run(db)
        run = db.get(AnalysisRun, run_id)
        run.status, run.lease_token = "running", "owner"
        run.lease_until = datetime.now(timezone.utc) + timedelta(minutes=1)
        db.commit()
        with pytest.raises(ResearchLeaseLost):
            run_research_pipeline(db, db.get(AnalysisRun, run_id), Provider(), "query")
        assert db.scalars(select(ResearchStageRun).where(ResearchStageRun.analysis_run_id == run_id)).all() == []


def test_pipeline_refuses_stale_lease_before_creating_artifacts():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run_id = _run(db)
        run = db.get(AnalysisRun, run_id)
        run.status, run.lease_token = "running", "owner"
        run.lease_until = datetime.now(timezone.utc).replace(year=2020)
        db.commit()
        with pytest.raises(ResearchLeaseLost):
            run_research_pipeline(db, db.get(AnalysisRun, run_id), Provider(), "query", lease_token="owner")
        assert db.scalars(select(ResearchStageRun).where(ResearchStageRun.analysis_run_id == run_id)).all() == []


def test_evidence_candidate_schema_has_no_fk_sort_cycle():
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        Base.metadata.sorted_tables
    assert not any("unresolvable cycles" in str(warning.message) for warning in captured)


def test_migration_removes_populated_candidate_promotion_cycle_with_sqlite_foreign_keys(tmp_path, monkeypatch):
    # env.py prioritizes DATABASE_URL over Config, so explicitly remove it.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    root = Path(__file__).resolve().parents[2]
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20250325_0020")

    engine = create_engine(database_url)
    with Session(engine) as db:
        project = Project(name="migration project")
        db.add(project); db.flush()
        candidate = EvidenceCandidate(project_id=project.id, claim="promoted claim", source_name="source")
        source = EvidenceSource(
            project_id=project.id, identity_key="migration-source", name="source",
            source_metadata={"provider": "legacy-import", "confidence": 0.8},
        )
        db.add_all((candidate, source)); db.flush()
        # This is a valid legacy reverse-only mapping: 0021 must make it
        # canonical rather than lose it when promoted_evidence_id is dropped.
        evidence = Evidence(source_id=source.id, content="promoted claim")
        db.add(evidence); db.flush()
        db.execute(
            text("UPDATE evidence_candidates SET promoted_evidence_id = :evidence_id WHERE id = :candidate_id"),
            {"evidence_id": evidence.id, "candidate_id": candidate.id},
        )
        candidate_id, evidence_id, source_id = candidate.id, evidence.id, source.id
        db.commit()

    spec = importlib.util.spec_from_file_location(
        "candidate_cycle_migration", root / "api/alembic/versions/20250326_0021_remove_candidate_promotion_cycle.py"
    )
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert connection.exec_driver_sql("SELECT candidate_id FROM evidence WHERE id = ?", (evidence_id,)).scalar() == candidate_id
        assert connection.exec_driver_sql("SELECT id FROM evidence_candidates WHERE id = ?", (candidate_id,)).scalar() == candidate_id
        assert connection.exec_driver_sql("SELECT content FROM evidence WHERE id = ?", (evidence_id,)).scalar() == "promoted claim"
        assert connection.exec_driver_sql(
            "SELECT source_metadata FROM evidence_sources WHERE id = ?", (source_id,)
        ).scalar() == '{"provider": "legacy-import", "confidence": 0.8}'
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert any(row[2] == "evidence_candidates" for row in connection.exec_driver_sql("PRAGMA foreign_key_list(evidence)"))
        assert not any(row[2] == "evidence" for row in connection.exec_driver_sql("PRAGMA foreign_key_list(evidence_candidates)"))

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert connection.exec_driver_sql(
            "SELECT promoted_evidence_id FROM evidence_candidates WHERE id = ?", (candidate_id,)
        ).scalar() == evidence_id
        assert connection.exec_driver_sql("SELECT candidate_id FROM evidence WHERE id = ?", (evidence_id,)).scalar() == candidate_id
        assert connection.exec_driver_sql("SELECT content FROM evidence WHERE id = ?", (evidence_id,)).scalar() == "promoted claim"
        assert connection.exec_driver_sql(
            "SELECT source_metadata FROM evidence_sources WHERE id = ?", (source_id,)
        ).scalar() == '{"provider": "legacy-import", "confidence": 0.8}'
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert any(row[2] == "evidence_candidates" for row in connection.exec_driver_sql("PRAGMA foreign_key_list(evidence)"))
        assert any(row[2] == "evidence" for row in connection.exec_driver_sql("PRAGMA foreign_key_list(evidence_candidates)"))


def test_migration_rejects_contradictory_candidate_promotion_mappings_with_sqlite_foreign_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    root = Path(__file__).resolve().parents[2]
    database_url = f"sqlite:///{tmp_path / 'migration-conflict.db'}"
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20250325_0020")

    engine = create_engine(database_url)
    with Session(engine) as db:
        project = Project(name="migration project")
        db.add(project); db.flush()
        source = EvidenceSource(project=project, identity_key="migration-source", name="source")
        legacy_candidate = EvidenceCandidate(project_id=project.id, claim="legacy", source_name="source")
        canonical_candidate = EvidenceCandidate(project_id=project.id, claim="canonical", source_name="source")
        db.add_all((source, legacy_candidate, canonical_candidate)); db.flush()
        evidence = Evidence(source_id=source.id, candidate_id=canonical_candidate.id, content="promoted claim")
        db.add(evidence); db.flush()
        db.execute(
            text("UPDATE evidence_candidates SET promoted_evidence_id = :evidence_id WHERE id = :candidate_id"),
            {"evidence_id": evidence.id, "candidate_id": legacy_candidate.id},
        )
        evidence_id = evidence.id
        canonical_candidate_id = canonical_candidate.id
        db.commit()

    spec = importlib.util.spec_from_file_location(
        "candidate_cycle_migration_conflict", root / "api/alembic/versions/20250326_0021_remove_candidate_promotion_cycle.py"
    )
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="contradictory promotion mapping.*legacy candidate"):
                migration.upgrade()
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert connection.exec_driver_sql(
            "SELECT candidate_id FROM evidence WHERE id = ?", (evidence_id,)
        ).scalar() == canonical_candidate_id
