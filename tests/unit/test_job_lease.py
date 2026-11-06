"""M5 — lease exclusivity and reclaim after expiry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from maintenancehub_api.jobs.locking import claim_jobs, complete_job, fail_job
from maintenancehub_api.models import Job, JobStatus


def _add_job(db, key: str = "k1") -> Job:
    job = Job(
        job_type="notify_dispatch",
        payload={"event_id": "e1"},
        idempotency_key=key,
        status=JobStatus.queued,
        run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_two_workers_only_one_claims(db_session, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()

    job = _add_job(db_session, "lease-1")
    claimed_a = claim_jobs(db_session, worker_id="worker-a", limit=5)
    assert len(claimed_a) == 1
    assert claimed_a[0].id == job.id
    assert claimed_a[0].leased_by == "worker-a"

    claimed_b = claim_jobs(db_session, worker_id="worker-b", limit=5)
    assert claimed_b == []

    assert complete_job(db_session, claimed_a[0], worker_id="worker-a") is True
    # Second complete by other worker fails
    claimed_a[0].status = JobStatus.leased
    claimed_a[0].leased_by = "worker-a"
    db_session.commit()
    # After success path already ran — verify foreign complete rejected
    job2 = _add_job(db_session, "lease-2")
    c = claim_jobs(db_session, worker_id="worker-a", limit=1)[0]
    assert complete_job(db_session, c, worker_id="worker-b") is False
    assert complete_job(db_session, c, worker_id="worker-a") is True
    assert job2.id == c.id


def test_expired_lease_reclaimed(db_session, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()

    job = _add_job(db_session, "reclaim-1")
    claimed = claim_jobs(db_session, worker_id="worker-a", limit=1)
    assert len(claimed) == 1
    # Expire lease
    claimed[0].lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    db_session.commit()

    reclaimed = claim_jobs(db_session, worker_id="worker-b", limit=1)
    assert len(reclaimed) == 1
    assert reclaimed[0].id == job.id
    assert reclaimed[0].leased_by == "worker-b"


def test_fail_then_dead_letter(db_session, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("JOB_MAX_ATTEMPTS", "2")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()

    _add_job(db_session, "dead-1")
    c1 = claim_jobs(db_session, worker_id="w", limit=1)[0]
    assert fail_job(db_session, c1, worker_id="w", error="boom1")
    db_session.refresh(c1)
    assert c1.status == JobStatus.failed

    # Make runnable
    c1.run_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    c2 = claim_jobs(db_session, worker_id="w", limit=1)[0]
    assert fail_job(db_session, c2, worker_id="w", error="boom2")
    db_session.refresh(c2)
    assert c2.status == JobStatus.dead
