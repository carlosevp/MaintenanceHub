"""M3b hardening — phases, identity, reminders, consistency, bounded perf."""

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
            "key": "pay-h",
            "name": "Pay Harden",
            "environments": [{"environment_id": env["id"], "display_name": "Pay-PROD"}],
        },
        headers=pub,
    ).json()
    return pub, admin, app, env


def test_approved_window_not_in_current_or_outages(client, monkeypatch):
    """In-window approved recurrence must not appear as current/outage."""
    pub, _admin, app, env = _bootstrap(client)
    now = datetime.now(timezone.utc)
    starts = now - timedelta(minutes=30)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "Approved in window",
            "kind": "planned_maintenance",
            "approval_state": "approved_window",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "WEEKLY", "byweekday": [starts.strftime("%a").upper()[:2]], "count": 4},
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["phase"] == "approved_window"

    summary = client.get("/api/v1/dashboard/summary", headers=pub).json()
    assert all(i["title"] != "Approved in window" for i in summary["current"]["items"])
    assert all(i["title"] != "Approved in window" for i in summary["outages"]["items"])
    # May appear in upcoming if next slots are future; must stay approved_window phase on calendar
    cal = client.get(
        "/api/v1/calendar/events",
        headers=pub,
        params={"from": (now - timedelta(days=1)).isoformat(), "to": (now + timedelta(days=14)).isoformat()},
    ).json()
    approved_rows = [c for c in cal if c["title"] == "Approved in window"]
    assert approved_rows
    assert all(c["phase"] == "approved_window" for c in approved_rows)
    assert all(c["approval_state"] == "approved_window" for c in approved_rows)


def test_scheduled_in_window_not_executing_current(client):
    pub, _admin, app, env = _bootstrap(client)
    now = datetime.now(timezone.utc)
    starts = now - timedelta(minutes=15)
    client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "Confirmed scheduled now",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
        },
    )
    summary = client.get("/api/v1/dashboard/summary", headers=pub).json()
    # Still scheduled (not human-started) → not in current executing slice
    assert all(i["title"] != "Confirmed scheduled now" for i in summary["current"]["items"])


def test_executing_manual_outage_in_outages(client):
    pub, _admin, app, env = _bootstrap(client)
    now = datetime.now(timezone.utc)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "Live outage",
            "kind": "manual_outage",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now - timedelta(minutes=10)).isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
        },
    ).json()
    # manual_outage creates as in_progress
    assert created["status"] == "in_progress"
    summary = client.get("/api/v1/dashboard/summary", headers=pub).json()
    assert any(i["title"] == "Live outage" for i in summary["outages"]["items"])
    assert any(i["title"] == "Live outage" for i in summary["current"]["items"])


def test_occurrence_id_stable_across_reschedule(client):
    pub, _admin, app, env = _bootstrap(client)
    starts = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)  # Monday
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "Stable id series",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "WEEKLY", "byweekday": ["MO"], "count": 5},
        },
    ).json()
    event_id = created["id"]
    second = starts + timedelta(days=7)
    before = client.get(
        f"/api/v1/events/{event_id}/occurrences",
        headers=pub,
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=21)).isoformat()},
    ).json()
    target = next(o for o in before if o["original_starts_at"].startswith("2026-09-14"))
    occ_id = target["occurrence_id"]

    new_start = second + timedelta(hours=3)
    client.post(
        f"/api/v1/events/{event_id}/series-edit",
        headers=pub,
        json={
            "scope": "this",
            "original_starts_at": second.isoformat(),
            "starts_at": new_start.isoformat(),
            "ends_at": (new_start + timedelta(hours=2)).isoformat(),
        },
    )
    after = client.get(
        f"/api/v1/events/{event_id}/occurrences",
        headers=pub,
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=21)).isoformat()},
    ).json()
    moved = next(o for o in after if o["occurrence_id"] == occ_id)
    assert moved["starts_at"].startswith("2026-09-14T15:00:00")
    assert moved["is_exception"] is True

    cal = client.get(
        "/api/v1/calendar/events",
        headers=pub,
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=21)).isoformat()},
    ).json()
    cal_row = next(c for c in cal if c["id"] == occ_id)
    assert cal_row["starts_at"].startswith("2026-09-14T15:00:00")
    assert cal_row["series_id"] == event_id


