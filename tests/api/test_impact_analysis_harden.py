"""M14 harden — preview privacy, server validation, selection revision, notifications."""

from __future__ import annotations


from sqlalchemy.orm import Session

from maintenancehub_api.models import (
    Job,
    JobStatus,
    OutboxEvent,
    ReminderOffset,
    Subscription,
    SubscriptionTarget,
)
from tests.api.test_impact_analysis import _catalog, _grant_publisher, _window
from tests.conftest import auth_header


def test_viewer_cannot_preview(client):
    admin = auth_header(client, "admin@test.example.com")
    viewer = auth_header(client, "viewer@test.example.com")
    apps, envs, oracle = _catalog(client, admin)
    starts, ends = _window()
    res = client.post(
        "/api/v1/impact-analysis/preview",
        json={
            "seeds": [
                {
                    "target_type": "infra_component",
                    "target_id": oracle.id,
                    "environment_id": envs["NON-PROD"]["id"],
                }
            ],
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
        },
        headers=viewer,
    )
    assert res.status_code == 403, res.text


def test_cross_app_preview_denied_without_grant(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    apps, envs, _ = _catalog(client, admin, with_oracle=False)
    starts, ends = _window()
    res = client.post(
        "/api/v1/impact-analysis/preview",
        json={
            "seeds": [
                {
                    "target_type": "application",
                    "target_id": apps["claims"]["id"],
                    "environment_id": envs["INT"]["id"],
                }
            ],
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
        },
        headers=pub,
    )
    assert res.status_code == 403, res.text


def test_manual_add_requires_grant_and_real_ids(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    apps, envs, oracle = _catalog(client, admin)
    _grant_publisher(client, apps["claims"]["id"])
    starts, ends = _window()
    event = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Oracle owned via creator",
            "approval_state": "approved_window",
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "infra_component",
                    "target_id": oracle.id,
                    "environment_id": envs["NON-PROD"]["id"],
                }
            ],
        },
        headers=admin,
    ).json()
    # Publisher is not creator and has no infra ownership path beyond seed apps empty
    # Admin-created infra event: publisher cannot confirm unless creator/admin
    preview = client.post(
        "/api/v1/impact-analysis/preview",
        json={
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "event_id": event["id"],
        },
        headers=admin,
    ).json()
    denied_manual = client.post(
        f"/api/v1/impact-analysis/events/{event['id']}/confirm",
        json={
            "revision_token": preview["revision_token"],
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "manual_additions": [
                {
                    "target_type": "application",
                    "target_id": apps["lonely"]["id"],
                    "environment_id": envs["PROD"]["id"],
                }
            ],
            "include_downstream": [
                {
                    "target_type": s["target_type"],
                    "target_id": s["target_id"],
                    "environment_id": s.get("environment_id"),
                }
                for s in preview["suggested_downstream"]
            ],
            "publish": False,
        },
        headers=pub,
    )
    assert denied_manual.status_code == 403, denied_manual.text

    # Unknown id
    bad_id = client.post(
        f"/api/v1/impact-analysis/events/{event['id']}/confirm",
        json={
            "revision_token": preview["revision_token"],
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "manual_additions": [
                {
                    "target_type": "application",
                    "target_id": "00000000-0000-0000-0000-000000000099",
                    "environment_id": envs["PROD"]["id"],
                }
            ],
            "include_downstream": [],
            "publish": False,
        },
        headers=admin,
    )
    assert bad_id.status_code == 400, bad_id.text


def test_selection_change_without_repreview_rejected(client):
    admin = auth_header(client, "admin@test.example.com")
    apps, envs, oracle = _catalog(client, admin)
    starts, ends = _window()
    event = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Selection gate",
            "approval_state": "approved_window",
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "infra_component",
                    "target_id": oracle.id,
                    "environment_id": envs["NON-PROD"]["id"],
                }
            ],
        },
        headers=admin,
    ).json()
    preview = client.post(
        "/api/v1/impact-analysis/preview",
        json={
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "event_id": event["id"],
        },
        headers=admin,
    ).json()
    # Drop all suggested includes without updating token via exclusions/re-preview
    bad = client.post(
        f"/api/v1/impact-analysis/events/{event['id']}/confirm",
        json={
            "revision_token": preview["revision_token"],
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "include_downstream": [],
            "publish": True,
        },
        headers=admin,
    )
    assert bad.status_code == 409, bad.text


