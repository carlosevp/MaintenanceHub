"""ICS approval-state accuracy + app-scoped / empty downloads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import auth_header


def _setup_app(client, headers, key="cal-app"):
    env = client.post(
        "/api/v1/environments",
        json={"key": "PROD", "name": "Production", "sort_order": 1},
        headers=headers,
    ).json()
    app = client.post(
        "/api/v1/applications",
        json={
            "key": key,
            "name": "Calendar App",
            "environments": [{"environment_id": env["id"], "display_name": "Cal-PROD"}],
        },
        headers=headers,
    ).json()
    return env, app


def test_download_empty_without_subscriptions(client):
    pub = auth_header(client, "publisher@test.example.com")
    res = client.get("/api/v1/calendar/download.ics", headers=pub)
    assert res.status_code == 200
    assert "BEGIN:VCALENDAR" in res.text
    assert "END:VCALENDAR" in res.text
    assert res.headers.get("X-MH-Calendar-Event-Count") == "0"


def test_download_application_scoped_without_subscription(client):
    pub = auth_header(client, "publisher@test.example.com")
    env, app = _setup_app(client, pub, key="scoped-dl")
    now = datetime.now(timezone.utc)
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "App Scoped Confirmed",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=2)).isoformat(),
            "ends_at": (now + timedelta(hours=3)).isoformat(),
            "timezone": "UTC",
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
    # No subscription / favorite — default download empty
    empty = client.get("/api/v1/calendar/download.ics", headers=pub)
    assert empty.headers.get("X-MH-Calendar-Event-Count") == "0"

    scoped = client.get(
        f"/api/v1/calendar/download.ics?application_id={app['id']}",
        headers=pub,
    )
    assert scoped.status_code == 200
    assert "App Scoped Confirmed" in scoped.text
    assert "STATUS:CONFIRMED" in scoped.text
    assert scoped.headers.get("X-MH-Calendar-Event-Count") == "1"
    assert "scoped-dl" in scoped.headers.get("content-disposition", "")


def test_approved_window_tentative_in_feed_and_download(client):
    pub = auth_header(client, "publisher@test.example.com")
    env, app = _setup_app(client, pub, key="approval-ics")
    client.put("/api/v1/me/favorites", json={"application_ids": [app["id"]]}, headers=pub)
    now = datetime.now(timezone.utc)
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Window Only",
            "approval_state": "approved_window",
            "starts_at": (now + timedelta(hours=4)).isoformat(),
            "ends_at": (now + timedelta(hours=5)).isoformat(),
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
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Confirmed Maint",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=6)).isoformat(),
            "ends_at": (now + timedelta(hours=7)).isoformat(),
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

    download = client.get("/api/v1/calendar/download.ics", headers=pub)
    assert download.status_code == 200
    body = download.text
    assert "[Approved window] Window Only" in body
    assert "STATUS:TENTATIVE" in body
    assert "Confirmed Maint" in body
    assert "STATUS:CONFIRMED" in body
    assert "confirmed_scheduled (confirmed maintenance)" in body
    assert "approved_window (tentative" in body

    token = client.post(
        "/api/v1/calendar-tokens",
        json={"scopes": ["favorites"], "label": "approval"},
        headers=pub,
    ).json()
    feed = client.get(f"/api/v1/public/ics/{token['token']}")
    assert feed.status_code == 200
    assert "[Approved window] Window Only" in feed.text
    assert "STATUS:TENTATIVE" in feed.text
    assert "Confirmed Maint" in feed.text
    assert "STATUS:CONFIRMED" in feed.text
