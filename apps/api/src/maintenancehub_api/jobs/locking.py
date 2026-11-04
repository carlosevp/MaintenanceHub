"""DB-backed job lease claiming (ADR-001).

Postgres: SELECT … FOR UPDATE SKIP LOCKED then UPDATE lease columns.
SQLite: atomic UPDATE … WHERE status=queued (or expired lease); document single worker.
"""

from __future__ import annotations

import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.orm import Session

from maintenancehub_api.config import get_settings
from maintenancehub_api.models import Job, JobStatus

logger = logging.getLogger("maintenancehub.jobs")


def worker_identity() -> str:
    settings = get_settings()
    if settings.worker_id:
        return settings.worker_id
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def claim_jobs(
    db: Session,
    *,
    worker_id: str,
    limit: int = 5,
    job_types: list[str] | None = None,
) -> list[Job]:
    """Claim up to `limit` runnable jobs for this worker."""
    settings = get_settings()
    lease_secs = settings.job_lease_seconds
    now = _now()
    expires = now + timedelta(seconds=lease_secs)

    if settings.is_postgres:
        return _claim_postgres(db, worker_id=worker_id, limit=limit, now=now, expires=expires, job_types=job_types)
    return _claim_sqlite(db, worker_id=worker_id, limit=limit, now=now, expires=expires, job_types=job_types)


def _claim_sqlite(
    db: Session,
    *,
    worker_id: str,
    limit: int,
    now: datetime,
    expires: datetime,
    job_types: list[str] | None,
) -> list[Job]:
    """Claim via conditional UPDATE — safe with a single SQLite writer/worker."""
    claimed: list[Job] = []
    q = (
        select(Job)
        .where(
            or_(
                and_(Job.status == JobStatus.queued, Job.run_at <= now),
                and_(
                    Job.status == JobStatus.leased,
                    Job.lease_expires_at.is_not(None),
                    Job.lease_expires_at < now,
                ),
                and_(Job.status == JobStatus.failed, Job.run_at <= now),
            )
        )
        .order_by(Job.run_at.asc())
        .limit(limit * 3)
    )
    if job_types:
        q = q.where(Job.job_type.in_(job_types))

    candidates = list(db.execute(q).scalars().all())
    for job in candidates:
        if len(claimed) >= limit:
            break
        # Compare in Python (SQLite often returns naive datetimes)
        lease_exp = job.lease_expires_at
        if lease_exp is not None and lease_exp.tzinfo is None:
            lease_exp = lease_exp.replace(tzinfo=timezone.utc)
        run_at = job.run_at
        if run_at is not None and run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=timezone.utc)

        eligible = False
        if job.status == JobStatus.queued and run_at is not None and run_at <= now:
            eligible = True
        elif (
            job.status == JobStatus.leased
            and lease_exp is not None
            and lease_exp < now
        ):
            eligible = True
        elif job.status == JobStatus.failed and run_at is not None and run_at <= now:
            eligible = True
        if not eligible:
            continue

        result = db.execute(
            update(Job)
            .where(Job.id == job.id, Job.status == job.status)
            .values(
                status=JobStatus.leased,
                leased_by=worker_id,
                lease_expires_at=expires,
                attempt_count=(job.attempt_count or 0) + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            db.flush()
            refreshed = db.get(Job, job.id)
            if refreshed:
                claimed.append(refreshed)
    db.commit()
    for j in claimed:
        db.refresh(j)
    return claimed


def _claim_postgres(
    db: Session,
    *,
    worker_id: str,
    limit: int,
    now: datetime,
    expires: datetime,
    job_types: list[str] | None,
) -> list[Job]:
    type_clause = ""
    params: dict = {"now": now, "limit": limit}
    if job_types:
        type_clause = "AND job_type = ANY(:types)"
        params["types"] = job_types

    # Lock candidate rows with SKIP LOCKED
    sql = text(
        f"""
        SELECT id FROM jobs
        WHERE (
            (status = 'queued' AND run_at <= :now)
            OR (status = 'leased' AND lease_expires_at IS NOT NULL AND lease_expires_at < :now)
            OR (status = 'failed' AND run_at <= :now)
        )
        {type_clause}
        ORDER BY run_at ASC
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
        """
    )
    rows = db.execute(sql, params).fetchall()
    ids = [r[0] for r in rows]
    if not ids:
        return []

    db.execute(
        text(
            "UPDATE jobs SET status='leased', leased_by=:wid, lease_expires_at=:exp, "
            "attempt_count = attempt_count + 1 WHERE id = ANY(:ids)"
        ),
        {"wid": worker_id, "exp": expires, "ids": ids},
    )
    db.commit()
    return list(db.execute(select(Job).where(Job.id.in_(ids))).scalars().all())


def complete_job(db: Session, job: Job, *, worker_id: str) -> bool:
    """Mark succeeded only if still leased by this worker. Returns False if lost lease."""
    result = db.execute(
        update(Job)
        .where(
            Job.id == job.id,
            Job.status == JobStatus.leased,
            Job.leased_by == worker_id,
        )
        .values(
            status=JobStatus.succeeded,
            leased_by=None,
            lease_expires_at=None,
            last_error=None,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount == 1


def fail_job(
    db: Session,
    job: Job,
    *,
    worker_id: str,
    error: str,
) -> bool:
    """Retry with backoff or dead-letter. Returns False if lease lost."""
    settings = get_settings()
    owned = (
        db.execute(
            select(Job).where(
                Job.id == job.id,
                Job.status == JobStatus.leased,
                Job.leased_by == worker_id,
            )
        )
        .scalars()
        .first()
    )
    if not owned:
        return False

    attempts = owned.attempt_count
    if attempts >= settings.job_max_attempts:
        owned.status = JobStatus.dead
        owned.last_error = error
        owned.leased_by = None
        owned.lease_expires_at = None
    else:
        backoff = min(3600, 2**attempts)
        owned.status = JobStatus.failed
        owned.last_error = error
        owned.leased_by = None
        owned.lease_expires_at = None
        owned.run_at = _now() + timedelta(seconds=backoff)
    db.commit()
    return True


def heartbeat_lease(db: Session, job: Job, *, worker_id: str) -> bool:
    settings = get_settings()
    expires = _now() + timedelta(seconds=settings.job_lease_seconds)
    result = db.execute(
        update(Job)
        .where(
            Job.id == job.id,
            Job.status == JobStatus.leased,
            Job.leased_by == worker_id,
        )
        .values(lease_expires_at=expires)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount == 1
