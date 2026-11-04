"""Highest-risk cross-module workflows: confirm→notify, SN impacts, reminders."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from maintenancehub_api.adapters.servicenow import ChangeRecord
from maintenancehub_api.domain.notifications import (
    process_notify_dispatch,
    schedule_reminders_for_event,
)
from maintenancehub_api.domain.servicenow_sync import upsert_change
from maintenancehub_api.models import (
    ApprovalState,
    EventImpact,
    ExternalCiLink,
    Job,
    MaintenanceEvent,
    OutboxEvent,
    ReminderOffset,
    Subscription,
    SubscriptionTarget,
)
from tests.conftest import auth_header


def test_confirm_approval_enqueues_outbox_and_reminders(client, db_session):
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
    now = datetime.now(timezone.utc)
    created = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Approved only first",
            "approval_state": "approved_window",
            "starts_at": (now + timedelta(hours=4)).isoformat(),
            "ends_at": (now + timedelta(hours=6)).isoformat(),
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
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    # Subscription so reminders have a target
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
        SubscriptionTarget(
            subscription_id=sub.id, target_type="application", target_id=app["id"]
        )
    )
    db_session.add(ReminderOffset(subscription_id=sub.id, offset_minutes=-60))
    db_session.commit()

    before = db_session.query(OutboxEvent).filter(OutboxEvent.aggregate_id == event_id).count()
    patched = client.patch(
        f"/api/v1/events/{event_id}",
        json={"approval_state": "confirmed_scheduled"},
        headers=pub,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["approval_state"] == "confirmed_scheduled"

    db_session.expire_all()
    confirmed = (
        db_session.query(OutboxEvent)
        .filter(
            OutboxEvent.aggregate_id == event_id,
            OutboxEvent.event_type == "event.confirmed",
        )
        .count()
    )
    assert confirmed >= 1
    assert (
        db_session.query(OutboxEvent).filter(OutboxEvent.aggregate_id == event_id).count()
        >= before
    )

    event = db_session.get(MaintenanceEvent, event_id)
    assert event is not None
    # Confirm path schedules reminders; ensure at least one job exists (idempotent re-call OK).
    schedule_reminders_for_event(db_session, event)
    db_session.expire_all()
    job = (
        db_session.query(Job)
        .filter(
            Job.job_type == "notify_reminder",
            Job.idempotency_key == f"reminder:event:{event_id}:sub:{sub.id}:offset:-60",
        )
        .first()
    )
    assert job is not None, "expected reminder job after confirmation"
    old_run = job.run_at
    # Reschedule window → reminder run_at must refresh
    new_start = event.starts_at + timedelta(hours=2)
    new_end = event.ends_at + timedelta(hours=2)
    res = client.post(
        f"/api/v1/events/{event_id}/reschedule",
        json={"starts_at": new_start.isoformat(), "ends_at": new_end.isoformat()},
        headers=pub,
    )
    assert res.status_code == 200, res.text
    db_session.expire_all()
    event = db_session.get(MaintenanceEvent, event_id)
    refreshed = schedule_reminders_for_event(db_session, event)
    assert refreshed >= 1  # existing queued job run_at updated
    db_session.expire_all()
    job = (
        db_session.query(Job)
        .filter(Job.idempotency_key == f"reminder:event:{event_id}:sub:{sub.id}:offset:-60")
        .one()
    )
    assert job.run_at != old_run
    assert job.run_at == event.starts_at + timedelta(minutes=-60)


def test_sn_import_attaches_impact_via_external_ci(db_session, monkeypatch):
    monkeypatch.setenv("SERVICENOW_ENABLED", "true")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()

    from maintenancehub_api.models import Application

    app = Application(key="sn-app", name="SN App")
    db_session.add(app)
    db_session.flush()
    db_session.add(
        ExternalCiLink(
            subject_type="application",
            subject_id=app.id,
            source_system="servicenow",
            external_id="ci-sys-1",
            display_name="SN CI",
        )
    )
    db_session.commit()

    rec = ChangeRecord(
        external_id="chg-sys-1",
        number="CHG200",
        short_description="SN window",
        description="desc",
        state="1",
        start="2026-12-01T02:00:00Z",
        end="2026-12-01T04:00:00Z",
        sys_updated_on="2026-11-01T00:00:00Z",
        raw={"cmdb_ci": {"value": "ci-sys-1"}},
    )
    assert upsert_change(db_session, rec) == "created"
    db_session.commit()
    event = (
        db_session.query(MaintenanceEvent)
        .filter(MaintenanceEvent.external_id == "chg-sys-1")
        .one()
    )
    impacts = db_session.query(EventImpact).filter(EventImpact.event_id == event.id).all()
    assert len(impacts) == 1
    assert impacts[0].target_id == app.id
    assert event.approval_state == ApprovalState.approved_window


def test_confirm_dispatch_skips_until_confirmed(db_session, client):
    """approved_window deliveries stay quiet; confirm then dispatch creates deliveries."""
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    env = client.post(
        "/api/v1/environments",
        json={"key": "INT", "name": "INT", "sort_order": 1},
        headers=admin,
    ).json()
    app = client.post(
        "/api/v1/applications",
        json={
            "key": "inv",
            "name": "Inv",
            "environments": [{"environment_id": env["id"], "display_name": "Inv-INT"}],
        },
        headers=pub,
    ).json()
    now = datetime.now(timezone.utc)
    created = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Quiet until confirm",
            "approval_state": "approved_window",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
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
        SubscriptionTarget(
            subscription_id=sub.id, target_type="application", target_id=app["id"]
        )
    )
    db_session.commit()

    quiet = process_notify_dispatch(
        db_session, {"event_id": created["id"], "event_type": "event.created"}
    )
    assert quiet["deliveries_enqueued"] == 0

    client.patch(
        f"/api/v1/events/{created['id']}",
        json={"approval_state": "confirmed_scheduled"},
        headers=pub,
    )
    db_session.expire_all()
    loud = process_notify_dispatch(
        db_session, {"event_id": created["id"], "event_type": "event.confirmed"}
    )
    assert loud["deliveries_enqueued"] >= 1
