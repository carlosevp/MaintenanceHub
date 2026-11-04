"""Shared pytest fixtures — isolated SQLite DB per test session/function."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Fail-closed settings for tests
os.environ["ENVIRONMENT"] = "development"
os.environ["AUTH_MODE"] = "local_dev"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["DATABASE_URL"] = "sqlite://"

from maintenancehub_api.auth.security import hash_password  # noqa: E402
from maintenancehub_api.db import Base, get_db  # noqa: E402
from maintenancehub_api.main import create_app  # noqa: E402
from maintenancehub_api.models import Role, RoleName, User, UserRole  # noqa: E402
from maintenancehub_api import models  # noqa: E402, F401


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)
    session = Session()
    # seed roles + users
    roles = {}
    for name in RoleName:
        r = Role(name=name)
        session.add(r)
        session.flush()
        roles[name] = r

    def add_user(email: str, role: RoleName) -> User:
        u = User(
            email=email,
            display_name=email.split("@")[0],
            password_hash=hash_password("password123"),
            is_active=True,
        )
        session.add(u)
        session.flush()
        session.add(UserRole(user_id=u.id, role_id=roles[role].id))
        return u

    viewer = add_user("viewer@test.example.com", RoleName.viewer)
    publisher = add_user("publisher@test.example.com", RoleName.publisher)
    admin = add_user("admin@test.example.com", RoleName.platform_administrator)
    session.commit()
    session.viewer = viewer  # type: ignore[attr-defined]
    session.publisher = publisher  # type: ignore[attr-defined]
    session.admin = admin  # type: ignore[attr-defined]
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _reset_settings_env():
    """Prevent AUTH_MODE / feature-flag leaks across tests (lru_cache)."""
    os.environ["ENVIRONMENT"] = "development"
    os.environ["AUTH_MODE"] = "local_dev"
    os.environ["ALLOW_LOCAL_AUTH"] = "false"
    os.environ["SEED_DEMO_DATA"] = "false"
    os.environ["JWT_SECRET"] = "test-secret"
    os.environ["OIDC_MOCK"] = "false"
    os.environ["LDAP_MOCK"] = "false"
    os.environ["SERVICENOW_ENABLED"] = "false"
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def client(db_engine, db_session):
    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)

    def _override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        c.db = db_session  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def auth_header(client: TestClient, email: str, password: str = "password123") -> dict[str, str]:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
