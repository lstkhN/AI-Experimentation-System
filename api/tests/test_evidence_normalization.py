from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Evidence, EvidenceLink, EvidenceSource, Hypothesis, Project
from app.services.evidence_normalization import normalize_research_results
from app.services.research import ResearchResult


def test_normalization_deduplicates_urls_and_clusters_and_keeps_provenance():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    project = Project(name="Research")
    hypothesis = Hypothesis(project=project, statement="Demand exists")
    session.add(hypothesis)
    session.commit()

    results = [
        ResearchResult("Report", "https://www.example.com/report?utm_source=search", "Demand is growing", 0.9),
        ResearchResult("Report duplicate", "https://www.example.com/report", "Same report", 0.8),
        ResearchResult("Second page", "https://example.com/other", "More data", 0.7),
        ResearchResult("Bad", "not-a-url", "Ignored"),
    ]
    summary = normalize_research_results(session, project=project, hypothesis=hypothesis, results=results)
    session.commit()

    assert summary.sources_created == 2
    assert summary.evidence_created == 1
    assert summary.results_skipped == 1
    sources = list(session.scalars(select(EvidenceSource)))
    assert len(sources) == 2
    report = next(source for source in sources if source.url.endswith("/report"))
    assert len(report.source_metadata["research_results"]) == 2
    evidence = session.scalar(select(Evidence))
    assert evidence.source_cluster == "example.com"
    assert evidence.direction == "neutral"
    assert evidence.tier == "E0"
    assert session.scalar(select(EvidenceLink)).relation == "unknown"
    assert session.scalar(select(EvidenceLink)).hypothesis_id == hypothesis.id

    repeated = normalize_research_results(session, project=project, hypothesis=hypothesis, results=results)
    session.commit()
    assert repeated.sources_created == 0
    assert repeated.evidence_created == 0
    assert repeated.evidence_reused == 1
    assert len(list(session.scalars(select(Evidence)))) == 1
    session.close()
    Base.metadata.drop_all(engine)


def test_normalization_retains_bounded_provenance_for_unreviewed_snippets():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        project = Project(name="Research")
        hypothesis = Hypothesis(project=project, statement="Teams will pay")
        session.add(hypothesis)
        session.commit()

        original = "x" * 4_001
        result = ResearchResult(
            "Unreviewed result",
            "https://example.test/report?utm_source=search",
            original,
            fetched_at=datetime(2025, 2, 20, 10, 0),
            source_metadata={"provider": "fixture", "collection": "search", "nested": {"at": datetime(2025, 2, 20, 11, 0)}},
        )
        normalize_research_results(session, project=project, hypothesis=hypothesis, results=[result])
        session.commit()

        source = session.scalar(select(EvidenceSource))
        provenance = source.source_metadata["research_results"][0]
        assert provenance["fetched_at"] == "2025-02-20T10:00:00+00:00"
        assert provenance["source_metadata"] == {
            "provider": "fixture", "collection": "search", "nested": {"at": "2025-02-20T11:00:00"}
        }
        assert provenance["url"] == "https://example.test/report"
        assert provenance["content_truncated"] is True
        assert provenance["original_content_length"] == len(original)
        assert len(provenance["content"]) == 4_000
        assert provenance["classification"] == {
            "direction": "neutral", "tier": "E0", "relation": "unknown", "reason": "unreviewed_search_snippet"
        }
        evidence = session.scalar(select(Evidence))
        assert (evidence.direction, evidence.tier, evidence.relevance) == ("neutral", "E0", 0.0)
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_normalization_uses_canonical_url_identity_for_duplicate_results():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        project = Project(name="Research")
        hypothesis = Hypothesis(project=project, statement="Teams will pay")
        session.add(hypothesis)
        session.commit()

        result = ResearchResult("Report", "https://example.test/report?utm_source=first", "claim")
        normalize_research_results(session, project=project, hypothesis=hypothesis, results=[result])
        session.commit()
        source = session.scalar(select(EvidenceSource))
        first_identity = source.identity_key

        duplicate = ResearchResult("Report", "https://example.test/report?utm_source=second", "claim")
        summary = normalize_research_results(session, project=project, hypothesis=hypothesis, results=[duplicate])
        session.commit()
        sources = list(session.scalars(select(EvidenceSource)))
        assert summary.sources_created == 0
        assert len(sources) == 1
        assert sources[0].identity_key == first_identity
    finally:
        session.close()
        Base.metadata.drop_all(engine)
