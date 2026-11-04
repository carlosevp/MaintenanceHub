"""M14 Alembic on PostgreSQL — impact_decisions, dep env columns, preview/confirm."""

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
def pg_engine(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    engine = create_engine(PG_URL, pool_pre_ping=True, future=True)
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


def test_postgres_m14_schema_and_preview_confirm(pg_engine, monkeypatch):
    insp = inspect(pg_engine)
    assert "impact_decisions" in set(insp.get_table_names())
    dep_cols = {c["name"] for c in insp.get_columns("dependencies")}
    assert "from_environment_id" in dep_cols
    assert "to_environment_id" in dep_cols
    assert "updated_at" in dep_cols
    evt_cols = {c["name"] for c in insp.get_columns("maintenance_events")}
    assert "impact_revision" in evt_cols
    ci_cols = {c["name"] for c in insp.get_columns("external_ci_links")}
    assert "updated_at" in ci_cols

    monkeypatch.setenv("DATABASE_URL", PG_URL)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AUTH_MODE", "local_dev")
    monkeypatch.setenv("SEED_DEMO_DATA", "false")
    monkeypatch.setenv("JWT_SECRET", "test-secret")

    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()

    from maintenancehub_api.auth.security import hash_password
    from maintenancehub_api.db import get_db
    from maintenancehub_api.domain import impact_preview as preview_service
    from maintenancehub_api.domain.impacts import ImpactRef
    from maintenancehub_api.main import create_app
    from maintenancehub_api.models import (
        Application,
        Dependency,
        Environment,
        InfraComponent,
        Role,
        RoleName,
        User,
        UserRole,
    )
    from fastapi.testclient import TestClient

    Session = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, future=True)
    session = Session()
    for name in RoleName:
        session.add(Role(name=name))
    session.flush()
    roles = {r.name: r for r in session.query(Role).all()}
    admin = User(
        email="admin@pg.example.com",
        display_name="Admin",
        password_hash=hash_password("password123"),
        is_active=True,
    )
    session.add(admin)
    session.flush()
    session.add(UserRole(user_id=admin.id, role_id=roles[RoleName.platform_administrator].id))
    env = Environment(key="NON-PROD", name="NON-PROD", sort_order=1)
    session.add(env)
    session.flush()
    claims = Application(key="claims", name="Claims")
    session.add(claims)
    session.flush()
    oracle = InfraComponent(key="oracle", name="Oracle", kind="database")
    session.add(oracle)
    session.flush()
    session.add(
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
    session.commit()

    def _override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app = create_app()
    app.dependency_overrides[get_db] = _override
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@pg.example.com", "password": "password123"},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        starts = datetime.now(timezone.utc) + timedelta(days=1)
        ends = starts + timedelta(hours=2)
        created = client.post(
            "/api/v1/events",
            json={
                "kind": "planned_maintenance",
                "title": "PG Oracle",
                "approval_state": "approved_window",
                "starts_at": starts.isoformat(),
                "ends_at": ends.isoformat(),
                "timezone": "UTC",
                "impacts": [
                    {
                        "target_type": "infra_component",
                        "target_id": oracle.id,
                        "environment_id": env.id,
                    }
                ],
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        event = created.json()
        preview = client.post(
            "/api/v1/impact-analysis/preview",
            json={
                "seeds": event["impacts"],
                "starts_at": event["starts_at"],
                "ends_at": event["ends_at"],
                "event_id": event["id"],
            },
            headers=headers,
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert any(s["target_id"] == claims.id for s in body["suggested_downstream"])
        confirm = client.post(
            f"/api/v1/impact-analysis/events/{event['id']}/confirm",
            json={
                "revision_token": body["revision_token"],
                "seeds": event["impacts"],
                "starts_at": event["starts_at"],
                "ends_at": event["ends_at"],
                "include_downstream": [
                    {
                        "target_type": "application",
                        "target_id": claims.id,
                        "environment_id": env.id,
                    }
                ],
                "publish": True,
            },
            headers=headers,
        )
        assert confirm.status_code == 200, confirm.text
        assert confirm.json()["approval_state"] == "confirmed_scheduled"

    # Domain service works on same PG session factory
    s2 = Session()
    try:
        result = preview_service.build_preview(
            s2,
            seeds=[{"target_type": "infra_component", "target_id": oracle.id, "environment_id": env.id}],
            starts_at=starts,
            ends_at=ends,
        )
        assert result["read_only"] is True
        assert ImpactRef("infra_component", oracle.id, env.id)
    finally:
        s2.close()
    session.close()
    app.dependency_overrides.clear()
    get_settings.cache_clear()
