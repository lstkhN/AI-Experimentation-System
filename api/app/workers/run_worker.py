"""Database-backed leasing primitives and a small analysis-run worker.

The claim uses a conditional UPDATE rather than relying solely on row locks, so
it works on both PostgreSQL and SQLite. PostgreSQL additionally benefits from
``FOR UPDATE SKIP LOCKED`` while choosing a candidate.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.db.models import AnalysisRun

DEFAULT_LEASE_SECONDS = 15 * 60
DEFAULT_RETRY_DELAY_SECONDS = 30


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _eligible(now: datetime):
    return and_(
        AnalysisRun.attempt < AnalysisRun.max_attempts,
        or_(
            and_(AnalysisRun.status == "queued", AnalysisRun.available_at <= now),
            and_(AnalysisRun.status == "running", AnalysisRun.lease_until.is_not(None), AnalysisRun.lease_until <= now),
        ),
    )


def _terminalize_expired_final_attempts(db: Session, now: datetime) -> None:
    """Atomically fail abandoned runs that cannot be claimed again."""
    changed = db.execute(update(AnalysisRun).where(
        AnalysisRun.status == "running", AnalysisRun.attempt >= AnalysisRun.max_attempts,
        AnalysisRun.lease_until.is_not(None), AnalysisRun.lease_until <= now,
    ).execution_options(synchronize_session=False).values(
        status="failed", completed_at=now, lease_until=None, lease_token=None,
        heartbeat_at=now, last_error={"code": "lease_expired"},
    )).rowcount
    if changed:
        db.commit()
        db.expire_all()


def claim_next_run(db: Session, *, lease_seconds: int = DEFAULT_LEASE_SECONDS,
                   now: datetime | None = None) -> AnalysisRun | None:
    """Atomically lease the oldest available or abandoned run.

    A losing claimant sees an UPDATE rowcount of zero and retries the next
    candidate. This is intentionally usable on SQLite, where SKIP LOCKED is
    unavailable.
    """
    now = now or utcnow()
    _terminalize_expired_final_attempts(db, now)
    for _ in range(8):
        statement = select(AnalysisRun.id).where(_eligible(now)).order_by(AnalysisRun.available_at, AnalysisRun.id).limit(1)
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        run_id = db.scalar(statement)
        if run_id is None:
            return None
        token = token_urlsafe(32)
        claimed = db.execute(
            update(AnalysisRun).where(AnalysisRun.id == run_id, _eligible(now)).execution_options(synchronize_session=False).values(
                status="running", started_at=now, attempt=AnalysisRun.attempt + 1,
                lease_token=token, lease_until=now + timedelta(seconds=lease_seconds),
                heartbeat_at=now, available_at=now,
            )
        ).rowcount
        if claimed:
            db.commit()
            db.expire_all()
            return db.get(AnalysisRun, run_id)
        db.rollback()
    return None


def claim_run(db: Session, run_id: int, *, lease_seconds: int = DEFAULT_LEASE_SECONDS,
              now: datetime | None = None) -> AnalysisRun | None:
    """Claim one particular run; used by the manual compatibility endpoint."""
    now = now or utcnow()
    _terminalize_expired_final_attempts(db, now)
    token = token_urlsafe(32)
    claimed = db.execute(
        update(AnalysisRun).where(AnalysisRun.id == run_id, _eligible(now)).execution_options(synchronize_session=False).values(
            status="running", started_at=now, attempt=AnalysisRun.attempt + 1,
            lease_token=token, lease_until=now + timedelta(seconds=lease_seconds),
            heartbeat_at=now, available_at=now,
        )
    ).rowcount
    if not claimed:
        db.rollback()
        return None
    db.commit()
    db.expire_all()
    return db.get(AnalysisRun, run_id)


def heartbeat(db: Session, run_id: int, lease_token: str, *, lease_seconds: int = DEFAULT_LEASE_SECONDS,
              now: datetime | None = None, commit: bool = True) -> bool:
    now = now or utcnow()
    if not lease_token:
        return False
    changed = db.execute(update(AnalysisRun).where(
        AnalysisRun.id == run_id, AnalysisRun.status == "running", AnalysisRun.lease_token == lease_token,
        AnalysisRun.lease_until.is_not(None), AnalysisRun.lease_until > now,
    ).execution_options(synchronize_session=False).values(heartbeat_at=now, lease_until=now + timedelta(seconds=lease_seconds))).rowcount == 1
    if commit:
        (db.commit() if changed else db.rollback())
        if changed:
            db.expire_all()
    return changed


def complete_run(db: Session, run_id: int, lease_token: str, result: dict[str, object], *,
                 now: datetime | None = None, commit: bool = True) -> bool:
    now = now or utcnow()
    if not lease_token:
        return False
    changed = db.execute(update(AnalysisRun).where(
        AnalysisRun.id == run_id, AnalysisRun.status == "running", AnalysisRun.lease_token == lease_token,
        AnalysisRun.lease_until.is_not(None), AnalysisRun.lease_until > now,
    ).execution_options(synchronize_session=False).values(status="completed", result=result, completed_at=now, lease_until=None,
             lease_token=None, heartbeat_at=now, last_error=None)).rowcount == 1
    if commit:
        (db.commit() if changed else db.rollback())
        if changed:
            db.expire_all()
    return changed


def fail_run(db: Session, run_id: int, lease_token: str, error: dict[str, object], *,
             retry_delay_seconds: int = DEFAULT_RETRY_DELAY_SECONDS, now: datetime | None = None,
             commit: bool = True, result: dict[str, object] | None = None, terminal: bool = False) -> bool:
    """Release an owned run, scheduling exponential retry unless exhausted."""
    now = now or utcnow()
    if not lease_token:
        return False
    run = db.scalar(select(AnalysisRun).where(
        AnalysisRun.id == run_id, AnalysisRun.status == "running", AnalysisRun.lease_token == lease_token,
        AnalysisRun.lease_until.is_not(None), AnalysisRun.lease_until > now,
    ))
    if run is None:
        if commit:
            db.rollback()
        return False
    exhausted = terminal or run.attempt >= run.max_attempts
    values: dict[str, object] = {"last_error": error, "lease_until": None, "lease_token": None, "heartbeat_at": now}
    if result is not None:
        values["result"] = result
    if exhausted:
        values.update(status="failed", completed_at=now)
    else:
        values.update(status="queued", available_at=now + timedelta(seconds=retry_delay_seconds * (2 ** max(run.attempt - 1, 0))))
    changed = db.execute(update(AnalysisRun).where(
        AnalysisRun.id == run_id, AnalysisRun.status == "running", AnalysisRun.lease_token == lease_token,
        AnalysisRun.lease_until.is_not(None), AnalysisRun.lease_until > now,
    ).execution_options(synchronize_session=False).values(**values)).rowcount == 1
    if commit:
        (db.commit() if changed else db.rollback())
        if changed:
            db.expire_all()
    return changed


def process_next_run(db: Session) -> AnalysisRun | None:
    """Claim and execute one run. Providers are instantiated by the service."""
    from app.services.run_execution import execute_claimed_run
    run = claim_next_run(db)
    return execute_claimed_run(db, run) if run is not None else None
