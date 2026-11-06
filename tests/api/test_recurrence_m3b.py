"""M3b API — create series, exceptions, calendar/ICS consistency, reminder idempotency."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import auth_header


def _bootstrap(client):
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
            "key": "pay",
            "name": "Pay",
            "environments": [{"environment_id": env["id"], "display_name": "Pay-PROD"}],
        },
        headers=pub,
    ).json()
    return pub, admin, app, env


def test_create_weekly_series_and_calendar_expand(client):
    pub, _admin, app, env = _bootstrap(client)
    starts = datetime(2026, 3, 1, 16, 0, tzinfo=timezone.utc)  # Sun 10:00 Chicago
    ends = starts + timedelta(hours=2)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "kind": "planned_maintenance",
            "title": "Weekly patch",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "timezone": "America/Chicago",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env["id"],
                }
            ],
            "recurrence": {"freq": "WEEKLY", "byweekday": ["SU"], "count": 6},
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["is_recurring"] is True
    assert body["recurrence"]["rrule"].startswith("FREQ=WEEKLY")
    assert "Every week" in body["recurrence"]["summary"]

    cal = client.get(
        "/api/v1/calendar/events",
        headers=pub,
        params={
            "view": "month",
            "from": "2026-03-01T00:00:00Z",
            "to": "2026-03-31T00:00:00Z",
        },
    )
    assert cal.status_code == 200
    occs = [c for c in cal.json() if c["title"] == "Weekly patch"]
    assert len(occs) >= 4
    assert all(c["is_occurrence"] for c in occs)
    # DST: Mar 1 16:00Z, Mar 8+ 15:00Z
    assert occs[0]["starts_at"].startswith("2026-03-01T16:00:00")
    mar8 = next(c for c in occs if "2026-03-08" in c["starts_at"])
    assert "T15:00:00" in mar8["starts_at"]


def test_cancel_one_occurrence_and_series_cancel(client):
    pub, _admin, app, env = _bootstrap(client)
    starts = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "Series A",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "WEEKLY", "byweekday": ["MO"], "count": 5},
        },
    ).json()
    event_id = created["id"]
    second = starts + timedelta(days=7)
    skipped = client.post(
        f"/api/v1/events/{event_id}/cancel",
        headers=pub,
        json={"scope": "this", "original_starts_at": second.isoformat()},
    )
    assert skipped.status_code == 200, skipped.text
    assert any(ex["action"] == "cancel" for ex in skipped.json()["recurrence"]["exceptions"])

    occs = client.get(
        f"/api/v1/events/{event_id}/occurrences",
        headers=pub,
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=30)).isoformat()},
    ).json()
    cancelled = [o for o in occs if o["cancelled"]]
    assert len(cancelled) == 1

    # Calendar should not show cancelled
    cal = client.get(
        "/api/v1/calendar/events",
        headers=pub,
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=30)).isoformat()},
    ).json()
    titles = [(c["starts_at"], c["title"]) for c in cal if c["title"] == "Series A"]
    assert not any(second.strftime("%Y-%m-%d") in s for s, _ in titles)


def test_two_concurrent_series_and_preview(client):
    pub, _admin, app, env = _bootstrap(client)
    starts = datetime(2026, 5, 4, 10, 0, tzinfo=timezone.utc)
    for title, byday in (("Series Blue", ["MO"]), ("Series Green", ["WE"])):
        res = client.post(
            "/api/v1/events",
            headers=pub,
            json={
                "title": title,
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
                "recurrence": {"freq": "WEEKLY", "byweekday": byday, "count": 4},
            },
        )
        assert res.status_code == 201, res.text

    cal = client.get(
        "/api/v1/calendar/events",
        headers=pub,
        params={
            "from": "2026-05-01T00:00:00Z",
            "to": "2026-05-31T00:00:00Z",
        },
    ).json()
    blues = [c for c in cal if c["title"] == "Series Blue"]
    greens = [c for c in cal if c["title"] == "Series Green"]
    assert len(blues) >= 3 and len(greens) >= 3

    preview = client.post(
        "/api/v1/events/recurrence/preview",
        headers=pub,
        json={
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "recurrence": {"freq": "MONTHLY", "bymonthday": 4, "count": 3},
            "count": 3,
        },
    )
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["occurrences"]) == 3


def test_reminder_idempotency_per_occurrence(client, db_session):
    pub, admin, app, env = _bootstrap(client)
    # subscription with reminder
    sub = client.post(
        "/api/v1/subscriptions",
        headers=pub,
        json={
            "destination_type": "email_address",
            "destination": "publisher@test.example.com",
            "digest_mode": "none",
            "targets": [{"target_type": "application", "target_id": app["id"]}],
            "reminders": [{"offset_minutes": -60}],
        },
    )
    assert sub.status_code in {200, 201}, sub.text
    sub_id = sub.json()["id"]
    rem = client.put(
        f"/api/v1/subscriptions/{sub_id}/reminders",
        headers=pub,
        json=[{"offset_minutes": -60}],
    )
    assert rem.status_code == 200, rem.text

    starts = datetime.now(timezone.utc) + timedelta(days=2)
    starts = starts.replace(minute=0, second=0, microsecond=0)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "Remind series",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "WEEKLY", "interval": 1, "count": 3},
        },
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    from maintenancehub_api.domain.notifications import schedule_reminders_for_event
    from maintenancehub_api.models import Job, MaintenanceEvent, RecurrenceRule
    from sqlalchemy.orm import joinedload

    db_session.expire_all()
    event = (
        db_session.query(MaintenanceEvent)
        .options(
            joinedload(MaintenanceEvent.impacts),
            joinedload(MaintenanceEvent.recurrence_rule).joinedload(RecurrenceRule.exceptions),
        )
        .filter(MaintenanceEvent.id == event_id)
        .first()
    )
    assert event is not None
    n1 = schedule_reminders_for_event(db_session, event)
    db_session.expire_all()
    event = (
        db_session.query(MaintenanceEvent)
        .options(
            joinedload(MaintenanceEvent.impacts),
            joinedload(MaintenanceEvent.recurrence_rule).joinedload(RecurrenceRule.exceptions),
        )
        .filter(MaintenanceEvent.id == event_id)
        .first()
    )
    n2 = schedule_reminders_for_event(db_session, event)
    keys = [
        j.idempotency_key
        for j in db_session.query(Job).filter(Job.job_type == "notify_reminder").all()
        if j.idempotency_key and event_id in j.idempotency_key
    ]
    assert len(keys) == len(set(keys))
    assert n1 >= 1
    assert n2 == 0 or all(
        db_session.query(Job).filter(Job.idempotency_key == k).count() == 1 for k in keys
    )


def test_ics_includes_rrule_and_exdate(client):
    pub, _admin, app, env = _bootstrap(client)
    starts = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "ICS series",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "WEEKLY", "byweekday": ["MO"], "count": 4},
        },
    ).json()
    client.post(
        f"/api/v1/events/{created['id']}/cancel",
        headers=pub,
        json={
            "scope": "this",
            "original_starts_at": (starts + timedelta(days=7)).isoformat(),
        },
    )
    # favorite so ICS includes app
    client.put(
        "/api/v1/me/favorites",
        headers=pub,
        json={"application_ids": [app["id"]]},
    )
    tok = client.post(
        "/api/v1/calendar-tokens",
        headers=pub,
        json={"label": "test", "scopes": ["favorites"]},
    )
    assert tok.status_code == 201, tok.text
    raw = tok.json()["token"]
    feed = client.get(f"/api/v1/public/ics/{raw}")
    assert feed.status_code == 200, feed.text
    text = feed.text
    assert "RRULE:FREQ=WEEKLY" in text
    assert "EXDATE:" in text


def test_approved_window_series_distinct_from_confirmed(client):
    pub, _admin, app, env = _bootstrap(client)
    starts = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "Approved recurring",
            "approval_state": "approved_window",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "MONTHLY", "bymonthday": 1, "count": 3},
        },
    )
    assert created.status_code == 201
    assert created.json()["approval_state"] == "approved_window"
    cal = client.get(
        "/api/v1/calendar/events",
        headers=pub,
        params={"from": "2026-08-01T00:00:00Z", "to": "2026-11-01T00:00:00Z"},
    ).json()
    items = [c for c in cal if c["title"] == "Approved recurring"]
    assert items and all(i["approval_state"] == "approved_window" for i in items)
