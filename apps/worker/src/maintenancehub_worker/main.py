"""Durable job worker — lease loop (M5).

SQLite: run a **single** worker process only.
Postgres: multiple replicas safe via FOR UPDATE SKIP LOCKED.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("maintenancehub.worker")

ROOT = Path(__file__).resolve().parents[3]
API_SRC = ROOT / "api" / "src"
sys.path.insert(0, str(API_SRC))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    from sqlalchemy.orm import sessionmaker

    from maintenancehub_api.config import get_settings
    from maintenancehub_api.db import engine
    from maintenancehub_api.jobs.locking import (
        claim_jobs,
        complete_job,
        fail_job,
        worker_identity,
    )
    from maintenancehub_worker.handlers.notify import HANDLERS

    settings = get_settings()
    if settings.is_sqlite:
        logger.warning(
            "SQLite profile: run a SINGLE worker only (see docs/LIMITATIONS.md). "
            "Multi-replica lease safety requires Postgres."
        )

    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    wid = worker_identity()
    poll = float(os.environ.get("WORKER_POLL_SECONDS", "2"))
    logger.info("Worker started id=%s poll=%ss", wid, poll)

    while True:
        try:
            with Session() as db:
                # Periodically enqueue an outbox_drain job if unprocessed outbox exists
                _ensure_outbox_drain_job(db)

                jobs = claim_jobs(db, worker_id=wid, limit=5)
                if not jobs:
                    pass
                for job in jobs:
                    handler = HANDLERS.get(job.job_type)
                    try:
                        if not handler:
                            raise ValueError(f"Unknown job_type {job.job_type}")
                        result = handler(db, job.payload or {})
                        ok = complete_job(db, job, worker_id=wid)
                        if ok:
                            logger.info(
                                "Job %s type=%s succeeded result=%s",
                                job.id,
                                job.job_type,
                                result,
                            )
                        else:
                            logger.warning("Job %s lease lost before complete", job.id)
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("Job %s failed: %s", job.id, exc)
                        fail_job(db, job, worker_id=wid, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Worker loop error: %s", exc)
        time.sleep(poll)


def _ensure_outbox_drain_job(db) -> None:  # noqa: ANN001
    from sqlalchemy import select

    from maintenancehub_api.models import Job, JobStatus, OutboxEvent

    pending = (
        db.execute(
            select(OutboxEvent.id).where(OutboxEvent.processed_at.is_(None)).limit(1)
        ).first()
    )
    if not pending:
        return
    # One queued drain at a time
    existing = (
        db.execute(
            select(Job).where(
                Job.job_type == "outbox_drain",
                Job.status.in_([JobStatus.queued, JobStatus.leased]),
            )
        )
        .scalars()
        .first()
    )
    if existing:
        return
    db.add(
        Job(
            job_type="outbox_drain",
            payload={},
            idempotency_key=None,
            status=JobStatus.queued,
            run_at=datetime.now(timezone.utc),
        )
    )
    db.commit()


if __name__ == "__main__":
    main()
