"""PR #8 Alembic on real PostgreSQL — upgrade, indexes, lifecycle ops."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

PG_URL = os.environ.get(
    "TEST_POSTGRES_URL",
    "postgresql+psycopg://mh:mh@127.0.0.1:5432/mh_test",
)
ROOT = Path(__file__).resolve().parents[2]


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
def pg_alembic_engine(monkeypatch):
    # env.py prefers DATABASE_URL — force Postgres (conftest defaults to sqlite://)
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    engine = create_engine(PG_URL, pool_pre_ping=True, future=True)
    # Drop everything so alembic upgrade is the sole schema source
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(ROOT / "db" / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", PG_URL)
    old = os.getcwd()
    os.chdir(ROOT)
    try:
        command.upgrade(cfg, "head")
    finally:
        os.chdir(old)
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def test_postgres_alembic_occurrence_schema_and_lifecycle(pg_alembic_engine, monkeypatch):
    insp = inspect(pg_alembic_engine)
    tables = set(insp.get_table_names())
    assert "occurrence_records" in tables
    assert "occurrence_impacts" in tables

    occ_indexes = {ix["name"] for ix in insp.get_indexes("occurrence_records")}
    assert "ix_occurrence_event_status" in occ_indexes or any(
        "original_starts" in (n or "") for n in occ_indexes
    )
    assert "ix_occurrence_records_original_starts_at" in occ_indexes

    impact_indexes = {ix["name"] for ix in insp.get_indexes("occurrence_impacts")}
    assert "ix_occurrence_impacts_target" in impact_indexes

    uniques = {u["name"] for u in insp.get_unique_constraints("occurrence_records")}
    assert "uq_occurrence_identity" in uniques

    # Lifecycle ops against Alembic-built schema (not create_all)
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AUTH_MODE", "local_dev")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()

    from maintenancehub_api.auth.security import hash_password
    from maintenancehub_api.domain import events as event_service
    from maintenancehub_api.domain import occurrences as occurrence_service
    from maintenancehub_api.models import (
        Application,
        Environment,
        EventStatus,
        Role,
        RoleName,
        User,
        UserRole,
    )

    Session = sessionmaker(bind=pg_alembic_engine, autoflush=False, autocommit=False, future=True)
    db = Session()
    try:
        roles = {}
        for name in RoleName:
            r = Role(name=name)
            db.add(r)
            db.flush()
            roles[name] = r
        user = User(
            email="pg-occ@test.example.com",
            display_name="PG",
            password_hash=hash_password("password123"),
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=roles[RoleName.platform_administrator].id))
        app = Application(key="pg-app", name="PG App")
        env = Environment(key="PROD", name="Production", sort_order=1)
        db.add_all([app, env])
        db.commit()

        starts = datetime(2032, 1, 5, 12, 0, tzinfo=timezone.utc)
        event = event_service.create_event(
            db,
            data={
                "kind": "planned_maintenance",
                "title": "PG occurrence lifecycle",
                "approval_state": "confirmed_scheduled",
                "starts_at": starts,
                "ends_at": starts + timedelta(hours=1),
                "timezone": "UTC",
                "impacts": [
                    {
                        "target_type": "application",
                        "target_id": app.id,
                        "environment_id": env.id,
                    }
                ],
                "recurrence": {"freq": "WEEKLY", "count": 3},
            },
            actor_id=user.id,
        )
        from maintenancehub_api.domain import recurrence as recurrence_service

        occs = recurrence_service.expand_event_occurrences(
            event,
            range_start=starts - timedelta(seconds=1),
            range_end=starts + timedelta(days=21),
        )
        assert len(occs) >= 2
        occurrence_service.transition_occurrence(
            db,
            event,
            original_starts_at=occs[0].original_starts_at,
            target_status=EventStatus.in_progress,
            actor_id=user.id,
        )
        occurrence_service.patch_occurrence(
            db,
            event,
            original_starts_at=occs[1].original_starts_at,
            actor_id=user.id,
            impacts=[],  # explicit empty override
        )
        rec0 = occurrence_service.find_record(db, event.id, occs[0].original_starts_at)
        rec1 = occurrence_service.find_record(db, event.id, occs[1].original_starts_at)
        assert rec0 is not None and rec0.status == EventStatus.in_progress
        assert rec1 is not None and rec1.impacts_overridden is True
        assert list(rec1.impacts or []) == []
    finally:
        db.close()
        get_settings.cache_clear()