def test_impact_change_reconciles_reminders_no_notify_excluded(client):
    admin = auth_header(client, "admin@test.example.com")
    apps, envs, oracle = _catalog(client, admin)
    starts, ends = _window(offset_h=72)
    db: Session = client.db
    sub = Subscription(
        user_id=db.admin.id,
        destination_type="email_address",
        destination="claims-watch@example.com",
        is_active=True,
    )
    db.add(sub)
    db.flush()
    db.add(
        SubscriptionTarget(
            subscription_id=sub.id,
            target_type="app_environment",
            target_id=f"{apps['claims']['id']}:{envs['INT']['id']}",
        )
    )
    db.add(ReminderOffset(subscription_id=sub.id, offset_minutes=-60))
    billing_sub = Subscription(
        user_id=db.admin.id,
        destination_type="email_address",
        destination="billing-watch@example.com",
        is_active=True,
    )
    db.add(billing_sub)
    db.flush()
    db.add(
        SubscriptionTarget(
            subscription_id=billing_sub.id,
            target_type="app_environment",
            target_id=f"{apps['billing']['id']}:{envs['DEV']['id']}",
        )
    )
    db.add(ReminderOffset(subscription_id=billing_sub.id, offset_minutes=-60))
    db.commit()

    event = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Impact change notify",
            "approval_state": "approved_window",
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "infra_component",
                    "target_id": oracle.id,
                    "environment_id": envs["NON-PROD"]["id"],
                }
            ],
        },
        headers=admin,
    ).json()
    preview = client.post(
        "/api/v1/impact-analysis/preview",
        json={
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "event_id": event["id"],
        },
        headers=admin,
    ).json()
    include = [
        {
            "target_type": s["target_type"],
            "target_id": s["target_id"],
            "environment_id": s.get("environment_id"),
        }
        for s in preview["suggested_downstream"]
    ]
    conf = client.post(
        f"/api/v1/impact-analysis/events/{event['id']}/confirm",
        json={
            "revision_token": preview["revision_token"],
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "include_downstream": include,
            "publish": True,
        },
        headers=admin,
    )
    assert conf.status_code == 200, conf.text
    jobs_after_publish = (
        db.query(Job)
        .filter(Job.job_type == "notify_reminder", Job.status == JobStatus.queued)
        .count()
    )
    assert jobs_after_publish >= 1

    # Re-preview excluding billing
    excl = [
        {
            "target_type": "application",
            "target_id": apps["billing"]["id"],
            "environment_id": envs["DEV"]["id"],
            "reason": "Not on this window",
        }
    ]
    preview2 = client.post(
        "/api/v1/impact-analysis/preview",
        json={
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "event_id": event["id"],
            "exclusions": excl,
        },
        headers=admin,
    ).json()
    include2 = [
        {
            "target_type": s["target_type"],
            "target_id": s["target_id"],
            "environment_id": s.get("environment_id"),
        }
        for s in preview2["suggested_downstream"]
        if s["selection"] != "excluded"
    ]
    conf2 = client.post(
        f"/api/v1/impact-analysis/events/{event['id']}/confirm",
        json={
            "revision_token": preview2["revision_token"],
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "exclusions": excl,
            "include_downstream": include2,
            "publish": True,
        },
        headers=admin,
    )
    assert conf2.status_code == 200, conf2.text
    # Impacts-changed outbox (already confirmed) — not a second event.confirmed
    impact_outbox = (
        db.query(OutboxEvent)
        .filter(
            OutboxEvent.aggregate_id == event["id"],
            OutboxEvent.event_type == "event.impacts_changed",
        )
        .count()
    )
    assert impact_outbox >= 1
    confirmed_outbox = (
        db.query(OutboxEvent)
        .filter(
            OutboxEvent.aggregate_id == event["id"],
            OutboxEvent.event_type == "event.confirmed",
        )
        .count()
    )
    assert confirmed_outbox == 1

    # Billing reminder jobs dead-lettered / not matching
    billing_queued = 0
    for job in db.query(Job).filter(Job.job_type == "notify_reminder").all():
        if (job.payload or {}).get("subscription_id") == billing_sub.id:
            if job.status == JobStatus.queued:
                billing_queued += 1
    assert billing_queued == 0
