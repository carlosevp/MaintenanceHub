"""ICS VALARM from subscription reminders — feed + download, recurrence/cancel."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import auth_header


def _bootstrap(client, *, key: str = "valarm-app"):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    env = client.post(
        "/api/v1/environments",
        json={"key": "PROD", "name": "Production", "sort_order": 1},
        headers=admin,
    ).json()
    app = client.post(
        "/api/v1/applications",
        json={
            "key": key,
            "name": "VALARM App",
            "environments": [{"environment_id": env["id"], "display_name": "VA-PROD"}],
        },
        headers=pub,
    ).json()
    return pub, admin, app, env


def test_download_and_feed_include_valarm_from_subscription_reminders(client):
    pub, _admin, app, env = _bootstrap(client, key="valarm-sub")
    now = datetime.now(timezone.utc)
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "VALARM Maint",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=6)).isoformat(),
            "ends_at": (now + timedelta(hours=7)).isoformat(),
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
    sub = client.post(
        "/api/v1/subscriptions",
        json={
            "destination_type": "email_address",
            "destination": "publisher@test.example.com",
            "targets": [
                {
                    "target_type": "app_environment",
                    "target_id": f"{app['id']}:{env['id']}",
                }
            ],
            "reminders": [
                {"offset_minutes": -60},
                {"offset_minutes": -5},
            ],
        },
        headers=pub,
    )
    assert sub.status_code == 201, sub.text

    plain = client.get("/api/v1/calendar/download.ics", headers=pub)
    assert plain.status_code == 200
    assert "BEGIN:VALARM" not in plain.text
    assert plain.headers.get("X-MH-Calendar-Include-Alarms") == "0"

    with_alarms = client.get(
        "/api/v1/calendar/download.ics?include_alarms=true",
        headers=pub,
    )
    assert with_alarms.status_code == 200
    body = with_alarms.text
    assert "VALARM Maint" in body
    assert "STATUS:CONFIRMED" in body
    assert "BEGIN:VALARM" in body
    assert "TRIGGER:-PT1H" in body
    assert "TRIGGER:-PT5M" in body
    assert with_alarms.headers.get("X-MH-Calendar-Include-Alarms") == "1"

    token = client.post(
        "/api/v1/calendar-tokens",
        json={
            "scopes": ["favorites", "subscriptions"],
            "label": "with-alarms",
            "include_alarms": True,
        },
        headers=pub,
    )
    assert token.status_code == 201, token.text
    assert token.json()["include_alarms"] is True
    feed = client.get(f"/api/v1/public/ics/{token.json()['token']}")
    assert feed.status_code == 200
    assert "BEGIN:VALARM" in feed.text
    assert "TRIGGER:-PT1H" in feed.text
    assert "TRIGGER:-PT5M" in feed.text
    assert feed.headers.get("X-MH-Calendar-Include-Alarms") == "1"

    no_alarm_token = client.post(
        "/api/v1/calendar-tokens",
        json={"scopes": ["subscriptions"], "label": "no-alarms", "include_alarms": False},
        headers=pub,
    ).json()
    quiet = client.get(f"/api/v1/public/ics/{no_alarm_token['token']}")
    assert "BEGIN:VALARM" not in quiet.text


def test_valarm_recurrence_cancel_and_reschedule(client):
    pub, _admin, app, env = _bootstrap(client, key="valarm-recur")
    starts = datetime(2026, 7, 6, 14, 0, tzinfo=timezone.utc)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "kind": "planned_maintenance",
            "title": "Weekly VALARM",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env["id"],
                }
            ],
            "recurrence": {"freq": "WEEKLY", "byweekday": ["MO"], "count": 4},
        },
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]
    second = starts + timedelta(days=7)
    third = starts + timedelta(days=14)

    cancel = client.post(
        f"/api/v1/events/{event_id}/cancel",
        headers=pub,
        json={"scope": "this", "original_starts_at": second.isoformat()},
    )
    assert cancel.status_code == 200, cancel.text

    resched = client.post(
        f"/api/v1/events/{event_id}/series-edit",
        headers=pub,
        json={
            "scope": "this",
            "original_starts_at": third.isoformat(),
            "starts_at": (third + timedelta(hours=2)).isoformat(),
            "ends_at": (third + timedelta(hours=3)).isoformat(),
        },
    )
    assert resched.status_code == 200, resched.text

    client.post(
        "/api/v1/subscriptions",
        json={
            "destination_type": "email_address",
            "destination": "publisher@test.example.com",
            "targets": [{"target_type": "application", "target_id": app["id"]}],
            "reminders": [{"offset_minutes": -60}, {"offset_minutes": -30}],
        },
        headers=pub,
    )

    download = client.get(
        "/api/v1/calendar/download.ics?include_alarms=true",
        headers=pub,
    )
    assert download.status_code == 200
    text = download.text
    assert "RRULE:FREQ=WEEKLY" in text
    assert "EXDATE:" in text
    assert "RECURRENCE-ID:" in text
    assert "BEGIN:VALARM" in text
    assert "TRIGGER:-PT1H" in text
    assert "TRIGGER:-PT30M" in text
    # Master + override should both carry alarms; cancelled occurrences stay as EXDATE only.
    assert text.count("BEGIN:VALARM") >= 4  # 2 offsets × (master + override)


def test_cancelled_series_omits_valarm(client):
    pub, _admin, app, env = _bootstrap(client, key="valarm-cancel-all")
    now = datetime.now(timezone.utc)
    created = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Soon Cancelled",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=3)).isoformat(),
            "ends_at": (now + timedelta(hours=4)).isoformat(),
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
    ).json()
    client.post(
        "/api/v1/subscriptions",
        json={
            "destination_type": "email_address",
            "destination": "publisher@test.example.com",
            "targets": [{"target_type": "application", "target_id": app["id"]}],
            "reminders": [{"offset_minutes": -5}],
        },
        headers=pub,
    )
    client.post(
        f"/api/v1/events/{created['id']}/cancel",
        headers=pub,
        json={"scope": "all"},
    )
    download = client.get(
        "/api/v1/calendar/download.ics?include_alarms=true",
        headers=pub,
    )
    assert "STATUS:CANCELLED" in download.text
    assert "BEGIN:VALARM" not in download.text


def test_unit_trigger_from_offset_minutes():
    from maintenancehub_api.domain.ics import trigger_from_offset_minutes

    assert trigger_from_offset_minutes(-1440) == "-P1D"
    assert trigger_from_offset_minutes(-60) == "-PT1H"
    assert trigger_from_offset_minutes(-5) == "-PT5M"
    assert trigger_from_offset_minutes(-30) == "-PT30M"
    assert trigger_from_offset_minutes(0) == "PT0S"
