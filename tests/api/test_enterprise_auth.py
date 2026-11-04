"""M11 — fail-closed, OIDC/LDAP mock, service credentials + audit."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.conftest import auth_header


def test_fail_closed_local_dev_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_MODE", "local_dev")
    monkeypatch.setenv("ALLOW_LOCAL_AUTH", "false")
    from maintenancehub_api.config import Settings

    with pytest.raises(ValidationError):
        Settings()


def test_oidc_mock_login_flow(client, monkeypatch, db_session):
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("OIDC_MOCK", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")
    from maintenancehub_api.config import get_settings
    from maintenancehub_api.models import GroupRoleMapping, RoleName

    get_settings.cache_clear()

    # Seed group mapping
    db_session.add(
        GroupRoleMapping(directory_group="mh-publishers", role=RoleName.publisher)
    )
    db_session.commit()

    # Re-create app with new settings
    from maintenancehub_api.main import create_app
    from maintenancehub_api.db import get_db
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def _override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app = create_app()
    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        start = c.get("/api/v1/auth/oidc/start", follow_redirects=False)
        assert start.status_code in {302, 307}
        loc = start.headers["location"]
        assert "oidc/mock-login" in loc
        # Follow mock login with publisher group
        mock = c.get(
            loc + "&groups=mh-publishers",
            follow_redirects=False,
        )
        # mock redirects to callback
        assert mock.status_code in {302, 307}
        cb = c.get(mock.headers["location"])
        assert cb.status_code == 200, cb.text
        token = cb.json()["access_token"]
        me = c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert "publisher" in me.json()["roles"]


def test_ldap_mock_login(client, monkeypatch, db_session):
    monkeypatch.setenv("AUTH_MODE", "ldap")
    monkeypatch.setenv("LDAP_MOCK", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")
    from maintenancehub_api.config import get_settings
    from maintenancehub_api.models import GroupRoleMapping, RoleName
    from maintenancehub_api.main import create_app
    from maintenancehub_api.db import get_db
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    get_settings.cache_clear()
    db_session.add(
        GroupRoleMapping(directory_group="mh-publishers", role=RoleName.publisher)
    )
    db_session.commit()

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def _override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app = create_app()
    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        res = c.post(
            "/api/v1/auth/login",
            json={"email": "ldap.user@example.com", "password": "ldap-pass"},
        )
        assert res.status_code == 200, res.text
        me = c.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {res.json()['access_token']}"},
        )
        assert "publisher" in me.json()["roles"]


def test_service_credential_banner_not_admin(client):
    admin = auth_header(client, "admin@test.example.com")
    created = client.post(
        "/api/v1/admin/service-credentials",
        headers=admin,
        json={"name": "banner-bot", "scopes": ["banner:read"]},
    )
    assert created.status_code == 201, created.text
    client_id = created.json()["client_id"]
    secret = created.json()["client_secret"]

    tok = client.post(
        "/api/v1/auth/service/token",
        json={"client_id": client_id, "client_secret": secret},
    )
    assert tok.status_code == 200
    headers = {"Authorization": f"Bearer {tok.json()['access_token']}"}

    banner = client.get(
        "/api/v1/public/banner?application_key=nonexistent",
        headers=headers,
    )
    assert banner.status_code == 200
    assert banner.json() == []

    # Cannot admin
    denied = client.get("/api/v1/admin/jobs", headers=headers)
    assert denied.status_code == 403

    # Audit for credential create
    audit = client.get("/api/v1/admin/audit", headers=admin)
    assert audit.status_code == 200
    actions = [a["action"] for a in audit.json()]
    assert "service_credential.create" in actions
