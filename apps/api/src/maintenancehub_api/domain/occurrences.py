"""Per-occurrence lifecycle, overrides, and series exception reconciliation.

Series = RRULE + defaults. Occurrence = stable `{series}@{original_start}`.
Records are persisted sparsely (overrides / state / audit only).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.domain import recurrence as recurrence_service
from maintenancehub_api.domain.lifecycle import (
    IllegalTransitionError,
    assert_transition,
    can_cancel,
    can_extend,
)
from maintenancehub_api.models import (
    EventStatus,
    EventTimelineEntry,
    ImpactTargetType,
    MaintenanceEvent,
    OccurrenceImpact,
    OccurrenceRecord,
    OutboxEvent,
    RecurrenceException,
    TimelineEntryType,
)
from maintenancehub_api.schemas.common import ensure_utc


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _orig_key(dt: datetime) -> str:
    return ensure_utc(dt).strftime("%Y%m%dT%H%M%SZ")


def _enqueue_outbox(
    db: Session,
    *,
    event: MaintenanceEvent,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    body = dict(payload or {})
    body.setdefault("event_id", event.id)
    body.setdefault("event_type", event_type)
    db.add(
        OutboxEvent(
            aggregate_type="maintenance_event",
            aggregate_id=event.id,
            event_type=event_type,
            payload=body,
        )
    )


def find_record(
    db: Session,
    event_id: str,
    original_starts_at: datetime,
) -> OccurrenceRecord | None:
    original_starts_at = ensure_utc(original_starts_at)
    rows = (
        db.query(OccurrenceRecord)
        .options(joinedload(OccurrenceRecord.impacts))
        .filter(OccurrenceRecord.event_id == event_id)
        .all()
    )
    for row in rows:
        if abs((ensure_utc(row.original_starts_at) - original_starts_at).total_seconds()) < 1:
            return row
    return None


def records_for_event(db: Session, event_id: str) -> dict[datetime, OccurrenceRecord]:
    rows = (
        db.query(OccurrenceRecord)
        .options(joinedload(OccurrenceRecord.impacts))
        .filter(OccurrenceRecord.event_id == event_id)
        .all()
    )
    return {ensure_utc(r.original_starts_at): r for r in rows}


def get_or_create_record(
    db: Session,
    event: MaintenanceEvent,
    *,
    original_starts_at: datetime,
    actor_id: str | None = None,
) -> OccurrenceRecord:
    original_starts_at = ensure_utc(original_starts_at)
    existing = find_record(db, event.id, original_starts_at)
    if existing:
        return existing
    row = OccurrenceRecord(
        event_id=event.id,
        original_starts_at=original_starts_at,
        status=EventStatus.scheduled,
        updated_by=actor_id,
    )
    db.add(row)
    db.flush()
    return row


def effective_status(
    event: MaintenanceEvent,
    *,
    original_starts_at: datetime,
    record: OccurrenceRecord | None = None,
    cancelled_exception: bool = False,
) -> EventStatus:
    if cancelled_exception:
        return EventStatus.cancelled
    if record is not None:
        return record.status
    # Non-recurring: master status is the occurrence status
    if not event.is_recurring:
        return event.status
    return EventStatus.scheduled


def effective_times(
    occ: recurrence_service.Occurrence,
    record: OccurrenceRecord | None,
) -> tuple[datetime, datetime]:
    if record and record.expected_starts_at and record.expected_ends_at:
        return ensure_utc(record.expected_starts_at), ensure_utc(record.expected_ends_at)
    return ensure_utc(occ.starts_at), ensure_utc(occ.ends_at)


def resolve_occurrence(
    db: Session,
    event: MaintenanceEvent,
    *,
    original_starts_at: datetime | None = None,
    occurrence_id: str | None = None,
) -> tuple[recurrence_service.Occurrence, OccurrenceRecord | None]:
    """Locate an expanded occurrence + optional sparse record by id or original start."""
    if occurrence_id:
        parsed = recurrence_service.parse_occurrence_id(occurrence_id)
        if not parsed:
            raise ValueError(f"Invalid occurrence_id: {occurrence_id}")
        eid, orig = parsed
        if eid != event.id:
            raise ValueError("occurrence_id does not belong to this event")
        original_starts_at = orig
    if original_starts_at is None:
        raise ValueError("original_starts_at or occurrence_id required")
    original_starts_at = ensure_utc(original_starts_at)

    # Expand a tight window around the slot (and a year pad for reschedule drift)
    pad = timedelta(days=2)
    occs = recurrence_service.expand_event_occurrences(
        event,
        range_start=original_starts_at - pad,
        range_end=original_starts_at + pad,
        include_cancelled=True,
    )
    match = None
    for o in occs:
        if abs((ensure_utc(o.original_starts_at) - original_starts_at).total_seconds()) < 1:
            match = o
            break
    if match is None and not event.is_recurring:
        starts = ensure_utc(event.starts_at)
        if abs((starts - original_starts_at).total_seconds()) < 1:
            match = recurrence_service.Occurrence(
                event_id=event.id,
                original_starts_at=starts,
                starts_at=starts,
                ends_at=ensure_utc(event.ends_at),
            )
    if match is None:
        # Historical executed slot may fall outside current RRULE — still allow via record
        record = find_record(db, event.id, original_starts_at)
        if record:
            starts = ensure_utc(record.expected_starts_at or record.original_starts_at)
            ends = ensure_utc(
                record.expected_ends_at
                or (starts + recurrence_service.duration_of(event))
            )
            match = recurrence_service.Occurrence(
                event_id=event.id,
                original_starts_at=original_starts_at,
                starts_at=starts,
                ends_at=ends,
                cancelled=record.status == EventStatus.cancelled,
                is_exception=True,
            )
            return match, record
        raise ValueError("Occurrence not found for given original_starts_at")

    return match, find_record(db, event.id, original_starts_at)


def occurrence_to_dict(
    event: MaintenanceEvent,
    occ: recurrence_service.Occurrence,
    record: OccurrenceRecord | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    from maintenancehub_api.domain import communication as comm

    now = now or _now()
    status = effective_status(
        event,
        original_starts_at=occ.original_starts_at,
        record=record,
        cancelled_exception=occ.cancelled,
    )
    starts, ends = effective_times(occ, record)
    description = (
        record.description if record and record.description is not None else event.description
    )
    expected_impact = (
        record.expected_impact
        if record and record.expected_impact is not None
        else event.expected_impact
    )
    # DTO impacts == effective set (override including empty, else series defaults)
    if record and record.impacts_overridden:
        impacts = [
            {
                "id": i.id,
                "target_type": i.target_type.value,
                "target_id": i.target_id,
                "environment_id": i.environment_id,
            }
            for i in (record.impacts or [])
        ]
    else:
        impacts = [
            {
                "id": i.id,
                "target_type": i.target_type.value,
                "target_id": i.target_id,
                "environment_id": i.environment_id,
            }
            for i in (event.impacts or [])
        ]

    return {
        "occurrence_id": occ.occurrence_id,
        "event_id": event.id,
        "series_id": event.id,
        "original_starts_at": ensure_utc(occ.original_starts_at).isoformat(),
        "starts_at": starts.isoformat(),
        "ends_at": ends.isoformat(),
        "cancelled": status == EventStatus.cancelled or occ.cancelled,
        "is_exception": occ.is_exception or bool(record and record.expected_starts_at),
        "has_record": record is not None,
        "status": status.value,
        "approval_state": event.approval_state.value,
        "phase": comm.communication_phase(
            event, now=now, starts_at=starts, ends_at=ends, status=status
        ),
        "title": event.title,
        "description": description,
        "expected_impact": expected_impact,
        "actual_starts_at": (
            record.actual_starts_at.isoformat() if record and record.actual_starts_at else None
        ),
        "actual_ends_at": (
            record.actual_ends_at.isoformat() if record and record.actual_ends_at else None
        ),
        "impacts_overridden": bool(record.impacts_overridden) if record else False,
        "impacts": impacts,
    }


def transition_occurrence(
    db: Session,
    event: MaintenanceEvent,
    *,
    original_starts_at: datetime,
    target_status: EventStatus,
    actor_id: str | None,
    note: str | None = None,
    ends_at: datetime | None = None,
) -> OccurrenceRecord:
    occ, record = resolve_occurrence(db, event, original_starts_at=original_starts_at)
    current = effective_status(
        event,
        original_starts_at=occ.original_starts_at,
        record=record,
        cancelled_exception=occ.cancelled,
    )
    try:
        assert_transition(current, target_status)
    except IllegalTransitionError as exc:
        raise ValueError(str(exc)) from exc

    record = record or get_or_create_record(
        db, event, original_starts_at=occ.original_starts_at, actor_id=actor_id
    )
    previous = record.status
    record.status = target_status
    record.updated_by = actor_id
    if target_status == EventStatus.in_progress and record.actual_starts_at is None:
        record.actual_starts_at = _now()
    if target_status in {EventStatus.completed, EventStatus.cancelled}:
        record.actual_ends_at = _now()
    if ends_at is not None:
        record.expected_ends_at = ensure_utc(ends_at)

    if target_status == EventStatus.cancelled:
        if event.is_recurring and event.recurrence_rule:
            recurrence_service.add_or_replace_exception(
                db,
                event,
                original_starts_at=occ.original_starts_at,
                action="cancel",
            )
        from maintenancehub_api.domain.notifications import cancel_reminder_jobs_for_occurrence

        cancel_reminder_jobs_for_occurrence(
            db, event_id=event.id, original_starts_at=occ.original_starts_at
        )

    # One-shot: keep master status in sync with the single occurrence
    if not event.is_recurring:
        event.status = target_status
        event.updated_by = actor_id

    payload = {
        "action": "occurrence_transition",
        "occurrence_id": occ.occurrence_id,
        "original_starts_at": ensure_utc(occ.original_starts_at).isoformat(),
        "from": previous.value,
        "to": target_status.value,
        "note": note,
    }
    db.add(
        EventTimelineEntry(
            event_id=event.id,
            at=_now(),
            actor_id=actor_id,
            entry_type=TimelineEntryType.status_change,
            payload=payload,
        )
    )
    outbox_type = {
        EventStatus.in_progress: "event.transitioned",
        EventStatus.verifying: "event.transitioned",
        EventStatus.completed: "event.transitioned",
        EventStatus.cancelled: "event.transitioned",
        EventStatus.extended: "event.extended",
        EventStatus.scheduled: "event.transitioned",
    }.get(target_status, "event.transitioned")
    _enqueue_outbox(
        db,
        event=event,
        event_type=outbox_type,
        payload={
            **payload,
            "status": target_status.value,
            "orig_key": _orig_key(occ.original_starts_at),
            "starts_at": effective_times(occ, record)[0].isoformat(),
            "ends_at": effective_times(occ, record)[1].isoformat(),
        },
    )
    db.commit()
    refreshed = find_record(db, event.id, occ.original_starts_at)
    assert refreshed is not None
    return refreshed


def extend_occurrence(
    db: Session,
    event: MaintenanceEvent,
    *,
    original_starts_at: datetime,
    new_ends_at: datetime,
    actor_id: str | None,
    note: str | None = None,
) -> OccurrenceRecord:
    occ, record = resolve_occurrence(db, event, original_starts_at=original_starts_at)
    current = effective_status(
        event,
        original_starts_at=occ.original_starts_at,
        record=record,
        cancelled_exception=occ.cancelled,
    )
    if not can_extend(current):
        raise ValueError(f"Cannot extend occurrence in status {current.value}")
    new_ends_at = ensure_utc(new_ends_at)
    starts, ends = effective_times(occ, record)
    if new_ends_at <= ends:
        raise ValueError("new_ends_at must be after current ends_at")

    record = record or get_or_create_record(
        db, event, original_starts_at=occ.original_starts_at, actor_id=actor_id
    )
    previous_end = ends
    record.expected_starts_at = record.expected_starts_at or starts
    record.expected_ends_at = new_ends_at
    record.status = EventStatus.extended
    record.updated_by = actor_id

    if event.is_recurring and event.recurrence_rule:
        recurrence_service.add_or_replace_exception(
            db,
            event,
            original_starts_at=occ.original_starts_at,
            action="reschedule",
            new_starts_at=record.expected_starts_at,
            new_ends_at=new_ends_at,
        )
    if not event.is_recurring:
        event.ends_at = new_ends_at
        event.status = EventStatus.extended
        event.updated_by = actor_id

    payload = {
        "action": "occurrence_extend",
        "occurrence_id": occ.occurrence_id,
        "original_starts_at": ensure_utc(occ.original_starts_at).isoformat(),
        "previous_ends_at": previous_end.isoformat(),
        "new_ends_at": new_ends_at.isoformat(),
        "note": note,
        "orig_key": _orig_key(occ.original_starts_at),
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
    refreshed = find_record(db, event.id, occ.original_starts_at)
    assert refreshed is not None
    return refreshed


def patch_occurrence(
    db: Session,
    event: MaintenanceEvent,
    *,
    original_starts_at: datetime,
    actor_id: str | None,
    expected_starts_at: datetime | None = None,
    expected_ends_at: datetime | None = None,
    expected_impact: str | None = None,
    description: str | None = None,
    impacts: list[dict[str, Any]] | None = None,
    clear_impact_override: bool = False,
) -> OccurrenceRecord:
    occ, record = resolve_occurrence(db, event, original_starts_at=original_starts_at)
    current = effective_status(
        event,
        original_starts_at=occ.original_starts_at,
        record=record,
        cancelled_exception=occ.cancelled,
    )
    if current in {EventStatus.completed, EventStatus.cancelled}:
        raise ValueError(f"Cannot patch occurrence in status {current.value}")

    record = record or get_or_create_record(
        db, event, original_starts_at=occ.original_starts_at, actor_id=actor_id
    )
    changes: dict[str, Any] = {}

    if expected_starts_at is not None or expected_ends_at is not None:
        starts = ensure_utc(expected_starts_at) if expected_starts_at else (
            ensure_utc(record.expected_starts_at) if record.expected_starts_at else occ.starts_at
        )
        ends = ensure_utc(expected_ends_at) if expected_ends_at else (
            ensure_utc(record.expected_ends_at) if record.expected_ends_at else occ.ends_at
        )
        if ends <= starts:
            raise ValueError("expected_ends_at must be after expected_starts_at")
        record.expected_starts_at = starts
        record.expected_ends_at = ends
        changes["expected_starts_at"] = starts.isoformat()
        changes["expected_ends_at"] = ends.isoformat()
        if event.is_recurring and event.recurrence_rule:
            recurrence_service.add_or_replace_exception(
                db,
                event,
                original_starts_at=occ.original_starts_at,
                action="reschedule",
                new_starts_at=starts,
                new_ends_at=ends,
            )
        elif not event.is_recurring:
            event.starts_at = starts
            event.ends_at = ends

    if expected_impact is not None:
        record.expected_impact = expected_impact
        changes["expected_impact"] = expected_impact
    if description is not None:
        record.description = description
        changes["description"] = description

    impacts_changed = False
    if clear_impact_override:
        record.impacts_overridden = False
        for row in list(record.impacts or []):
            db.delete(row)
        changes["impacts_overridden"] = False
        impacts_changed = True
    elif impacts is not None:
        # Explicit list — including [] — replaces series defaults for this occurrence
        record.impacts_overridden = True
        for row in list(record.impacts or []):
            db.delete(row)
        db.flush()
        for imp in impacts:
            db.add(
                OccurrenceImpact(
                    occurrence_id=record.id,
                    target_type=ImpactTargetType(imp["target_type"]),
                    target_id=imp["target_id"],
                    environment_id=imp.get("environment_id"),
                )
            )
        changes["impacts_overridden"] = True
        changes["impacts"] = impacts
        impacts_changed = True

    record.updated_by = actor_id
    db.add(
        EventTimelineEntry(
            event_id=event.id,
            at=_now(),
            actor_id=actor_id,
            entry_type=TimelineEntryType.system,
            payload={
                "action": "occurrence_patch",
                "occurrence_id": occ.occurrence_id,
                "original_starts_at": ensure_utc(occ.original_starts_at).isoformat(),
                "changes": changes,
            },
        )
    )
    if "expected_starts_at" in changes:
        _enqueue_outbox(
            db,
            event=event,
            event_type="event.rescheduled",
            payload={
                "action": "occurrence_reschedule",
                "occurrence_id": occ.occurrence_id,
                "original_starts_at": ensure_utc(occ.original_starts_at).isoformat(),
                "orig_key": _orig_key(occ.original_starts_at),
                "starts_at": changes.get("expected_starts_at"),
                "ends_at": changes.get("expected_ends_at"),
            },
        )
    db.flush()
    if impacts_changed or "expected_starts_at" in changes:
        from maintenancehub_api.domain.notifications import schedule_reminders_for_event

        # Retarget / dead-letter queued reminders; never rewrite sent deliveries
        schedule_reminders_for_event(db, event)
    db.commit()
    refreshed = find_record(db, event.id, occ.original_starts_at)
    assert refreshed is not None
    return refreshed


def cancel_occurrence(
    db: Session,
    event: MaintenanceEvent,
    *,
    original_starts_at: datetime,
    actor_id: str | None,
    note: str | None = None,
) -> OccurrenceRecord:
    current_occ, record = resolve_occurrence(db, event, original_starts_at=original_starts_at)
    current = effective_status(
        event,
        original_starts_at=current_occ.original_starts_at,
        record=record,
        cancelled_exception=current_occ.cancelled,
    )
    if not can_cancel(current):
        raise ValueError(f"Cannot cancel occurrence in status {current.value}")
    return transition_occurrence(
        db,
        event,
        original_starts_at=original_starts_at,
        target_status=EventStatus.cancelled,
        actor_id=actor_id,
        note=note,
    )


# ---------------------------------------------------------------------------
# Exception reconciliation on RRULE / DTSTART change
# ---------------------------------------------------------------------------


@dataclass
class ExceptionMismatch:
    original_starts_at: datetime
    action: str
    reason: str
    historical: bool
    has_execution_record: bool
    compatible: bool


def _slot_in_new_rule(
    event: MaintenanceEvent,
    *,
    new_rrule: str,
    original_starts_at: datetime,
    window_days: int = 400,
) -> bool:
    """Check whether original_starts_at still lands on a generated slot under new_rrule."""
    from types import SimpleNamespace

    original_starts_at = ensure_utc(original_starts_at)
    fake_rule = SimpleNamespace(rrule=new_rrule, until_at=None, exceptions=[])
    fake_event = SimpleNamespace(
        id=event.id,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        timezone=event.timezone,
        is_recurring=True,
        recurrence_rule=fake_rule,
    )
    # Wide window around the exception
    start = original_starts_at - timedelta(days=1)
    end = original_starts_at + timedelta(days=1)
    # Also try full horizon from DTSTART for safety on pattern shift
    occs = recurrence_service.expand_event_occurrences(
        fake_event,  # type: ignore[arg-type]
        range_start=ensure_utc(event.starts_at) - timedelta(days=1),
        range_end=ensure_utc(event.starts_at) + timedelta(days=window_days),
        include_cancelled=True,
    )
    for o in occs:
        if abs((ensure_utc(o.original_starts_at) - original_starts_at).total_seconds()) < 1:
            return True
    # Tight check in case horizon missed a far-future exception
    occs2 = recurrence_service.expand_event_occurrences(
        fake_event,  # type: ignore[arg-type]
        range_start=start,
        range_end=end,
        include_cancelled=True,
    )
    return any(
        abs((ensure_utc(o.original_starts_at) - original_starts_at).total_seconds()) < 1
        for o in occs2
    )


def analyze_exception_mismatches(
    db: Session,
    event: MaintenanceEvent,
    *,
    new_rrule: str | None = None,
    new_starts_at: datetime | None = None,
    new_ends_at: datetime | None = None,
    now: datetime | None = None,
) -> list[ExceptionMismatch]:
    """Identify exceptions that would stop matching after an RRULE/DTSTART change."""
    if not event.recurrence_rule:
        return []
    now = ensure_utc(now or _now())
    # Build prospective event for slot checks
    prospective_starts = ensure_utc(new_starts_at) if new_starts_at else ensure_utc(event.starts_at)
    prospective_ends = ensure_utc(new_ends_at) if new_ends_at else ensure_utc(event.ends_at)
    body = new_rrule if new_rrule is not None else event.recurrence_rule.rrule

    from types import SimpleNamespace

    probe = SimpleNamespace(
        id=event.id,
        starts_at=prospective_starts,
        ends_at=prospective_ends,
        timezone=event.timezone,
        is_recurring=True,
        recurrence_rule=SimpleNamespace(rrule=body, until_at=None, exceptions=[]),
    )

    records = records_for_event(db, event.id)
    mismatches: list[ExceptionMismatch] = []
    for ex in event.recurrence_rule.exceptions or []:
        orig = ensure_utc(ex.original_starts_at)
        compatible = _slot_in_new_rule(
            probe,  # type: ignore[arg-type]
            new_rrule=body,
            original_starts_at=orig,
        )
        rec = None
        for k, v in records.items():
            if abs((k - orig).total_seconds()) < 1:
                rec = v
                break
        executed = bool(
            rec
            and rec.status
            in {
                EventStatus.in_progress,
                EventStatus.extended,
                EventStatus.verifying,
                EventStatus.completed,
                EventStatus.cancelled,
            }
        )
        historical = orig < now or executed
        if compatible and not (historical and executed):
            continue
        if compatible and historical:
            # Compatible historical — no mismatch
            continue
        mismatches.append(
            ExceptionMismatch(
                original_starts_at=orig,
                action=ex.action,
                reason="slot_missing_after_rrule_change" if not compatible else "ok",
                historical=historical,
                has_execution_record=executed,
                compatible=compatible,
            )
        )
    # Also flag execution records without exceptions that fall off the new rule
    for orig, rec in records.items():
        if rec.status == EventStatus.scheduled and not (
            rec.expected_starts_at or rec.expected_impact or rec.description or rec.impacts_overridden
        ):
            continue
        compatible = _slot_in_new_rule(
            probe,  # type: ignore[arg-type]
            new_rrule=body,
            original_starts_at=orig,
        )
        if compatible:
            continue
        if any(
            abs((m.original_starts_at - orig).total_seconds()) < 1 for m in mismatches
        ):
            continue
        mismatches.append(
            ExceptionMismatch(
                original_starts_at=orig,
                action="lifecycle_record",
                reason="slot_missing_after_rrule_change",
                historical=True,
                has_execution_record=rec.status != EventStatus.scheduled,
                compatible=False,
            )
        )
    return mismatches


def apply_exception_reconciliation(
    db: Session,
    event: MaintenanceEvent,
    *,
    mismatches: list[ExceptionMismatch],
    policy: str,
    drop_originals: list[datetime] | None = None,
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Reconcile exceptions before RRULE mutate.

    Policies:
      - keep_historical_require_future: preserve executed/historical; require explicit
        drop list (or policy drop_incompatible_future) for incompatible *future* exceptions
      - drop_incompatible_future: drop only incompatible future exceptions (not historical)
      - fail_on_incompatible: raise if any incompatible future remains unlisted

    Never deletes OccurrenceRecord execution state or notification deliveries.
    """
    policy = (policy or "keep_historical_require_future").lower().replace("-", "_")
    drop_set = {ensure_utc(d) for d in (drop_originals or [])}
    now = _now()

    incompatible_future = [
        m
        for m in mismatches
        if not m.compatible and not m.historical and not m.has_execution_record
    ]
    historical_kept = [
        m for m in mismatches if m.historical or m.has_execution_record
    ]

    if policy == "fail_on_incompatible" and incompatible_future:
        raise ValueError(
            "Incompatible future exceptions require explicit handling: "
            + ", ".join(m.original_starts_at.isoformat() for m in incompatible_future)
        )

    if policy == "keep_historical_require_future" and incompatible_future:
        unresolved = [
            m
            for m in incompatible_future
            if not any(abs((d - m.original_starts_at).total_seconds()) < 1 for d in drop_set)
        ]
        if unresolved:
            raise ValueError(
                "Incompatible future exceptions must be listed in drop_exception_originals "
                "or use exception_reconcile=drop_incompatible_future: "
                + ", ".join(m.original_starts_at.isoformat() for m in unresolved)
            )

    dropped: list[str] = []
    to_drop: list[datetime] = []
    if policy == "drop_incompatible_future":
        to_drop = [m.original_starts_at for m in incompatible_future]
    else:
        to_drop = list(drop_set)

    if event.recurrence_rule and to_drop:
        remaining: list[RecurrenceException] = []
        for ex in list(event.recurrence_rule.exceptions or []):
            orig = ensure_utc(ex.original_starts_at)
            if any(abs((d - orig).total_seconds()) < 1 for d in to_drop):
                # Never drop if there is an execution/notification audit record
                rec = find_record(db, event.id, orig)
                if rec and rec.status != EventStatus.scheduled:
                    remaining.append(ex)
                    continue
                dropped.append(orig.isoformat())
                db.delete(ex)
            else:
                remaining.append(ex)
        db.flush()

    db.add(
        EventTimelineEntry(
            event_id=event.id,
            at=now,
            actor_id=actor_id,
            entry_type=TimelineEntryType.system,
            payload={
                "action": "exception_reconciliation",
                "policy": policy,
                "dropped_exceptions": dropped,
                "preserved_historical": [
                    m.original_starts_at.isoformat() for m in historical_kept
                ],
                "mismatch_count": len(mismatches),
            },
        )
    )
    return {
        "policy": policy,
        "dropped": dropped,
        "preserved_historical": [m.original_starts_at.isoformat() for m in historical_kept],
        "mismatches": [
            {
                "original_starts_at": m.original_starts_at.isoformat(),
                "action": m.action,
                "reason": m.reason,
                "historical": m.historical,
                "has_execution_record": m.has_execution_record,
                "compatible": m.compatible,
            }
            for m in mismatches
        ],
    }