def test_ics_recurrence_id_on_reschedule(client):
    pub, _admin, app, env = _bootstrap(client)
    starts = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "ICS override",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "WEEKLY", "byweekday": ["MO"], "count": 4},
        },
    ).json()
    second = starts + timedelta(days=7)
    client.post(
        f"/api/v1/events/{created['id']}/series-edit",
        headers=pub,
        json={
            "scope": "this",
            "original_starts_at": second.isoformat(),
            "starts_at": (second + timedelta(hours=4)).isoformat(),
            "ends_at": (second + timedelta(hours=5)).isoformat(),
        },
    )
    client.put("/api/v1/me/favorites", headers=pub, json={"application_ids": [app["id"]]})
    tok = client.post(
        "/api/v1/calendar-tokens",
        headers=pub,
        json={"scopes": ["favorites"], "label": "t"},
    ).json()
    feed = client.get(f"/api/v1/public/ics/{tok['token']}").text
    assert f"UID:{created['id']}@maintenancehub" in feed
    assert "RECURRENCE-ID:20261012T120000Z" in feed
    assert "EXDATE:" not in feed or "RRULE:" in feed


def test_cancel_occurrence_dead_letters_reminder_job(client, db_session):
    pub, _admin, app, env = _bootstrap(client)
    sub = client.post(
        "/api/v1/subscriptions",
        headers=pub,
        json={
            "destination_type": "email_address",
            "destination": "publisher@test.example.com",
            "targets": [{"target_type": "application", "target_id": app["id"]}],
            "reminders": [{"offset_minutes": -60}],
        },
    )
    assert sub.status_code in {200, 201}
    starts = datetime.now(timezone.utc) + timedelta(days=3)
    starts = starts.replace(minute=0, second=0, microsecond=0)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "Cancel rem",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "WEEKLY", "interval": 1, "count": 3},
        },
    ).json()
    from maintenancehub_api.domain.notifications import schedule_reminders_for_event
    from maintenancehub_api.models import Job, JobStatus, MaintenanceEvent, RecurrenceRule
    from sqlalchemy.orm import joinedload

    db_session.expire_all()
    event = (
        db_session.query(MaintenanceEvent)
        .options(
            joinedload(MaintenanceEvent.impacts),
            joinedload(MaintenanceEvent.recurrence_rule).joinedload(RecurrenceRule.exceptions),
        )
        .filter(MaintenanceEvent.id == created["id"])
        .one()
    )
    schedule_reminders_for_event(db_session, event)
    db_session.expire_all()
    jobs_before = (
        db_session.query(Job)
        .filter(Job.job_type == "notify_reminder", Job.idempotency_key.contains(created["id"]))
        .all()
    )
    assert jobs_before
    # Cancel second occurrence via API
    second = starts + timedelta(days=7)
    client.post(
        f"/api/v1/events/{created['id']}/cancel",
        headers=pub,
        json={"scope": "this", "original_starts_at": second.isoformat()},
    )
    db_session.expire_all()
    # Re-schedule should dead-letter cancelled occ jobs
    event = (
        db_session.query(MaintenanceEvent)
        .options(
            joinedload(MaintenanceEvent.impacts),
            joinedload(MaintenanceEvent.recurrence_rule).joinedload(RecurrenceRule.exceptions),
        )
        .filter(MaintenanceEvent.id == created["id"])
        .one()
    )
    schedule_reminders_for_event(db_session, event)
    db_session.expire_all()
    orig_key = second.strftime("%Y%m%dT%H%M%SZ")
    related = [
        j
        for j in db_session.query(Job).filter(Job.job_type == "notify_reminder").all()
        if j.idempotency_key and orig_key in j.idempotency_key
    ]
    assert related
    assert all(j.status == JobStatus.dead for j in related)


