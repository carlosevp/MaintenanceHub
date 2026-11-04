import pytest
from pydantic import ValidationError


def test_local_dev_refused_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_MODE", "local_dev")
    monkeypatch.setenv("ALLOW_LOCAL_AUTH", "false")
    from maintenancehub_api.config import Settings

    with pytest.raises(ValidationError):
        Settings()


def test_break_glass_allows_local_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_MODE", "local_dev")
    monkeypatch.setenv("ALLOW_LOCAL_AUTH", "true")
    monkeypatch.setenv("JWT_SECRET", "production-grade-secret-value-32chars")
    from maintenancehub_api.config import Settings

    s = Settings()
    assert s.auth_mode == "local_dev"
    assert s.allow_local_auth is True


def test_weak_jwt_refused_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("JWT_SECRET", "change-me-local-dev-only")
    from maintenancehub_api.config import Settings

    with pytest.raises(ValidationError):
        Settings()
