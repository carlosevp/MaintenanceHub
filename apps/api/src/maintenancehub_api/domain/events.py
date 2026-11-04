"""Event domain service: create, transition, extend, cancel, reschedule."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.domain.lifecycle import (
    IllegalTransitionError,
    assert_transition,
    can_cancel,
    can_extend,
    can_reschedule,
)
from maintenancehub_api.schemas.common import ensure_utc
from maintenancehub_api.models import (
    ApprovalState,
    EventImpact,
    EventKind,
    EventStatus,
    EventTimelineEntry,
    ImpactTargetType,
    MaintenanceEvent,
    OutboxEvent,
    TimelineEntryType,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _enqueue_outbox(
    db: Session,
    *,
    event: MaintenanceEvent,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Transactional outbox (ADR-001). Worker drains outbox → leased jobs."""
    body = dict(payload or {})
    body.setdefault("event_id", event.id)
    body.setdefault("status", event.status.value)
    body.setdefault("event_type", event_type)
    db.add(
        OutboxEvent(
            aggregate_type="maintenance_event",
            aggregate_id=event.id,
            event_type=event_type,
            payload=body,
        )
    )


def create_event(
    db: Session,
    *,
    data: dict[str, Any],
    actor_id: str | None,
) -> MaintenanceEvent:
    starts = ensure_utc(data["starts_at"])
    ends = ensure_utc(data["ends_at"])
    if ends <= starts:
        raise ValueError("ends_at must be after starts_at")

    kind = EventKind(data.get("kind", "planned_maintenance"))
    approval = ApprovalState(data.get("approval_state", "confirmed_scheduled"))
    is_recurring = bool(data.get("recurrence"))

    event = MaintenanceEvent(
        kind=kind,
        title=data["title"],
        description=data.get("description"),
        expected_impact=data.get("expected_impact"),
        status=EventStatus.scheduled if kind == EventKind.planned_maintenance else EventStatus.in_progress,
        approval_state=approval,
        starts_at=starts,
        ends_at=ends,
        timezone=data.get("timezone") or "UTC",
        is_recurring=is_recurring,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(event)
    db.flush()

    for impact in data.get("impacts") or []:
        db.add(
            EventImpact(
                event_id=event.id,
                target_type=ImpactTargetType(impact["target_type"]),
                target_id=impact["target_id"],
                environment_id=impact.get("environment_id"),
            )
        )

    db.add(
        EventTimelineEntry(
            event_id=event.id,
            at=_now(),
            actor_id=actor_id,
            entry_type=TimelineEntryType.system,
            payload={"action": "created", "status": event.status.value, "approval_state": approval.value},
        )
    )
    _enqueue_outbox(db, event=event, event_type="event.created")
    db.commit()
    return get_event(db, event.id)


def get_event(db: Session, event_id: str) -> MaintenanceEvent | None:
    return (
        db.query(MaintenanceEvent)
        .options(joinedload(MaintenanceEvent.impacts), joinedload(MaintenanceEvent.timeline))
        .filter(MaintenanceEvent.id == event_id)
        .first()
    )


def list_events(
    db: Session,
    *,
    kind: str | None = None,
    status: str | None = None,
    approval_state: str | None = None,
    application_id: str | None = None,
    environment_id: str | None = None,
    q: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MaintenanceEvent], int]:
    query = db.query(MaintenanceEvent).options(joinedload(MaintenanceEvent.impacts))
    if kind:
        query = query.filter(MaintenanceEvent.kind == EventKind(kind))
    if status:
        query = query.filter(MaintenanceEvent.status == EventStatus(status))
    if approval_state:
        query = query.filter(MaintenanceEvent.approval_state == ApprovalState(approval_state))
    if from_dt:
        query = query.filter(MaintenanceEvent.ends_at >= from_dt)
    if to_dt:
        query = query.filter(MaintenanceEvent.starts_at <= to_dt)
    if q:
        like = f"%{q}%"
        query = query.filter(MaintenanceEvent.title.ilike(like))
    if application_id or environment_id:
        query = query.join(EventImpact)
        if application_id:
            query = query.filter(
                EventImpact.target_type == ImpactTargetType.application,
                EventImpact.target_id == application_id,
            )
        if environment_id:
            query = query.filter(EventImpact.environment_id == environment_id)
        query = query.distinct()

    total = query.count()
    items = (
        query.order_by(MaintenanceEvent.starts_at.asc()).offset(offset).limit(limit).all()
    )
    return items, total


