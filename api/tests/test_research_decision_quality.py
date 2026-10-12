from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import (AnalysisRun, Base, Project, ResearchClaimContradiction,
                           ResearchStageRun, ResearchVerificationAttempt)
from app.services.project_report_snapshot import save_project_report_snapshot
from app.services.research_pipeline.orchestration import run_research_pipeline
from app.services.research_pipeline.verify import contradicts, verify_claim


class Provider:
    def search(self, query, *, max_results=10):
        return [
            {"title": "A", "url": "https://a.test/report", "content": "", "source_metadata": {"source_quality": .9, "methodology_available": True}},
            {"title": "B", "url": "https://b.test/report", "content": "", "source_metadata": {"source_quality": .9, "methodology_available": True}},
        ]

    def fetch(self, url):
        return "Demand exists" if "a.test" in url else "Demand does not exist"


def test_verification_records_freshness_independence_contradictions_and_report_provenance():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="P")
        db.add(project); db.flush()
        run = AnalysisRun(project_id=project.id)
        db.add(run); db.commit()
        run_research_pipeline(db, run, Provider(), "demand")

        attempts = list(db.scalars(select(ResearchVerificationAttempt)))
        assert len(attempts) == 2
        assert all(item.freshness_score > .99 for item in attempts)
        assert all(item.provenance["source_cluster"] in {"a.test", "b.test"} for item in attempts)
        assert len(db.scalars(select(ResearchClaimContradiction))) == 1
        cluster_stage = db.scalar(select(ResearchStageRun).where(ResearchStageRun.analysis_run_id == run.id,
                                                                  ResearchStageRun.stage == "cluster"))
        assert cluster_stage.output["contradictions"]
        report = save_project_report_snapshot(db, project, analysis_run=run)
        assert report.provenance_snapshot["research"][0]["claims"][0]["verification"]["provenance"]


def test_verification_policy_is_freshness_and_cluster_aware_without_breaking_status_contract():
    stale = datetime.now(timezone.utc) - timedelta(days=730)
    result = verify_claim({"claim": "x"}, methodology_available=True, source_quality=.8,
                          fetched_at=stale, source_cluster="publisher", independent_clusters=2)
    assert result["status"] == "verified"
    assert result["freshness_score"] < .3
    assert result["independence_score"] == 1
    assert contradicts("Demand exists", "Demand does not exist")