def list_occurrence_history(
    db: Session,
    event: MaintenanceEvent,
    *,
    original_starts_at: datetime,
) -> dict[str, Any]:
    """Timeline entries + notification deliveries scoped to one occurrence."""
    from maintenancehub_api.models import NotificationDelivery

    original_starts_at = ensure_utc(original_starts_at)
    occ_id = recurrence_service.occurrence_id_for(event.id, original_starts_at)
    orig_key = _orig_key(original_starts_at)

    timeline = []
    for entry in event.timeline or []:
        payload = entry.payload or {}
        if payload.get("occurrence_id") == occ_id:
            timeline.append(entry)
            continue
        if payload.get("original_starts_at"):
            try:
                ts = ensure_utc(
                    datetime.fromisoformat(
                        str(payload["original_starts_at"]).replace("Z", "+00:00")
                    )
                )
                if abs((ts - original_starts_at).total_seconds()) < 1:
                    timeline.append(entry)
            except ValueError:
                pass

    deliveries = (
        db.query(NotificationDelivery)
        .filter(NotificationDelivery.event_id == event.id)
        .order_by(NotificationDelivery.created_at.asc())
        .all()
    )
    occ_deliveries = [
        d
        for d in deliveries
        if orig_key in (d.idempotency_key or "") or occ_id in (d.idempotency_key or "")
    ]
    return {
        "occurrence_id": occ_id,
        "timeline": timeline,
        "deliveries": occ_deliveries,
    }


def overlay_status_for_expand(
    db: Session,
    event: MaintenanceEvent,
) -> dict[datetime, EventStatus]:
    """Map original_starts_at → occurrence status for dashboard/ICS/list overlays."""
    return {
        ensure_utc(r.original_starts_at): r.status
        for r in db.query(OccurrenceRecord).filter(OccurrenceRecord.event_id == event.id).all()
    }


def impact_app_ids_for_occurrence(
    event: MaintenanceEvent,
    record: OccurrenceRecord | None,
) -> set[str]:
    from maintenancehub_api.domain.impacts import application_ids, effective_impacts

    return application_ids(effective_impacts(event, record))
