"""M12 — public banner API: minimal DTO, env filter, no internal leak."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import auth_header


def _bootstrap(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    env_prod = client.post(
        "/api/v1/environments",
        json={"key": "PROD", "name": "Production", "sort_order": 1},
        headers=admin,
    ).json()
    env_dev = client.post(
        "/api/v1/environments",
        json={"key": "DEV", "name": "Development", "sort_order": 2},
        headers=admin,
    ).json()
    app = client.post(
        "/api/v1/applications",
        json={
            "key": "payments-gateway",
            "name": "Payments",
            "environments": [
                {"environment_id": env_prod["id"], "display_name": "Pay-PROD"},
                {"environment_id": env_dev["id"], "display_name": "Pay-DEV"},
            ],
        },
        headers=pub,
    ).json()
    return pub, admin, app, env_prod, env_dev


def test_banner_public_dto_excludes_internal_fields(client):
    pub, _admin, app, env_prod, _env_dev = _bootstrap(client)
    now = datetime.now(timezone.utc)
    created = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Public patch",
            "description": "INTERNAL NOTE MUST NOT LEAK",
            "expected_impact": "brief RO",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now - timedelta(minutes=10)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env_prod["id"],
                }
            ],
        },
        headers=pub,
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]
    client.post(
        f"/api/v1/events/{event_id}/transition",
        json={"status": "in_progress", "note": "started — internal"},
        headers=pub,
    )

    res = client.get(
        "/api/v1/public/banner?application_key=payments-gateway&environment_key=PROD",
        headers=pub,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body) >= 1
    msg = next(m for m in body if m["id"] == event_id)
    assert set(msg.keys()) <= {
        "id",
        "kind",
        "title",
        "status",
        "starts_at",
        "ends_at",
        "expected_impact",
        "approval_state",
    }
    raw = res.text
    assert "INTERNAL NOTE" not in raw
    assert "timeline" not in raw
    assert "description" not in raw
    assert msg["title"] == "Public patch"
    assert msg["status"] == "in_progress"


def test_banner_filters_by_environment_and_skips_approved_only(client):
    pub, _admin, app, env_prod, env_dev = _bootstrap(client)
    now = datetime.now(timezone.utc)
    # Confirmed on DEV only
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "DEV only",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=3)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env_dev["id"],
                }
            ],
        },
        headers=pub,
    )
    # Approved window on PROD — must not appear
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Approved only",
            "approval_state": "approved_window",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=3)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env_prod["id"],
                }
            ],
        },
        headers=pub,
    )

    prod = client.get(
        "/api/v1/public/banner?application_key=payments-gateway&environment_key=PROD",
        headers=pub,
    ).json()
    assert all(m["title"] != "DEV only" for m in prod)
    assert all(m["title"] != "Approved only" for m in prod)

    dev = client.get(
        "/api/v1/public/banner?application_key=payments-gateway&environment_key=DEV",
        headers=pub,
    ).json()
    assert any(m["title"] == "DEV only" for m in dev)


def test_banner_public_unauthenticated_and_service_scope(client):
    pub, admin, app, env_prod, _ = _bootstrap(client)
    now = datetime.now(timezone.utc)
    client.post(
        "/api/v1/events",
        json={
            "kind": "manual_outage",
            "title": "Outage",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env_prod["id"],
                }
            ],
        },
        headers=pub,
    )

    # Public DTO is intentionally readable without credentials (browser embeds).
    anon = client.get("/api/v1/public/banner?application_key=payments-gateway")
    assert anon.status_code == 200
    assert any(m["title"] == "Outage" for m in anon.json())

    created = client.post(
        "/api/v1/admin/service-credentials",
        headers=admin,
        json={"name": "embed", "scopes": ["banner:read"]},
    )
    assert created.status_code == 201
    tok = client.post(
        "/api/v1/auth/service/token",
        json={
            "client_id": created.json()["client_id"],
            "client_secret": created.json()["client_secret"],
        },
    )
    ok = client.get(
        "/api/v1/public/banner?application_key=payments-gateway",
        headers={"Authorization": f"Bearer {tok.json()['access_token']}"},
    )
    assert ok.status_code == 200
    assert any(m["title"] == "Outage" for m in ok.json())

    # Service credential without banner:read must not succeed when authenticating.
    bad = client.post(
        "/api/v1/admin/service-credentials",
        headers=admin,
        json={"name": "wrong-scope", "scopes": ["notifications:write"]},
    )
    assert bad.status_code == 201
    bad_tok = client.post(
        "/api/v1/auth/service/token",
        json={
            "client_id": bad.json()["client_id"],
            "client_secret": bad.json()["client_secret"],
        },
    )
    denied = client.get(
        "/api/v1/public/banner?application_key=payments-gateway",
        headers={"Authorization": f"Bearer {bad_tok.json()['access_token']}"},
    )
    assert denied.status_code == 403