def transition_event(
    db: Session,
    event: MaintenanceEvent,
    *,
    target_status: EventStatus,
    actor_id: str | None,
    note: str | None = None,
    ends_at: datetime | None = None,
) -> MaintenanceEvent:
    try:
        assert_transition(event.status, target_status)
    except IllegalTransitionError as exc:
        raise ValueError(str(exc)) from exc

    previous = event.status
    event.status = target_status
    event.updated_by = actor_id
    if ends_at is not None:
        event.ends_at = ends_at

    payload: dict[str, Any] = {
        "from": previous.value,
        "to": target_status.value,
    }
    if note:
        payload["note"] = note

    db.add(
        EventTimelineEntry(
            event_id=event.id,
            at=_now(),
            actor_id=actor_id,
            entry_type=TimelineEntryType.status_change,
            payload=payload,
        )
    )
    _enqueue_outbox(db, event=event, event_type="event.transitioned", payload=payload)
    db.commit()
    return get_event(db, event.id)  # type: ignore[return-value]


def extend_event(
    db: Session,
    event: MaintenanceEvent,
    *,
    new_ends_at: datetime,
    actor_id: str | None,
    note: str | None = None,
) -> MaintenanceEvent:
    if not can_extend(event.status):
        raise ValueError(f"Cannot extend event in status {event.status.value}")
    new_ends_at = ensure_utc(new_ends_at)
    current_end = ensure_utc(event.ends_at)
    if new_ends_at <= current_end:
        raise ValueError("new_ends_at must be after current ends_at")

    previous_end = current_end
    event.ends_at = new_ends_at
    event.status = EventStatus.extended
    event.updated_by = actor_id
    payload = {
        "previous_ends_at": previous_end.isoformat(),
        "new_ends_at": new_ends_at.isoformat(),
        "note": note,
    }
    db.add(
        EventTimelineEntry(
            event_id=event.id,
            at=_now(),
            actor_id=actor_id,
            entry_type=TimelineEntryType.extension,
            payload=payload,
        )
    )
    _enqueue_outbox(db, event=event, event_type="event.extended", payload=payload)
    db.commit()
    return get_event(db, event.id)  # type: ignore[return-value]


def reschedule_event(
    db: Session,
    event: MaintenanceEvent,
    *,
    starts_at: datetime,
    ends_at: datetime,
    actor_id: str | None,
    note: str | None = None,
) -> MaintenanceEvent:
    if not can_reschedule(event.status):
        raise ValueError(f"Cannot reschedule event in status {event.status.value}")
    if ends_at <= starts_at:
        raise ValueError("ends_at must be after starts_at")

    payload = {
        "previous_starts_at": event.starts_at.isoformat(),
        "previous_ends_at": event.ends_at.isoformat(),
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "note": note,
    }
    event.starts_at = starts_at
    event.ends_at = ends_at
    event.status = EventStatus.scheduled
    event.updated_by = actor_id
    db.add(
        EventTimelineEntry(
            event_id=event.id,
            at=_now(),
            actor_id=actor_id,
            entry_type=TimelineEntryType.reschedule,
            payload=payload,
        )
    )
    _enqueue_outbox(db, event=event, event_type="event.rescheduled", payload=payload)
    db.commit()
    return get_event(db, event.id)  # type: ignore[return-value]


def cancel_event(
    db: Session,
    event: MaintenanceEvent,
    *,
    actor_id: str | None,
    note: str | None = None,
) -> MaintenanceEvent:
    if not can_cancel(event.status):
        raise ValueError(f"Cannot cancel event in status {event.status.value}")
    return transition_event(
        db,
        event,
        target_status=EventStatus.cancelled,
        actor_id=actor_id,
        note=note,
    )


def add_timeline_note(
    db: Session,
    event: MaintenanceEvent,
    *,
    actor_id: str | None,
    note: str,
) -> EventTimelineEntry:
    entry = EventTimelineEntry(
        event_id=event.id,
        at=_now(),
        actor_id=actor_id,
        entry_type=TimelineEntryType.note,
        payload={"note": note},
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
