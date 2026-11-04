"""Ensure Alembic metadata / schema creates cleanly on SQLite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("AUTH_MODE", "local_dev")

from maintenancehub_api.db import Base
from maintenancehub_api import models  # noqa: F401


def test_sqlite_create_all_has_core_tables_and_uniques(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(bind=engine)
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    required = {
        "users",
        "roles",
        "applications",
        "environments",
        "app_environments",
        "maintenance_events",
        "event_impacts",
        "event_timeline_entries",
        "jobs",
        "outbox_events",
        "notification_deliveries",
        "favorites",
        "audit_log",
        "dependencies",
        "external_ci_links",
    }
    assert required.issubset(tables)

    # Unique constraints / indexes present for idempotency keys
    job_uniques = {u["name"] for u in insp.get_unique_constraints("jobs")}
    delivery_uniques = {u["name"] for u in insp.get_unique_constraints("notification_deliveries")}
    event_uniques = {u["name"] for u in insp.get_unique_constraints("maintenance_events")}
    assert "uq_job_idempotency" in job_uniques
    assert "uq_delivery_idempotency" in delivery_uniques
    assert "uq_event_source_external" in event_uniques


def test_idempotency_unique_enforced():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO notification_deliveries "
                "(id, idempotency_key, channel, destination, status, attempt_count) "
                "VALUES ('1', 'k1', 'smtp', 'a@b.c', 'pending', 0)"
            )
        )
        with pytest.raises(Exception):
            conn.execute(
                text(
                    "INSERT INTO notification_deliveries "
                    "(id, idempotency_key, channel, destination, status, attempt_count) "
                    "VALUES ('2', 'k1', 'smtp', 'a@b.c', 'pending', 0)"
                )
            )
