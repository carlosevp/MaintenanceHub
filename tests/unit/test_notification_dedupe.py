"""M6 — notification delivery idempotency."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from maintenancehub_api.domain.notifications import (
    create_delivery_idempotent,
    enqueue_deliveries_for_event,
    process_notify_dispatch,
)
from maintenancehub_api.models import (
    ApprovalState,
    EventImpact,
    EventKind,
    EventStatus,
    ImpactTargetType,
    MaintenanceEvent,
    ReminderOffset,
    Subscription,
    SubscriptionTarget,
)


def _event(db, app_id: str) -> MaintenanceEvent:
    now = datetime.now(timezone.utc)
    event = MaintenanceEvent(
        kind=EventKind.planned_maintenance,
        title="Notify me",
        status=EventStatus.scheduled,
        approval_state=ApprovalState.confirmed_scheduled,
        starts_at=now + timedelta(hours=2),
        ends_at=now + timedelta(hours=4),
        timezone="UTC",
    )
    db.add(event)
    db.flush()
    db.add(
        EventImpact(
            event_id=event.id,
            target_type=ImpactTargetType.application,
            target_id=app_id,
        )
    )
    db.commit()
    db.refresh(event)
    return event


def test_delivery_idempotency_key(db_session):
    from maintenancehub_api.models import Application

    app = Application(key="n1", name="N1")
    db_session.add(app)
    db_session.commit()

    a, created_a = create_delivery_idempotent(
        db_session,
        idempotency_key="dedupe-1",
        channel="log",
        destination_type="email_address",
        destination="a@example.com",
        subject="s",
        body="b",
        event_id=None,
        subscription_id=None,
    )
    b, created_b = create_delivery_idempotent(
        db_session,
        idempotency_key="dedupe-1",
        channel="log",
        destination_type="email_address",
        destination="a@example.com",
        subject="s2",
        body="b2",
        event_id=None,
        subscription_id=None,
    )
    assert a is not None and b is not None
    assert a.id == b.id
    assert created_a is True
    assert created_b is False


def test_enqueue_once_per_subscription(db_session):
    from maintenancehub_api.models import Application, NotificationDelivery

    app = Application(key="n2", name="N2")
    db_session.add(app)
    db_session.flush()
    user_id = db_session.publisher.id  # type: ignore[attr-defined]
    sub = Subscription(
        user_id=user_id,
        destination_type="email_address",
        destination="publisher@test.example.com",
        is_active=True,
    )
    db_session.add(sub)
    db_session.flush()
    db_session.add(
        SubscriptionTarget(
            subscription_id=sub.id, target_type="application", target_id=app.id
        )
    )
    db_session.add(ReminderOffset(subscription_id=sub.id, offset_minutes=-60))
    db_session.commit()

    event = _event(db_session, app.id)
    n1 = enqueue_deliveries_for_event(
        db_session, event, template_key="event.created", reason="event.created"
    )
    n2 = enqueue_deliveries_for_event(
        db_session, event, template_key="event.created", reason="event.created"
    )
    assert n1 == 1
    assert n2 == 0  # idempotent — second pass does not create new pending rows counted
    count = (
        db_session.query(NotificationDelivery)
        .filter(NotificationDelivery.event_id == event.id)
        .count()
    )
    assert count == 1


def test_dispatch_handler_creates_delivery(db_session):
    from maintenancehub_api.models import Application, NotificationDelivery

    app = Application(key="n3", name="N3")
    db_session.add(app)
    db_session.flush()
    sub = Subscription(
        user_id=db_session.publisher.id,  # type: ignore[attr-defined]
        destination_type="email_address",
        destination="x@example.com",
        is_active=True,
    )
    db_session.add(sub)
    db_session.flush()
    db_session.add(
        SubscriptionTarget(
            subscription_id=sub.id, target_type="application", target_id=app.id
        )
    )
    db_session.commit()
    event = _event(db_session, app.id)
    result = process_notify_dispatch(
        db_session,
        {"event_id": event.id, "event_type": "event.created", "action": "created"},
    )
    assert result["deliveries_enqueued"] >= 1
    assert (
        db_session.query(NotificationDelivery)
        .filter(NotificationDelivery.event_id == event.id)
        .count()
        >= 1
    )
