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
    RecurrenceRule,
    TimelineEntryType,
)
from maintenancehub_api.domain import recurrence as recurrence_service


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

    if data.get("recurrence"):
        recurrence_service.upsert_rule(db, event, recurrence=data["recurrence"])
        db.add(
            EventTimelineEntry(
                event_id=event.id,
                at=_now(),
                actor_id=actor_id,
                entry_type=TimelineEntryType.system,
                payload={
                    "action": "recurrence_set",
                    "rrule": event.recurrence_rule.rrule if event.recurrence_rule else None,
                    "summary": recurrence_service.human_summary(
                        data["recurrence"], timezone_name=event.timezone
                    ),
                },
            )
        )

    _enqueue_outbox(db, event=event, event_type="event.created")
    db.commit()
    return get_event(db, event.id)


def get_event(db: Session, event_id: str) -> MaintenanceEvent | None:
    return (
        db.query(MaintenanceEvent)
        .options(
            joinedload(MaintenanceEvent.impacts),
            joinedload(MaintenanceEvent.timeline),
            joinedload(MaintenanceEvent.recurrence_rule).joinedload(RecurrenceRule.exceptions),
        )
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


def update_event_fields(
    db: Session,
    event: MaintenanceEvent,
    *,
    data: dict[str, Any],
    actor_id: str | None,
) -> MaintenanceEvent:
    """Patch mutable fields. Confirming approval_state enqueues outbox + reminders."""
    previous_approval = event.approval_state
    for key, value in data.items():
        if value is None:
            continue
        if key == "approval_state":
            event.approval_state = ApprovalState(value)
        else:
            setattr(event, key, value)
    event.updated_by = actor_id

    if (
        "approval_state" in data
        and data["approval_state"] is not None
        and event.approval_state != previous_approval
    ):
        payload = {
            "from_approval": previous_approval.value,
            "to_approval": event.approval_state.value,
        }
        db.add(
            EventTimelineEntry(
                event_id=event.id,
                at=_now(),
                actor_id=actor_id,
                entry_type=TimelineEntryType.system,
                payload={"action": "approval_state_change", **payload},
            )
        )
        if event.approval_state == ApprovalState.confirmed_scheduled:
            # Notify subscribers now that the window is confirmed (SN imports start as approved_window).
            _enqueue_outbox(
                db,
                event=event,
                event_type="event.confirmed",
                payload=payload,
            )

    db.commit()
    updated = get_event(db, event.id)
    if (
        updated
        and updated.approval_state == ApprovalState.confirmed_scheduled
        and previous_approval != ApprovalState.confirmed_scheduled
    ):
        from maintenancehub_api.domain.notifications import schedule_reminders_for_event

        schedule_reminders_for_event(db, updated)
    return updated  # type: ignore[return-value]


def set_recurrence(
    db: Session,
    event: MaintenanceEvent,
    *,
    recurrence: dict[str, Any],
    actor_id: str | None,
) -> MaintenanceEvent:
    recurrence_service.resolve_tz(event.timezone)
    recurrence_service.upsert_rule(db, event, recurrence=recurrence)
    db.add(
        EventTimelineEntry(
            event_id=event.id,
            at=_now(),
            actor_id=actor_id,
            entry_type=TimelineEntryType.system,
            payload={
                "action": "recurrence_set",
                "rrule": event.recurrence_rule.rrule if event.recurrence_rule else None,
                "summary": recurrence_service.human_summary(
                    recurrence, timezone_name=event.timezone
                ),
            },
        )
    )
    _enqueue_outbox(db, event=event, event_type="event.rescheduled", payload={"action": "recurrence_set"})
    db.commit()
    return get_event(db, event.id)  # type: ignore[return-value]


def exception_for_occurrence(
    db: Session,
    event: MaintenanceEvent,
    *,
    original_starts_at: datetime,
    action: str,
    new_starts_at: datetime | None = None,
    new_ends_at: datetime | None = None,
    actor_id: str | None,
) -> MaintenanceEvent:
    """Cancel or reschedule a single occurrence (does not rewrite the master series)."""
    if not event.is_recurring or not event.recurrence_rule:
        raise ValueError("Event is not recurring")
    recurrence_service.add_or_replace_exception(
        db,
        event,
        original_starts_at=original_starts_at,
        action=action,
        new_starts_at=new_starts_at,
        new_ends_at=new_ends_at,
    )
    db.add(
        EventTimelineEntry(
            event_id=event.id,
            at=_now(),
            actor_id=actor_id,
            entry_type=TimelineEntryType.system,
            payload={
                "action": f"occurrence_{action}",
                "occurrence_id": recurrence_service.occurrence_id_for(
                    event.id, ensure_utc(original_starts_at)
                ),
                "original_starts_at": ensure_utc(original_starts_at).isoformat(),
                "new_starts_at": new_starts_at.isoformat() if new_starts_at else None,
                "new_ends_at": new_ends_at.isoformat() if new_ends_at else None,
            },
        )
    )
    if action == "cancel":
        from maintenancehub_api.domain.notifications import cancel_reminder_jobs_for_occurrence

        cancel_reminder_jobs_for_occurrence(
            db, event_id=event.id, original_starts_at=ensure_utc(original_starts_at)
        )
    _enqueue_outbox(
        db,
        event=event,
        event_type="event.rescheduled",
        payload={
            "action": f"occurrence_{action}",
            "original_starts_at": ensure_utc(original_starts_at).isoformat(),
        },
    )
    db.commit()
    return get_event(db, event.id)  # type: ignore[return-value]


def edit_series(
    db: Session,
    event: MaintenanceEvent,
    *,
    scope: str,
    original_starts_at: datetime | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    title: str | None = None,
    description: str | None = None,
    expected_impact: str | None = None,
    approval_state: str | None = None,
    recurrence: dict[str, Any] | None = None,
    actor_id: str | None = None,
) -> MaintenanceEvent:
    """Edit this / this_and_future / all occurrences of a series."""
    scope = scope.lower().replace("-", "_")
    if scope not in {"this", "this_and_future", "all"}:
        raise ValueError("scope must be this | this_and_future | all")

    if scope == "this":
        if not original_starts_at:
            raise ValueError("original_starts_at required for scope=this")
        if not starts_at or not ends_at:
            raise ValueError("starts_at and ends_at required to reschedule one occurrence")
        return exception_for_occurrence(
            db,
            event,
            original_starts_at=original_starts_at,
            action="reschedule",
            new_starts_at=starts_at,
            new_ends_at=ends_at,
            actor_id=actor_id,
        )

    if scope == "all":
        # Entire-series edit keeps existing recurrence_exceptions keyed by original_starts_at.
        # If DTSTART/pattern shifts so those originals no longer fall on generated slots,
        # exceptions remain stored (audit) but may stop matching — documented in LIMITATIONS.
        prior_exception_count = (
            len(event.recurrence_rule.exceptions) if event.recurrence_rule else 0
        )
        if starts_at and ends_at:
            if ends_at <= starts_at:
                raise ValueError("ends_at must be after starts_at")
            event.starts_at = ensure_utc(starts_at)
            event.ends_at = ensure_utc(ends_at)
        if title is not None:
            event.title = title
        if description is not None:
            event.description = description
        if expected_impact is not None:
            event.expected_impact = expected_impact
        if approval_state is not None:
            event.approval_state = ApprovalState(approval_state)
        event.updated_by = actor_id
        if recurrence is not None:
            recurrence_service.upsert_rule(db, event, recurrence=recurrence)
        db.add(
            EventTimelineEntry(
                event_id=event.id,
                at=_now(),
                actor_id=actor_id,
                entry_type=TimelineEntryType.reschedule,
                payload={
                    "action": "series_edit_all",
                    "preserved_exceptions": prior_exception_count,
                    "note": (
                        "Existing exceptions retained by original_starts_at; "
                        "may not match if RRULE/DTSTART changed"
                    ),
                },
            )
        )
        _enqueue_outbox(db, event=event, event_type="event.rescheduled", payload={"scope": "all"})
        db.commit()
        return get_event(db, event.id)  # type: ignore[return-value]

    # this_and_future — truncate old series and spawn a new master from this occurrence
    if not original_starts_at:
        raise ValueError("original_starts_at required for scope=this_and_future")
    original_starts_at = ensure_utc(original_starts_at)
    new_starts = ensure_utc(starts_at) if starts_at else original_starts_at
    dur = recurrence_service.duration_of(event)
    new_ends = ensure_utc(ends_at) if ends_at else new_starts + dur

    # Preserve historical exceptions/reminders/deliveries on the truncated master.
    # Future-dated exceptions after the split stay on the old rule but no longer expand
    # (after UNTIL); they are not migrated onto the new series.
    hist_exceptions = 0
    if event.recurrence_rule:
        hist_exceptions = sum(
            1
            for ex in (event.recurrence_rule.exceptions or [])
            if ensure_utc(ex.original_starts_at) < original_starts_at
        )
    recurrence_service.truncate_series_before(event, from_occurrence_start=original_starts_at)
    db.add(
        EventTimelineEntry(
            event_id=event.id,
            at=_now(),
            actor_id=actor_id,
            entry_type=TimelineEntryType.system,
            payload={
                "action": "series_truncated",
                "from": original_starts_at.isoformat(),
                "preserved_historical_exceptions": hist_exceptions,
            },
        )
    )
    db.flush()

    data = {
        "kind": event.kind.value,
        "title": title if title is not None else event.title,
        "description": description if description is not None else event.description,
        "expected_impact": expected_impact if expected_impact is not None else event.expected_impact,
        "approval_state": (
            approval_state if approval_state is not None else event.approval_state.value
        ),
        "starts_at": new_starts,
        "ends_at": new_ends,
        "timezone": event.timezone,
        "impacts": [
            {
                "target_type": i.target_type.value,
                "target_id": i.target_id,
                "environment_id": i.environment_id,
            }
            for i in event.impacts
        ],
    }
    if recurrence is not None:
        data["recurrence"] = recurrence
    elif event.recurrence_rule:
        # Continue with same freq pattern (UNTIL from old rule stripped for new series)
        body = event.recurrence_rule.rrule
        parts = [
            p
            for p in body.split(";")
            if not p.upper().startswith("UNTIL=") and not p.upper().startswith("COUNT=")
        ]
        data["recurrence"] = {"rrule": ";".join(parts)}

    # Commit truncate first so create_event's commit is clean
    db.commit()
    return create_event(db, data=data, actor_id=actor_id)
