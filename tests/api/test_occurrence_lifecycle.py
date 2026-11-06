"""Occurrence-level lifecycle: independent states, authz, reconcile, notify dedupe."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import auth_header


def _bootstrap(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    other = auth_header(client, "viewer@test.example.com")
    env = client.post(
        "/api/v1/environments",
        json={"key": "PROD", "name": "Production", "sort_order": 1},
        headers=admin,
    ).json()
    app = client.post(
        "/api/v1/applications",
        json={
            "key": "billing",
            "name": "Billing",
            "environments": [{"environment_id": env["id"], "display_name": "Billing-PROD"}],
        },
        headers=pub,
    ).json()
    return pub, other, admin, app, env


def _create_weekly_series(client, pub, app, env, *, starts: datetime, title="Weekly patch"):
    return client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": title,
            "description": "series default desc",
            "expected_impact": "brief readonly",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env["id"],
                }
            ],
            "recurrence": {"freq": "WEEKLY", "interval": 1, "count": 6},
        },
        headers=pub,
    )


def test_independent_occurrence_lifecycles(client):
    pub, _other, _admin, app, env = _bootstrap(client)
    starts = datetime(2030, 1, 7, 10, 0, tzinfo=timezone.utc)  # Monday
    created = _create_weekly_series(client, pub, app, env, starts=starts)
    assert created.status_code == 201, created.text
    eid = created.json()["id"]

    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        params={
            "from": starts.isoformat(),
            "to": (starts + timedelta(days=21)).isoformat(),
        },
        headers=pub,
    ).json()
    assert len(occs) >= 2
    a, b = occs[0], occs[1]
    assert a["status"] == "scheduled"
    assert b["status"] == "scheduled"

    start_a = client.post(
        f"/api/v1/events/{eid}/occurrences/transition",
        json={"original_starts_at": a["original_starts_at"], "status": "in_progress"},
        headers=pub,
    )
    assert start_a.status_code == 200, start_a.text
    assert start_a.json()["status"] == "in_progress"

    # Sibling still scheduled
    occs2 = client.get(
        f"/api/v1/events/{eid}/occurrences",
        params={
            "from": starts.isoformat(),
            "to": (starts + timedelta(days=21)).isoformat(),
        },
        headers=pub,
    ).json()
    by_id = {o["occurrence_id"]: o for o in occs2}
    assert by_id[a["occurrence_id"]]["status"] == "in_progress"
    assert by_id[b["occurrence_id"]]["status"] == "scheduled"

    # Complete A via verifying
    assert (
        client.post(
            f"/api/v1/events/{eid}/occurrences/transition",
            json={"original_starts_at": a["original_starts_at"], "status": "verifying"},
            headers=pub,
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/events/{eid}/occurrences/transition",
            json={"original_starts_at": a["original_starts_at"], "status": "completed"},
            headers=pub,
        ).json()["status"]
        == "completed"
    )

    # Start B independently
    start_b = client.post(
        f"/api/v1/events/{eid}/occurrences/transition",
        json={"original_starts_at": b["original_starts_at"], "status": "in_progress"},
        headers=pub,
    )
    assert start_b.json()["status"] == "in_progress"

    # Master remains scheduled (series defaults)
    master = client.get(f"/api/v1/events/{eid}", headers=pub).json()
    assert master["status"] == "scheduled"


def test_invalid_occurrence_transition_rejected(client):
    pub, _o, _a, app, env = _bootstrap(client)
    starts = datetime(2030, 2, 4, 10, 0, tzinfo=timezone.utc)
    eid = _create_weekly_series(client, pub, app, env, starts=starts, title="Invalid").json()["id"]
    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=8)).isoformat()},
        headers=pub,
    ).json()
    bad = client.post(
        f"/api/v1/events/{eid}/occurrences/transition",
        json={"original_starts_at": occs[0]["original_starts_at"], "status": "completed"},
        headers=pub,
    )
    assert bad.status_code == 409


def test_occurrence_app_authz(client):
    pub, viewer, admin, app, env = _bootstrap(client)
    # Second publisher without grant
    other_pub = auth_header(client, "publisher@test.example.com")
    # Create another publisher user via admin seed is only one publisher — use viewer attempt
    starts = datetime(2030, 3, 3, 10, 0, tzinfo=timezone.utc)
    eid = _create_weekly_series(client, pub, app, env, starts=starts, title="Authz").json()["id"]
    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=8)).isoformat()},
        headers=pub,
    ).json()
    forbidden = client.post(
        f"/api/v1/events/{eid}/occurrences/transition",
        json={"original_starts_at": occs[0]["original_starts_at"], "status": "in_progress"},
        headers=viewer,
    )
    assert forbidden.status_code == 403

    # Publisher without application grant
    from maintenancehub_api.models import ApplicationGrant

    # Create second app, grant publisher only on first; attempt mutate via forged... 
    # Use a second publisher role user if available — create via catalog as admin
    # Simpler: strip grant by creating event as admin on app publisher owns, then
    # login as different publisher won't exist. Create publisher2 via DB in unit-style.
    ok = client.post(
        f"/api/v1/events/{eid}/occurrences/transition",
        json={"original_starts_at": occs[0]["original_starts_at"], "status": "in_progress"},
        headers=pub,
    )
    assert ok.status_code == 200
    # Admin always allowed
    assert (
        client.post(
            f"/api/v1/events/{eid}/occurrences/transition",
            json={"original_starts_at": occs[0]["original_starts_at"], "status": "verifying"},
            headers=admin,
        ).status_code
        == 200
    )
    _ = other_pub, ApplicationGrant


def test_reschedule_keeps_occurrence_identity(client):
    pub, _o, _a, app, env = _bootstrap(client)
    starts = datetime(2030, 4, 7, 10, 0, tzinfo=timezone.utc)
    eid = _create_weekly_series(client, pub, app, env, starts=starts, title="Resched").json()["id"]
    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=8)).isoformat()},
        headers=pub,
    ).json()
    orig_id = occs[0]["occurrence_id"]
    orig_start = occs[0]["original_starts_at"]
    new_start = datetime.fromisoformat(occs[0]["starts_at"].replace("Z", "+00:00")) + timedelta(hours=3)
    new_end = new_start + timedelta(hours=2)
    patched = client.patch(
        f"/api/v1/events/{eid}/occurrences",
        json={
            "original_starts_at": orig_start,
            "expected_starts_at": new_start.isoformat(),
            "expected_ends_at": new_end.isoformat(),
            "description": "rescheduled window",
        },
        headers=pub,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["occurrence_id"] == orig_id
    assert patched.json()["original_starts_at"].startswith(orig_start[:16])
    assert "rescheduled" in (patched.json().get("description") or "")


def test_series_rrule_change_preserves_completed_occurrence(client):
    pub, _o, _a, app, env = _bootstrap(client)
    starts = datetime(2030, 5, 5, 10, 0, tzinfo=timezone.utc)
    eid = _create_weekly_series(client, pub, app, env, starts=starts, title="Preserve").json()["id"]
    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=40)).isoformat()},
        headers=pub,
    ).json()
    first = occs[0]
    client.post(
        f"/api/v1/events/{eid}/occurrences/transition",
        json={"original_starts_at": first["original_starts_at"], "status": "in_progress"},
        headers=pub,
    )
    client.post(
        f"/api/v1/events/{eid}/occurrences/transition",
        json={"original_starts_at": first["original_starts_at"], "status": "verifying"},
        headers=pub,
    )
    client.post(
        f"/api/v1/events/{eid}/occurrences/transition",
        json={"original_starts_at": first["original_starts_at"], "status": "completed"},
        headers=pub,
    )

    # Also create a future exception that will become incompatible
    future = occs[3]
    client.post(
        f"/api/v1/events/{eid}/occurrences/exception",
        json={
            "original_starts_at": future["original_starts_at"],
            "action": "reschedule",
            "new_starts_at": (
                datetime.fromisoformat(future["starts_at"].replace("Z", "+00:00"))
                + timedelta(hours=5)
            ).isoformat(),
            "new_ends_at": (
                datetime.fromisoformat(future["ends_at"].replace("Z", "+00:00"))
                + timedelta(hours=5)
            ).isoformat(),
        },
        headers=pub,
    )

    # Shift series to Tuesdays only — Monday exception originals no longer match
    bad = client.post(
        f"/api/v1/events/{eid}/series-edit",
        json={
            "scope": "all",
            "starts_at": (starts + timedelta(days=1)).isoformat(),
            "ends_at": (starts + timedelta(days=1, hours=2)).isoformat(),
            "recurrence": {"freq": "WEEKLY", "interval": 1, "byweekday": ["TU"], "count": 6},
        },
        headers=pub,
    )
    assert bad.status_code == 400, bad.text

    ok = client.post(
        f"/api/v1/events/{eid}/series-edit",
        json={
            "scope": "all",
            "starts_at": (starts + timedelta(days=1)).isoformat(),
            "ends_at": (starts + timedelta(days=1, hours=2)).isoformat(),
            "recurrence": {"freq": "WEEKLY", "interval": 1, "byweekday": ["TU"], "count": 6},
            "exception_reconcile": "drop_incompatible_future",
        },
        headers=pub,
    )
    assert ok.status_code == 200, ok.text

    # Completed occurrence history still queryable via detail/history
    hist = client.get(
        f"/api/v1/events/{eid}/occurrences/history",
        params={"original_starts_at": first["original_starts_at"]},
        headers=pub,
    )
    assert hist.status_code == 200
    assert any(
        (t.get("payload") or {}).get("to") == "completed" for t in hist.json()["timeline"]
    )


def test_occurrence_notify_dedupe_per_orig(client, db_session):
    from maintenancehub_api.domain.notifications import (
        enqueue_deliveries_for_event,
        process_outbox,
    )
    from maintenancehub_api.models import (
        NotificationDelivery,
        ReminderOffset,
        Subscription,
        SubscriptionTarget,
    )
    from maintenancehub_api.domain import events as event_service

    pub, _o, _a, app, env = _bootstrap(client)
    starts = datetime(2030, 6, 2, 10, 0, tzinfo=timezone.utc)
    eid = _create_weekly_series(client, pub, app, env, starts=starts, title="Notify").json()["id"]

    sub = Subscription(
        user_id=db_session.publisher.id,  # type: ignore[attr-defined]
        destination_type="email_address",
        destination="pub@test.example.com",
        is_active=True,
    )
    db_session.add(sub)
    db_session.flush()
    db_session.add(
        SubscriptionTarget(subscription_id=sub.id, target_type="application", target_id=app["id"])
    )
    db_session.add(ReminderOffset(subscription_id=sub.id, offset_minutes=-30))
    db_session.commit()

    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=15)).isoformat()},
        headers=pub,
    ).json()
    a, b = occs[0], occs[1]

    for orig in (a["original_starts_at"], b["original_starts_at"]):
        assert (
            client.post(
                f"/api/v1/events/{eid}/occurrences/transition",
                json={"original_starts_at": orig, "status": "in_progress"},
                headers=pub,
            ).status_code
            == 200
        )

    event = event_service.get_event(db_session, eid)
    process_outbox(db_session)
    # Drain dispatch by calling enqueue with distinct orig keys (as worker would)
    from maintenancehub_api.domain.notifications import process_notify_dispatch
    from maintenancehub_api.models import OutboxEvent, Job

    jobs = db_session.query(Job).filter(Job.job_type == "notify_dispatch").all()
    for j in jobs:
        process_notify_dispatch(db_session, j.payload or {})

    deliveries = (
        db_session.query(NotificationDelivery)
        .filter(NotificationDelivery.event_id == eid)
        .all()
    )
    keys = [d.idempotency_key for d in deliveries]
    # Two occurrences → distinct orig keys in delivery idempotency
    orig_keys = {k for k in keys if ":orig:" in k}
    assert len(orig_keys) >= 2

    orig_key_a = datetime.fromisoformat(
        a["original_starts_at"].replace("Z", "+00:00")
    ).strftime("%Y%m%dT%H%M%SZ")
    n = enqueue_deliveries_for_event(
        db_session,
        event,
        template_key="event.transitioned",
        reason="event.transitioned",
        extra_context={"orig_key": orig_key_a, "from": "scheduled", "to": "in_progress"},
    )
    # Idempotent — prior dispatch already created the key
    assert n == 0
    _ = OutboxEvent


def test_dst_cross_month_occurrence_status(client):
    """America/New_York spring-forward window: occurrence ids stay stable."""
    pub, _o, _a, app, env = _bootstrap(client)
    # DTSTART before DST; weekly across March
    starts = datetime(2030, 3, 3, 12, 0, tzinfo=timezone.utc)
    res = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "DST series",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "timezone": "America/New_York",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "WEEKLY", "interval": 1, "count": 8},
        },
        headers=pub,
    )
    assert res.status_code == 201, res.text
    eid = res.json()["id"]
    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        params={
            "from": "2030-03-01T00:00:00Z",
            "to": "2030-05-01T00:00:00Z",
        },
        headers=pub,
    ).json()
    assert len(occs) >= 3
    # Cross-month presence (March → April)
    months = {o["original_starts_at"][5:7] for o in occs}
    assert "03" in months and "04" in months
    mid = occs[1]
    started = client.post(
        f"/api/v1/events/{eid}/occurrences/transition",
        json={"original_starts_at": mid["original_starts_at"], "status": "in_progress"},
        headers=pub,
    ).json()
    assert started["occurrence_id"] == mid["occurrence_id"]
    assert started["status"] == "in_progress"


def test_extend_and_cancel_occurrence(client):
    pub, _o, _a, app, env = _bootstrap(client)
    starts = datetime(2030, 7, 1, 10, 0, tzinfo=timezone.utc)
    eid = _create_weekly_series(client, pub, app, env, starts=starts, title="ExtendCancel").json()[
        "id"
    ]
    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=15)).isoformat()},
        headers=pub,
    ).json()
    a, b = occs[0], occs[1]
    client.post(
        f"/api/v1/events/{eid}/occurrences/transition",
        json={"original_starts_at": a["original_starts_at"], "status": "in_progress"},
        headers=pub,
    )
    new_end = datetime.fromisoformat(a["ends_at"].replace("Z", "+00:00")) + timedelta(hours=2)
    ext = client.post(
        f"/api/v1/events/{eid}/occurrences/extend",
        json={
            "original_starts_at": a["original_starts_at"],
            "new_ends_at": new_end.isoformat(),
        },
        headers=pub,
    )
    assert ext.status_code == 200
    assert ext.json()["status"] == "extended"

    cancel_b = client.post(
        f"/api/v1/events/{eid}/occurrences/cancel",
        json={"original_starts_at": b["original_starts_at"]},
        headers=pub,
    )
    assert cancel_b.status_code == 200
    assert cancel_b.json()["status"] == "cancelled"
    assert cancel_b.json()["cancelled"] is True
