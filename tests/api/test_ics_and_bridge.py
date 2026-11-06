"""M7/M8 — bridge subject routing + ICS token revoke."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import auth_header


def test_bridge_subject_contains_channel_key():
    from maintenancehub_api.adapters.bridge import render_bridge_subject

    subject = render_bridge_subject(channel_key="ops-payments", title="DB patch")
    assert "ops-payments" in subject
    assert "DB patch" in subject
    assert "MH-ROUTE" in subject


def test_bridge_connection_test_copy(client):
    admin = auth_header(client, "admin@test.example.com")
    res = client.post(
        "/api/v1/admin/settings/integrations/test?kind=bridge",
        headers=admin,
    )
    assert res.status_code == 200
    body = res.json()
    assert "Teams via email bridge" in body["note"]
    assert "Teams API" in body["note"] or "webhooks" in body["note"]


def test_ics_token_create_and_revoke(client):
    pub = auth_header(client, "publisher@test.example.com")
    # Create app + favorite so feed has content path
    admin = auth_header(client, "admin@test.example.com")
    env = client.post(
        "/api/v1/environments",
        json={"key": "PROD", "name": "Production", "sort_order": 1},
        headers=admin,
    ).json()
    app = client.post(
        "/api/v1/applications",
        json={
            "key": "ics-app",
            "name": "ICS App",
            "environments": [{"environment_id": env["id"], "display_name": "ICS-PROD"}],
        },
        headers=pub,
    ).json()
    client.put(
        "/api/v1/me/favorites",
        json={"application_ids": [app["id"]]},
        headers=pub,
    )
    now = datetime.now(timezone.utc)
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "ICS Event",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
            "timezone": "America/Chicago",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env["id"],
                }
            ],
        },
        headers=pub,
    )

    created = client.post(
        "/api/v1/calendar-tokens",
        json={"scopes": ["favorites"], "label": "Outlook"},
        headers=pub,
    )
    assert created.status_code == 201, created.text
    data = created.json()
    assert "token" in data
    assert data["feed_url"].endswith(data["token"])
    raw = data["token"]

    feed = client.get(f"/api/v1/public/ics/{raw}")
    assert feed.status_code == 200
    assert "BEGIN:VCALENDAR" in feed.text
    assert "ICS Event" in feed.text
    assert "VERSION:2.0" in feed.text

    revoke = client.delete(f"/api/v1/calendar-tokens/{data['id']}", headers=pub)
    assert revoke.status_code == 204
    blocked = client.get(f"/api/v1/public/ics/{raw}")
    assert blocked.status_code == 401


def test_notification_test_send_log_sink(client):
    pub = auth_header(client, "publisher@test.example.com")
    res = client.post(
        "/api/v1/notifications/test",
        json={
            "template_key": "event.created",
            "destination_type": "email_address",
            "destination": "test@example.com",
            "capture_only": True,
        },
        headers=pub,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "sent"
    assert body["channel"] in {"log", "smtp", "capture"}
    assert body["teams_delivery_confirmed"] is False


def test_teams_bridge_test_send_subject(client):
    pub = auth_header(client, "publisher@test.example.com")
    res = client.post(
        "/api/v1/notifications/test",
        json={
            "template_key": "event.created",
            "destination_type": "teams_bridge_channel",
            "destination": "bridge@example.com",
            "bridge_channel_key": "ops-test",
            "capture_only": True,
        },
        headers=pub,
    )
    assert res.status_code == 200, res.text
    assert "ops-test" in res.json()["subject"]
    assert "NOT Teams delivery" in res.json()["note"] or "not Teams" in res.json()["note"].lower()


def test_real_test_send_requires_admin(client):
    pub = auth_header(client, "publisher@test.example.com")
    res = client.post(
        "/api/v1/notifications/test",
        json={
            "template_key": "event.created",
            "destination_type": "email_address",
            "destination": "test@example.com",
            "capture_only": False,
        },
        headers=pub,
    )
    assert res.status_code == 403
