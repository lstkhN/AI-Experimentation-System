"""Small PostgreSQL-backed polling worker for local Compose deployments."""
from __future__ import annotations
import os
import time
from app.db.session import SessionLocal
from app.workers.run_worker import process_next_run


def main() -> None:
    poll_seconds = float(os.getenv("WORKER_POLL_SECONDS", "2"))
    while True:
        db = SessionLocal()
        try:
            run = process_next_run(db)
            if run is None:
                time.sleep(poll_seconds)
        except Exception:
            db.rollback()
            time.sleep(poll_seconds)
        finally:
            db.close()

if __name__ == "__main__":
    main()
