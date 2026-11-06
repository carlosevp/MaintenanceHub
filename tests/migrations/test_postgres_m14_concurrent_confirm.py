"""M14 harden — concurrent confirm on Postgres: no lost updates / duplicate publish."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
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
def pg_engine(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    engine = create_engine(PG_URL, pool_pre_ping=True, future=True, pool_size=5)
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


def test_concurrent_confirm_same_revision_single_publish(pg_engine):
    from maintenancehub_api.domain import events as event_service
    from maintenancehub_api.domain import impact_preview as preview_service
    from maintenancehub_api.models import (
        Application,
        Dependency,
        Environment,
        InfraComponent,
        OutboxEvent,
    )

    Session = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, future=True)
    setup = Session()
    env = Environment(key="NON-PROD", name="NON-PROD", sort_order=1)
    setup.add(env)
    setup.flush()
    claims = Application(key="claims", name="Claims")
    setup.add(claims)
    setup.flush()
    oracle = InfraComponent(key="oracle", name="Oracle", kind="database")
    setup.add(oracle)
    setup.flush()
    setup.add(
        Dependency(
            from_type="application",
            from_id=claims.id,
            to_type="infra_component",
            to_id=oracle.id,
            from_environment_id=env.id,
            to_environment_id=env.id,
            origin="import",
        )
    )
    starts = datetime.now(timezone.utc) + timedelta(days=2)
    ends = starts + timedelta(hours=2)
    event = event_service.create_event(
        setup,
        data={
            "kind": "planned_maintenance",
            "title": "Concurrent confirm",
            "approval_state": "approved_window",
            "starts_at": starts,
            "ends_at": ends,
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "infra_component",
                    "target_id": oracle.id,
                    "environment_id": env.id,
                }
            ],
        },
        actor_id=None,
    )
    event_id = event.id
    preview = preview_service.build_preview(
        setup,
        seeds=[
            {
                "target_type": "infra_component",
                "target_id": oracle.id,
                "environment_id": env.id,
            }
        ],
        starts_at=starts,
        ends_at=ends,
        event_id=event_id,
        include_destinations=False,
    )
    token = preview["revision_token"]
    include = [
        {
            "target_type": s["target_type"],
            "target_id": s["target_id"],
            "environment_id": s.get("environment_id"),
        }
        for s in preview["suggested_downstream"]
    ]
    seeds = [
        {
            "target_type": "infra_component",
            "target_id": oracle.id,
            "environment_id": env.id,
        }
    ]
    setup.close()

    results: list[str] = []

    def _confirm() -> str:
        s = Session()
        try:
            ev = event_service.get_event(s, event_id)
            assert ev is not None
            preview_service.confirm_impact_analysis(
                s,
                ev,
                revision_token=token,
                seeds=seeds,
                starts_at=starts,
                ends_at=ends,
                exclusions=[],
                manual_additions=[],
                include_downstream=include,
                original_starts_at=None,
                actor_id=None,
                publish=True,
            )
            return "ok"
        except ValueError as exc:
            return f"err:{exc}"
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [pool.submit(_confirm) for _ in range(2)]
        for f in as_completed(futs):
            results.append(f.result())

    assert any(r == "ok" for r in results)
    # Second either errors stale/unreviewed or also ok if it ran as impacts_changed
    # after first publish — but outbox event.confirmed must be exactly one.
    verify = Session()
    try:
        n = (
            verify.query(OutboxEvent)
            .filter(
                OutboxEvent.aggregate_id == event_id,
                OutboxEvent.event_type == "event.confirmed",
            )
            .count()
        )
        assert n == 1, (n, results)
    finally:
        verify.close()
