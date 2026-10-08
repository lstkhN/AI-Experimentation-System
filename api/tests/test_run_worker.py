from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import AnalysisRun, Base, Project
from app.workers.run_worker import claim_next_run, complete_run, fail_run, heartbeat


def test_claim_lease_heartbeat_and_conditional_completion():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    project = Project(name="run worker")
    db.add(project)
    db.flush()
    db.add(AnalysisRun(project_id=project.id, status="queued", queued_at=now, available_at=now))
    db.commit()

    run = claim_next_run(db, now=now, lease_seconds=60)
    assert run is not None and run.status == "running" and run.attempt == 1
    assert run.lease_token
    assert heartbeat(db, run.id, "wrong", now=now) is False
    assert heartbeat(db, run.id, run.lease_token, now=now + timedelta(seconds=1)) is True
    assert complete_run(db, run.id, "wrong", {"mode": "starter"}, now=now) is False
    assert complete_run(db, run.id, run.lease_token, {"mode": "starter"}, now=now) is True
    assert db.get(AnalysisRun, run.id).status == "completed"
    db.close()
    engine.dispose()


def test_expired_lease_is_reclaimed_and_failure_uses_backoff_and_max_attempts():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    project = Project(name="retry")
    db.add(project)
    db.flush()
    db.add(AnalysisRun(project_id=project.id, status="running", attempt=1, max_attempts=2,
                       queued_at=now, available_at=now, lease_token="abandoned", lease_until=now - timedelta(seconds=1)))
    db.commit()

    run = claim_next_run(db, now=now)
    assert run is not None and run.attempt == 2 and run.lease_token != "abandoned"
    assert fail_run(db, run.id, run.lease_token, {"code": "boom"}, now=now) is True
    assert db.get(AnalysisRun, run.id).status == "failed"

    # A non-final failure returns to queued and is unavailable until backoff expires.
    second = AnalysisRun(project_id=project.id, status="queued", queued_at=now, available_at=now, max_attempts=3)
    db.add(second)
    db.commit()
    claimed = claim_next_run(db, now=now)
    assert claimed is not None and claimed.id == second.id
    assert fail_run(db, claimed.id, claimed.lease_token, {"code": "transient"}, retry_delay_seconds=10, now=now)
    db.refresh(second)
    assert second.status == "queued"
    assert second.available_at.replace(tzinfo=timezone.utc) == now + timedelta(seconds=10)
    assert claim_next_run(db, now=now + timedelta(seconds=9)) is None
    assert claim_next_run(db, now=now + timedelta(seconds=10)).id == second.id
    db.close()
    engine.dispose()
