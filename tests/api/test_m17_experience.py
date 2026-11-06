"""M17 experience profile capability registry."""

from __future__ import annotations

import os

from tests.conftest import auth_header


def test_experience_endpoint_default_enterprise(client):
    r = client.get("/api/v1/experience")
    assert r.status_code == 200
    body = r.json()
    assert body["profile"] in {"essentials", "team", "enterprise"}
    assert "capabilities" in body
    assert body["capabilities"]["overview"] is True


def test_essentials_blocks_impact_and_admin(client, monkeypatch):
    monkeypatch.setenv("EXPERIENCE_PROFILE", "essentials")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()
    try:
        exp = client.get("/api/v1/experience").json()
        assert exp["profile"] == "essentials"
        assert exp["capabilities"]["impact_analysis"] is False
        assert exp["capabilities"]["admin_workspace"] is False
        assert exp["capabilities"]["servicenow"] is False
        assert exp["capabilities"]["csv_import"] is False

        pub = auth_header(client, "publisher@test.example.com")
        r = client.post(
            "/api/v1/impact-analysis/preview",
            headers=pub,
            json={
                "seeds": [
                    {
                        "target_type": "application",
                        "target_id": "00000000-0000-0000-0000-000000000001",
                        "environment_id": None,
                    }
                ],
                "starts_at": "2030-01-01T00:00:00+00:00",
                "ends_at": "2030-01-01T01:00:00+00:00",
                "max_depth": 5,
            },
        )
        assert r.status_code == 403, r.text

        admin = auth_header(client, "admin@test.example.com")
        r2 = client.get("/api/v1/admin/overview", headers=admin)
        assert r2.status_code == 403
    finally:
        os.environ.pop("EXPERIENCE_PROFILE", None)
        get_settings.cache_clear()


def test_enterprise_allows_admin_overview(client, monkeypatch):
    monkeypatch.setenv("EXPERIENCE_PROFILE", "enterprise")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()
    try:
        admin = auth_header(client, "admin@test.example.com")
        r = client.get("/api/v1/admin/overview", headers=admin)
        assert r.status_code == 200
    finally:
        os.environ.pop("EXPERIENCE_PROFILE", None)
        get_settings.cache_clear()
