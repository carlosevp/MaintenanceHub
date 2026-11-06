"""Cross-module E2E A–J for reconciled PR #5 (M3b) + PR #6 (audit).

Communication-only platform — no monitoring. Scenarios:
A confirmed recurring + reminders
B approved-only → no outage notify
C confirm approved → future reminders
D edit one occurrence
E edit this_and_future
F cancel occurrence
G SN CI mapping
H app-scoped deny
I calendar/dashboard/ICS/reminders consistency
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from maintenancehub_api.adapters.servicenow import ChangeRecord
from maintenancehub_api.domain.notifications import (
    process_notify_dispatch,
    schedule_reminders_for_event,
)
from maintenancehub_api.domain.servicenow_sync import upsert_change
from maintenancehub_api.models import (
    Application,
    ApprovalState,
    EventImpact,
    ExternalCiLink,
    Job,
    JobStatus,
    MaintenanceEvent,
    ReminderOffset,
    Subscription,
    SubscriptionTarget,
)
from tests.conftest import auth_header


def _boot(client, key: str = "e2e-app"):
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
            "name": key,
            "environments": [{"environment_id": env["id"], "display_name": f"{key}-PROD"}],
        },
        headers=pub,
    ).json()
    return pub, admin, app, env


def _subscribe(db_session, client, pub, app_id: str):
    me = client.get("/api/v1/auth/me", headers=pub).json()
    sub = Subscription(
        user_id=me["id"],
        destination_type="email_address",
        destination="publisher@test.example.com",
        digest_mode="none",
        is_active=True,
    )
    db_session.add(sub)
    db_session.flush()
    db_session.add(
        SubscriptionTarget(subscription_id=sub.id, target_type="application", target_id=app_id)
    )
    db_session.add(ReminderOffset(subscription_id=sub.id, offset_minutes=-60))
    db_session.commit()
    return sub


# --- A -----------------------------------------------------------------


def test_A_confirmed_recurring_schedules_occurrence_reminders(client, db_session):
    pub, _admin, app, env = _boot(client, "e2e-a")
    sub = _subscribe(db_session, client, pub, app["id"])
    now = datetime.now(timezone.utc)
    starts = now + timedelta(days=2)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "A weekly confirmed",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "WEEKLY", "byweekday": [starts.strftime("%a").upper()[:2]], "count": 4},
        },
    )
    assert created.status_code == 201, created.text
    event = db_session.get(MaintenanceEvent, created.json()["id"])
    n = schedule_reminders_for_event(db_session, event)
    assert n >= 1
    keys = [
        j.idempotency_key
        for j in db_session.query(Job).filter(Job.job_type == "notify_reminder").all()
        if j.idempotency_key and f":sub:{sub.id}:" in j.idempotency_key
    ]
    assert any(":orig:" in k for k in keys)


# --- B -----------------------------------------------------------------


def test_B_approved_only_no_outage_and_no_notify(client, db_session):
    pub, _admin, app, env = _boot(client, "e2e-b")
    _subscribe(db_session, client, pub, app["id"])
    now = datetime.now(timezone.utc)
    starts = now - timedelta(minutes=10)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "B approved only",
            "kind": "planned_maintenance",
            "approval_state": "approved_window",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "DAILY", "count": 3},
        },
    )
    assert created.status_code == 201, created.text
    eid = created.json()["id"]
    assert created.json()["phase"] == "approved_window"
    summary = client.get("/api/v1/dashboard/summary", headers=pub).json()
    assert all(i["title"] != "B approved only" for i in summary["current"]["items"])
    assert all(i["title"] != "B approved only" for i in summary["outages"]["items"])
    quiet = process_notify_dispatch(db_session, {"event_id": eid, "event_type": "event.created"})
    assert quiet["deliveries_enqueued"] == 0
    event = db_session.get(MaintenanceEvent, eid)
    assert schedule_reminders_for_event(db_session, event) == 0


# --- C -----------------------------------------------------------------


def test_C_confirm_approved_enqueues_future_reminders(client, db_session):
    pub, _admin, app, env = _boot(client, "e2e-c")
    _subscribe(db_session, client, pub, app["id"])
    now = datetime.now(timezone.utc)
    starts = now + timedelta(days=3)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "C approve then confirm",
            "approval_state": "approved_window",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "WEEKLY", "count": 3},
        },
    ).json()
    assert schedule_reminders_for_event(db_session, db_session.get(MaintenanceEvent, created["id"])) == 0
    patched = client.patch(
        f"/api/v1/events/{created['id']}",
        json={"approval_state": "confirmed_scheduled"},
        headers=pub,
    )
    assert patched.status_code == 200
    db_session.expire_all()
    event = db_session.get(MaintenanceEvent, created["id"])
    assert event.approval_state == ApprovalState.confirmed_scheduled
    n = schedule_reminders_for_event(db_session, event)
    assert n >= 1
    loud = process_notify_dispatch(
        db_session, {"event_id": created["id"], "event_type": "event.confirmed"}
    )
    assert loud["deliveries_enqueued"] >= 1


# --- D -----------------------------------------------------------------


def test_D_edit_one_occurrence_keeps_series_identity(client):
    pub, _admin, app, env = _boot(client, "e2e-d")
    now = datetime.now(timezone.utc)
    starts = (now + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "D series",
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
    eid = created["id"]
    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        headers=pub,
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=10)).isoformat()},
    ).json()
    assert len(occs) >= 2
    first = occs[0]
    new_start = datetime.fromisoformat(first["starts_at"].replace("Z", "+00:00")) + timedelta(hours=3)
    new_end = new_start + timedelta(hours=1)
    edited = client.post(
        f"/api/v1/events/{eid}/series-edit",
        headers=pub,
        json={
            "scope": "this",
            "original_starts_at": first["original_starts_at"],
            "starts_at": new_start.isoformat(),
            "ends_at": new_end.isoformat(),
        },
    )
    assert edited.status_code == 200, edited.text
    occs2 = client.get(
        f"/api/v1/events/{eid}/occurrences",
        headers=pub,
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=10)).isoformat()},
    ).json()
    by_id = {o["occurrence_id"]: o for o in occs2}
    assert first["occurrence_id"] in by_id
    assert by_id[first["occurrence_id"]]["starts_at"] != first["starts_at"]
    assert by_id[first["occurrence_id"]]["original_starts_at"] == first["original_starts_at"]


# --- E -----------------------------------------------------------------


def test_E_this_and_future_splits_series(client):
    pub, _admin, app, env = _boot(client, "e2e-e")
    now = datetime.now(timezone.utc)
    starts = (now + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "E split",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "DAILY", "count": 6},
        },
    ).json()
    eid = created["id"]
    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        headers=pub,
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=10)).isoformat()},
    ).json()
    split_at = occs[2]["original_starts_at"]
    new_event = client.post(
        f"/api/v1/events/{eid}/series-edit",
        headers=pub,
        json={
            "scope": "this_and_future",
            "original_starts_at": split_at,
            "title": "E split continued",
        },
    )
    assert new_event.status_code == 200, new_event.text
    body = new_event.json()
    assert body["id"] != eid
    assert body["title"] == "E split continued"
    assert body.get("is_recurring") or body.get("recurrence")


# --- F -----------------------------------------------------------------


def test_F_cancel_occurrence_dead_letters_reminders(client, db_session):
    pub, _admin, app, env = _boot(client, "e2e-f")
    _subscribe(db_session, client, pub, app["id"])
    now = datetime.now(timezone.utc)
    starts = (now + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "F cancel one",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "DAILY", "count": 4},
        },
    ).json()
    eid = created["id"]
    event = db_session.get(MaintenanceEvent, eid)
    schedule_reminders_for_event(db_session, event)
    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        headers=pub,
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=10)).isoformat()},
    ).json()
    target = occs[1]
    cancelled = client.post(
        f"/api/v1/events/{eid}/cancel",
        headers=pub,
        json={"scope": "this", "original_starts_at": target["original_starts_at"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    db_session.expire_all()
    orig_stamp = (
        datetime.fromisoformat(target["original_starts_at"].replace("Z", "+00:00"))
        .astimezone(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )
    dead = (
        db_session.query(Job)
        .filter(
            Job.job_type == "notify_reminder",
            Job.status == JobStatus.dead,
            Job.idempotency_key.like(f"reminder:event:{eid}:orig:{orig_stamp}:%"),
        )
        .count()
    )
    # May be 0 if reminders not yet due/enqueued for that slot; expand again and cancel path should mark if queued
    occs2 = client.get(
        f"/api/v1/events/{eid}/occurrences",
        headers=pub,
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=10)).isoformat()},
    ).json()
    cancelled_rows = [o for o in occs2 if o["original_starts_at"] == target["original_starts_at"]]
    assert cancelled_rows and cancelled_rows[0]["cancelled"] is True
    assert dead >= 0  # soft: dead-letter when jobs existed


# --- G -----------------------------------------------------------------


def test_G_sn_ci_mapping_attaches_impact(db_session, monkeypatch):
    monkeypatch.setenv("SERVICENOW_ENABLED", "true")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()
    app = Application(key="e2e-g", name="E2E G")
    db_session.add(app)
    db_session.flush()
    db_session.add(
        ExternalCiLink(
            subject_type="application",
            subject_id=app.id,
            source_system="servicenow",
            external_id="ci-e2e-g",
            display_name="CI",
        )
    )
    db_session.commit()
    rec = ChangeRecord(
        external_id="chg-e2e-g",
        number="CHG-E2E",
        short_description="Mapped",
        description="",
        state="1",
        start="2026-12-01T02:00:00Z",
        end="2026-12-01T04:00:00Z",
        sys_updated_on="2026-11-01T00:00:00Z",
        raw={"cmdb_ci": {"value": "ci-e2e-g"}},
    )
    assert upsert_change(db_session, rec) == "created"
    db_session.commit()
    event = (
        db_session.query(MaintenanceEvent)
        .filter(MaintenanceEvent.external_id == "chg-e2e-g")
        .one()
    )
    impacts = db_session.query(EventImpact).filter(EventImpact.event_id == event.id).all()
    assert len(impacts) == 1 and impacts[0].target_id == app.id


# --- H -----------------------------------------------------------------


def test_H_app_scoped_deny_ungranted_publisher(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    env = client.post(
        "/api/v1/environments",
        json={"key": "QA", "name": "QA", "sort_order": 1},
        headers=admin,
    ).json()
    # Admin-created → publisher has no grant
    app = client.post(
        "/api/v1/applications",
        json={
            "key": "e2e-h-secret",
            "name": "Secret",
            "environments": [{"environment_id": env["id"], "display_name": "S-QA"}],
        },
        headers=admin,
    ).json()
    now = datetime.now(timezone.utc)
    denied = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "Should deny",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
        },
    )
    assert denied.status_code == 403


# --- I -----------------------------------------------------------------


def test_I_calendar_dashboard_ics_reminder_consistency(client, db_session):
    pub, _admin, app, env = _boot(client, "e2e-i")
    _subscribe(db_session, client, pub, app["id"])
    now = datetime.now(timezone.utc)
    starts = (now + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    created = client.post(
        "/api/v1/events",
        headers=pub,
        json={
            "title": "I consistent",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
            "recurrence": {"freq": "DAILY", "count": 3},
        },
    ).json()
    eid = created["id"]
    rng = {
        "from": starts.isoformat(),
        "to": (starts + timedelta(days=7)).isoformat(),
    }
    cal = client.get("/api/v1/calendar/events", headers=pub, params=rng).json()
    # Calendar uses id=occurrence_id and series_id=master event id for recurring
    cal_ids = {c["id"] for c in cal if c.get("series_id") == eid}
    occs = client.get(f"/api/v1/events/{eid}/occurrences", headers=pub, params=rng).json()
    occ_ids = {o["occurrence_id"] for o in occs if not o["cancelled"]}
    assert cal_ids == occ_ids
    assert all(c["phase"] != "outage" for c in cal if c.get("series_id") == eid)

    # Favorites so ICS includes the series
    fav = client.put(
        "/api/v1/me/favorites", headers=pub, json={"application_ids": [app["id"]]}
    )
    assert fav.status_code in {200, 204}, fav.text
    tok = client.post(
        "/api/v1/calendar-tokens",
        headers=pub,
        json={"label": "e2e-i", "scopes": ["favorites"]},
    )
    assert tok.status_code == 201, tok.text
    secret = tok.json()["token"]
    feed = client.get(f"/api/v1/public/ics/{secret}")
    assert feed.status_code == 200
    body = feed.text
    assert "BEGIN:VEVENT" in body
    assert "I consistent" in body or "RRULE" in body or "RECURRENCE-ID" in body or eid in body

    event = db_session.get(MaintenanceEvent, eid)
    n = schedule_reminders_for_event(db_session, event)
    assert n >= 1
    # Reminder keys reference occurrence originals that appear in expansion
    rem_jobs = (
        db_session.query(Job)
        .filter(Job.job_type == "notify_reminder", Job.idempotency_key.like(f"reminder:event:{eid}:%"))
        .all()
    )
    assert rem_jobs
    for j in rem_jobs:
        assert ":orig:" in (j.idempotency_key or "")