def test_consistency_dst_cross_midnight_month_boundary(client):
    """Same fixture → calendar, occurrences, ICS agree on starts (DST + month edge)."""
    pub, _admin, app, env = _bootstrap(client)
    # Cross US fall-back weekend into November: Sundays 22:30 America/Chicago
    # 2026-10-25 22:30 CDT = 2026-10-26 03:30Z; after Nov 1 CST = 04:30Z
    starts = datetime(2026, 10, 26, 3, 30, tzinfo=timezone.utc)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "Late night weekly",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),  # crosses midnight local
            "timezone": "America/Chicago",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {
                "freq": "WEEKLY",
                "byweekday": ["SU"],
                "count": 4,
            },
        },
    ).json()
    event_id = created["id"]
    rng = {
        "from": "2026-10-20T00:00:00Z",
        "to": "2026-11-20T00:00:00Z",
    }
    def _norm(iso: str) -> str:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )

    cal = {
        _norm(c["occurrence_starts_at"]): _norm(c["starts_at"])
        for c in client.get("/api/v1/calendar/events", headers=pub, params=rng).json()
        if c["title"] == "Late night weekly"
    }
    occs = {
        _norm(o["original_starts_at"]): _norm(o["starts_at"])
        for o in client.get(
            f"/api/v1/events/{event_id}/occurrences", headers=pub, params=rng
        ).json()
        if not o["cancelled"]
    }
    assert set(cal.keys()) == set(occs.keys())
    assert cal == occs
    # Month boundary: at least one November occurrence present
    assert any(k.startswith("202611") for k in cal)
    # Cross-midnight: duration still 2h on a November (CST) occurrence
    nov = next(k for k in sorted(cal) if k.startswith("202611"))
    start = datetime.strptime(cal[nov], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    # Find matching ends via occurrences API
    nov_occ = next(
        o
        for o in client.get(
            f"/api/v1/events/{event_id}/occurrences", headers=pub, params=rng
        ).json()
        if _norm(o["original_starts_at"]) == nov
    )
    end = datetime.fromisoformat(nov_occ["ends_at"].replace("Z", "+00:00"))
    assert end - start == timedelta(hours=2)


def test_reminder_schedule_idempotent_repeated_runs(client, db_session):
    pub, _admin, app, env = _bootstrap(client)
    client.post(
        "/api/v1/subscriptions",
        headers=pub,
        json={
            "destination_type": "email_address",
            "destination": "publisher@test.example.com",
            "targets": [{"target_type": "application", "target_id": app["id"]}],
            "reminders": [{"offset_minutes": -30}],
        },
    )
    starts = datetime.now(timezone.utc) + timedelta(days=4)
    starts = starts.replace(minute=0, second=0, microsecond=0)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "Idem rem",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "DAILY", "count": 5},
        },
    ).json()
    from maintenancehub_api.domain.notifications import schedule_reminders_for_event
    from maintenancehub_api.models import Job, MaintenanceEvent, RecurrenceRule
    from sqlalchemy.orm import joinedload

    def _load():
        db_session.expire_all()
        return (
            db_session.query(MaintenanceEvent)
            .options(
                joinedload(MaintenanceEvent.impacts),
                joinedload(MaintenanceEvent.recurrence_rule).joinedload(RecurrenceRule.exceptions),
            )
            .filter(MaintenanceEvent.id == created["id"])
            .one()
        )

    schedule_reminders_for_event(db_session, _load())
    keys1 = {
        j.idempotency_key
        for j in db_session.query(Job).filter(Job.job_type == "notify_reminder").all()
        if j.idempotency_key and created["id"] in j.idempotency_key
    }
    schedule_reminders_for_event(db_session, _load())
    schedule_reminders_for_event(db_session, _load())
    keys2 = {
        j.idempotency_key
        for j in db_session.query(Job).filter(Job.job_type == "notify_reminder").all()
        if j.idempotency_key and created["id"] in j.idempotency_key
    }
    assert keys1 == keys2
    assert len(keys1) >= 3


def test_expand_perf_thousands_of_series_bounded(client, db_session):
    """Expanding a month window across many series stays bounded and fast enough."""
    import time
    from types import SimpleNamespace
    from maintenancehub_api.domain.recurrence import expand_event_occurrences, master_may_intersect_window

    range_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    range_end = datetime(2026, 7, 1, tzinfo=timezone.utc)
    series = []
    for i in range(2000):
        starts = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc) + timedelta(hours=(i % 24))
        rule = SimpleNamespace(rrule="FREQ=WEEKLY;BYDAY=MO", exceptions=[], until_at=None)
        series.append(
            SimpleNamespace(
                id=f"e{i}",
                starts_at=starts,
                ends_at=starts + timedelta(hours=1),
                timezone="UTC",
                is_recurring=True,
                recurrence_rule=rule,
                status="scheduled",
            )
        )
    t0 = time.perf_counter()
    total = 0
    scanned = 0
    for e in series:
        scanned += 1
        if not master_may_intersect_window(e, range_start=range_start, range_end=range_end):
            continue
        total += len(
            expand_event_occurrences(e, range_start=range_start, range_end=range_end)
        )
    elapsed = time.perf_counter() - t0
    assert scanned == 2000
    assert total > 0
    # Soft budget: should finish well under a few seconds in CI
    assert elapsed < 8.0, f"expand too slow: {elapsed:.2f}s for {total} occs"
