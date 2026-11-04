"""Occurrence-aware notification recipients — app+env pairs, overrides, dedupe."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from maintenancehub_api.domain.authz import grant_user_on_application
from maintenancehub_api.domain.notifications import (
    enqueue_deliveries_for_event,
    matching_subscriptions,
    schedule_reminders_for_event,
)
from maintenancehub_api.domain import events as event_service
from maintenancehub_api.domain import occurrences as occurrence_service
from maintenancehub_api.models import (
    Job,
    JobStatus,
    NotificationDelivery,
    ReminderOffset,
    Role,
    RoleName,
    Subscription,
    SubscriptionTarget,
    User,
    UserRole,
)
from maintenancehub_api.auth.security import hash_password
from tests.conftest import auth_header


def _envs_and_apps(client, admin, pub_claims, pub_billing):
    env_int = client.post(
        "/api/v1/environments",
        json={"key": "INT", "name": "Integration", "sort_order": 1},
        headers=admin,
    ).json()
    env_dev = client.post(
        "/api/v1/environments",
        json={"key": "DEV", "name": "Development", "sort_order": 2},
        headers=admin,
    ).json()
    claims = client.post(
        "/api/v1/applications",
        json={
            "key": "claims",
            "name": "Claims",
            "environments": [
                {"environment_id": env_int["id"], "display_name": "Claims-INT"},
                {"environment_id": env_dev["id"], "display_name": "Claims-DEV"},
            ],
        },
        headers=pub_claims,
    ).json()
    billing = client.post(
        "/api/v1/applications",
        json={
            "key": "billing",
            "name": "Billing",
            "environments": [
                {"environment_id": env_int["id"], "display_name": "Billing-INT"},
                {"environment_id": env_dev["id"], "display_name": "Billing-DEV"},
            ],
        },
        headers=pub_billing,
    ).json()
    return env_int, env_dev, claims, billing


def _second_publisher(db_session, email: str = "publisher2@test.example.com") -> User:
    role = db_session.query(Role).filter(Role.name == RoleName.publisher).one()
    u = User(
        email=email,
        display_name="Publisher Two",
        password_hash=hash_password("password123"),
        is_active=True,
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(UserRole(user_id=u.id, role_id=role.id))
    db_session.commit()
    return u


def test_occurrence_impacts_target_correct_subscribers(client, db_session):
    admin = auth_header(client, "admin@test.example.com")
    pub_claims = auth_header(client, "publisher@test.example.com")
    pub2 = _second_publisher(db_session)
    pub_billing = auth_header(client, pub2.email)

    env_int, env_dev, claims, billing = _envs_and_apps(
        client, admin, pub_claims, pub_billing
    )

    # Series defaults: both apps (admin creates via claims publisher adding both —
    # use admin to create multi-app series)
    starts = datetime(2031, 1, 6, 10, 0, tzinfo=timezone.utc)
    created = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Shared series",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": claims["id"],
                    "environment_id": env_int["id"],
                },
                {
                    "target_type": "application",
                    "target_id": billing["id"],
                    "environment_id": env_dev["id"],
                },
            ],
            "recurrence": {"freq": "WEEKLY", "interval": 1, "count": 4},
        },
        headers=admin,
    )
    assert created.status_code == 201, created.text
    eid = created.json()["id"]

    # Subscribers: Claims-INT pair, Billing-DEV pair, and a cross-pair that must NOT match
    def add_sub(user_id, dest, target_type, target_id):
        sub = Subscription(
            user_id=user_id,
            destination_type="email_address",
            destination=dest,
            is_active=True,
        )
        db_session.add(sub)
        db_session.flush()
        db_session.add(
            SubscriptionTarget(
                subscription_id=sub.id, target_type=target_type, target_id=target_id
            )
        )
        db_session.add(ReminderOffset(subscription_id=sub.id, offset_minutes=-60))
        db_session.commit()
        return sub

    sub_claims_int = add_sub(
        db_session.publisher.id,  # type: ignore[attr-defined]
        "claims-int@example.com",
        "app_environment",
        f"{claims['id']}:{env_int['id']}",
    )
    sub_billing_dev = add_sub(
        pub2.id,
        "billing-dev@example.com",
        "app_environment",
        f"{billing['id']}:{env_dev['id']}",
    )
    # Claims DEV — should NOT match Claims INT override (pair equality)
    sub_claims_dev = add_sub(
        db_session.publisher.id,  # type: ignore[attr-defined]
        "claims-dev@example.com",
        "app_environment",
        f"{claims['id']}:{env_dev['id']}",
    )
    # Event-level sub — matches every occurrence once
    sub_event = add_sub(
        db_session.admin.id,  # type: ignore[attr-defined]
        "event-watcher@example.com",
        "event",
        eid,
    )

    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=21)).isoformat()},
        headers=admin,
    ).json()
    a, b = occs[0], occs[1]

    # Occ A → Claims INT only; Occ B → Billing DEV only
    assert (
        client.patch(
            f"/api/v1/events/{eid}/occurrences",
            json={
                "original_starts_at": a["original_starts_at"],
                "impacts": [
                    {
                        "target_type": "application",
                        "target_id": claims["id"],
                        "environment_id": env_int["id"],
                    }
                ],
            },
            headers=admin,
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/events/{eid}/occurrences",
            json={
                "original_starts_at": b["original_starts_at"],
                "impacts": [
                    {
                        "target_type": "application",
                        "target_id": billing["id"],
                        "environment_id": env_dev["id"],
                    }
                ],
            },
            headers=admin,
        ).status_code
        == 200
    )

    db_session.expire_all()
    event = event_service.get_event(db_session, eid)
    rec_a = occurrence_service.find_record(
        db_session,
        eid,
        datetime.fromisoformat(a["original_starts_at"].replace("Z", "+00:00")),
    )
    rec_b = occurrence_service.find_record(
        db_session,
        eid,
        datetime.fromisoformat(b["original_starts_at"].replace("Z", "+00:00")),
    )

    matched_a = {s.id for s in matching_subscriptions(db_session, event, record=rec_a)}
    matched_b = {s.id for s in matching_subscriptions(db_session, event, record=rec_b)}

    assert sub_claims_int.id in matched_a
    assert sub_event.id in matched_a
    assert sub_billing_dev.id not in matched_a
    assert sub_claims_dev.id not in matched_a

    assert sub_billing_dev.id in matched_b
    assert sub_event.id in matched_b
    assert sub_claims_int.id not in matched_b
    assert sub_claims_dev.id not in matched_b

    # Lifecycle notify for A only hits Claims-INT + event watcher
    n = enqueue_deliveries_for_event(
        db_session,
        event,
        template_key="event.transitioned",
        reason="event.transitioned",
        extra_context={
            "orig_key": datetime.fromisoformat(
                a["original_starts_at"].replace("Z", "+00:00")
            ).strftime("%Y%m%dT%H%M%SZ"),
            "from": "scheduled",
            "to": "in_progress",
        },
        record=rec_a,
    )
    assert n == 2
    dests = {
        d.destination
        for d in db_session.query(NotificationDelivery)
        .filter(NotificationDelivery.event_id == eid)
        .all()
    }
    assert "claims-int@example.com" in dests
    assert "event-watcher@example.com" in dests
    assert "billing-dev@example.com" not in dests
    assert "claims-dev@example.com" not in dests

    # Second enqueue is idempotent (no duplicate)
    n2 = enqueue_deliveries_for_event(
        db_session,
        event,
        template_key="event.transitioned",
        reason="event.transitioned",
        extra_context={
            "orig_key": datetime.fromisoformat(
                a["original_starts_at"].replace("Z", "+00:00")
            ).strftime("%Y%m%dT%H%M%SZ"),
            "from": "scheduled",
            "to": "in_progress",
        },
        record=rec_a,
    )
    assert n2 == 0

    # Empty override → only event-level subscription matches
    assert (
        client.patch(
            f"/api/v1/events/{eid}/occurrences",
            json={"original_starts_at": a["original_starts_at"], "impacts": []},
            headers=admin,
        ).status_code
        == 200
    )
    db_session.expire_all()
    event = event_service.get_event(db_session, eid)
    rec_a = occurrence_service.find_record(
        db_session,
        eid,
        datetime.fromisoformat(a["original_starts_at"].replace("Z", "+00:00")),
    )
    assert rec_a is not None and rec_a.impacts_overridden is True
    matched_empty = {s.id for s in matching_subscriptions(db_session, event, record=rec_a)}
    assert matched_empty == {sub_event.id}


def test_impact_change_reconciles_queued_reminders(client, db_session):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    env_int, env_dev, claims, billing = _envs_and_apps(
        client, admin, pub, pub
    )
    # Grant pub on billing too for this fixture (same publisher owns both apps here)
    grant_user_on_application(
        db_session, user_id=db_session.publisher.id, application_id=billing["id"]  # type: ignore[attr-defined]
    )
    db_session.commit()

    starts = datetime.now(timezone.utc) + timedelta(days=3)
    starts = starts.replace(minute=0, second=0, microsecond=0)
    created = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Reminder reconcile",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": claims["id"],
                    "environment_id": env_int["id"],
                }
            ],
            "recurrence": {"freq": "WEEKLY", "count": 3},
        },
        headers=pub,
    )
    assert created.status_code == 201, created.text
    eid = created.json()["id"]

    sub = Subscription(
        user_id=db_session.publisher.id,  # type: ignore[attr-defined]
        destination_type="email_address",
        destination="claims@example.com",
        is_active=True,
    )
    db_session.add(sub)
    db_session.flush()
    db_session.add(
        SubscriptionTarget(
            subscription_id=sub.id,
            target_type="app_environment",
            target_id=f"{claims['id']}:{env_int['id']}",
        )
    )
    db_session.add(ReminderOffset(subscription_id=sub.id, offset_minutes=-120))
    db_session.commit()

    db_session.expire_all()
    event = event_service.get_event(db_session, eid)
    schedule_reminders_for_event(db_session, event)
    queued = (
        db_session.query(Job)
        .filter(Job.job_type == "notify_reminder", Job.status == JobStatus.queued)
        .count()
    )
    assert queued >= 1

    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=20)).isoformat()},
        headers=pub,
    ).json()
    # Flip first occ to Billing DEV — Claims subscriber must lose queued reminders
    assert (
        client.patch(
            f"/api/v1/events/{eid}/occurrences",
            json={
                "original_starts_at": occs[0]["original_starts_at"],
                "impacts": [
                    {
                        "target_type": "application",
                        "target_id": billing["id"],
                        "environment_id": env_dev["id"],
                    }
                ],
            },
            headers=pub,
        ).status_code
        == 200
    )
    db_session.expire_all()
    orig_key = datetime.fromisoformat(
        occs[0]["original_starts_at"].replace("Z", "+00:00")
    ).strftime("%Y%m%dT%H%M%SZ")
    dead = (
        db_session.query(Job)
        .filter(
            Job.job_type == "notify_reminder",
            Job.status == JobStatus.dead,
            Job.idempotency_key.like(f"reminder:event:{eid}:orig:{orig_key}:%"),
        )
        .all()
    )
    assert any(j.last_error == "occurrence_impacts_no_longer_match" for j in dead)
