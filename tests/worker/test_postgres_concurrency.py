"""J — worker restart + concurrent claims on real PostgreSQL (not SQLite).

Requires: DATABASE_URL pointing at Postgres (default mh_test local).
Skip cleanly when Postgres is unreachable.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from maintenancehub_api.db import Base
from maintenancehub_api.jobs.locking import claim_jobs, complete_job
from maintenancehub_api.models import Job, JobStatus
from maintenancehub_api import models as _models  # noqa: F401

PG_URL = os.environ.get(
    "TEST_POSTGRES_URL",
    "postgresql+psycopg://mh:mh@127.0.0.1:5432/mh_test",
)


def _postgres_available(url: str) -> bool:
    try:
        eng = create_engine(url, pool_pre_ping=True, future=True)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_available(PG_URL),
    reason=f"Postgres not available at {PG_URL}",
)


@pytest.fixture()
def pg_engine(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AUTH_MODE", "local_dev")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()
    engine = create_engine(PG_URL, pool_pre_ping=True, future=True, pool_size=10)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    get_settings.cache_clear()


@pytest.fixture()
def PgSession(pg_engine):
    return sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, future=True)


def _seed_jobs(Session, n: int = 20) -> list[str]:
    db = Session()
    ids = []
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    for i in range(n):
        job = Job(
            job_type="notify_dispatch",
            payload={"i": i},
            idempotency_key=f"pg-conc-{i}-{os.getpid()}",
            status=JobStatus.queued,
            run_at=now,
        )
        db.add(job)
        db.flush()
        ids.append(job.id)
    db.commit()
    db.close()
    return ids


def test_J_concurrent_workers_exclusive_claim(PgSession, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()
    assert get_settings().is_postgres

    ids = _seed_jobs(PgSession, 30)
    claimed: list[str] = []
    lock = threading.Lock()

    def worker(wid: str) -> list[str]:
        db = PgSession()
        got = []
        try:
            while True:
                batch = claim_jobs(db, worker_id=wid, limit=3)
                if not batch:
                    break
                for j in batch:
                    got.append(j.id)
                    assert complete_job(db, j, worker_id=wid) is True
        finally:
            db.close()
        return got

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(worker, f"w-{i}") for i in range(4)]
        for f in as_completed(futs):
            with lock:
                claimed.extend(f.result())

    assert sorted(claimed) == sorted(ids)
    assert len(claimed) == len(set(claimed)), "duplicate claims across workers"


def test_J_worker_restart_reclaims_expired_lease(PgSession, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    monkeypatch.setenv("JOB_LEASE_SECONDS", "30")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()

    db = PgSession()
    job = Job(
        job_type="outbox_drain",
        payload={},
        idempotency_key=f"restart-{os.getpid()}",
        status=JobStatus.queued,
        run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id

    claimed = claim_jobs(db, worker_id="worker-old", limit=1)
    assert len(claimed) == 1 and claimed[0].id == job_id
    # Simulate crash: lease expires without complete
    claimed[0].lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    db.commit()
    db.close()

    db2 = PgSession()
    reclaimed = claim_jobs(db2, worker_id="worker-new", limit=1)
    assert len(reclaimed) == 1
    assert reclaimed[0].id == job_id
    assert reclaimed[0].leased_by == "worker-new"
    assert complete_job(db2, reclaimed[0], worker_id="worker-new") is True
    db2.close()
