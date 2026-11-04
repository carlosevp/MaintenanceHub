from __future__ import annotations

from datetime import datetime, timezone as tz

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, get_current_user, require_roles
from maintenancehub_api.domain import communication as comm
from maintenancehub_api.domain import events as event_service
from maintenancehub_api.domain import recurrence as recurrence_service
from maintenancehub_api.domain.authz import ensure_app_grants
from maintenancehub_api.models import EventStatus, ImpactTargetType
from maintenancehub_api.schemas.events import (
    CancelRequest,
    EventCreate,
    EventOut,
    EventUpdate,
    ExtendRequest,
    OccurrenceExceptionRequest,
    RecurrenceOut,
    RecurrenceExceptionOut,
    RecurrencePreviewRequest,
    RecurrenceSpec,
    RescheduleRequest,
    SeriesEditRequest,
    TimelineEntryOut,
    TimelineNoteCreate,
    TransitionRequest,
)

router = APIRouter(prefix="/events", tags=["events"])


def _recurrence_out(event) -> RecurrenceOut | None:  # noqa: ANN001
    rule = getattr(event, "recurrence_rule", None)
    if not rule:
        return None
    return RecurrenceOut(
        rrule=rule.rrule,
        until_at=rule.until_at,
        summary=recurrence_service.human_summary(rule.rrule, timezone_name=event.timezone),
        exceptions=[
            RecurrenceExceptionOut(
                id=ex.id,
                original_starts_at=ex.original_starts_at,
                action=ex.action,
                new_starts_at=ex.new_starts_at,
                new_ends_at=ex.new_ends_at,
            )
            for ex in (rule.exceptions or [])
        ],
    )


def _to_out(event) -> EventOut:  # noqa: ANN001
    data = EventOut.model_validate(event)
    data.recurrence = _recurrence_out(event)
    data.phase = comm.communication_phase(
        event, now=datetime.now(tz.utc), starts_at=event.starts_at, ends_at=event.ends_at
    )
    return data


@router.post("/recurrence/preview")
def preview_recurrence(
    body: RecurrencePreviewRequest,
    _: AuthUser = Depends(get_current_user),
) -> dict:
    try:
        occs = recurrence_service.preview_occurrences(
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            timezone_name=body.timezone,
            recurrence=body.recurrence.model_dump(exclude_none=True),
            count=body.count,
            exceptions=[e.model_dump(exclude_none=True) for e in body.exceptions],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    summary = recurrence_service.human_summary(
        body.recurrence.model_dump(exclude_none=True), timezone_name=body.timezone
    )
    return {"summary": summary, "occurrences": occs}


def _impact_app_ids(event) -> set[str]:  # noqa: ANN001
    return {
        i.target_id
        for i in (event.impacts or [])
        if i.target_type == ImpactTargetType.application
    }


def _require_event_grant(db, user: AuthUser, event) -> None:  # noqa: ANN001
    ensure_app_grants(db, user, _impact_app_ids(event), action="mutate event")


@router.get("", response_model=list[EventOut])
def list_events(
    kind: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    approval_state: str | None = None,
    application_id: str | None = None,
    environment_id: str | None = None,
    q: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> list[EventOut]:
    items, _total = event_service.list_events(
        db,
        kind=kind,
        status=status_filter,
        approval_state=approval_state,
        application_id=application_id,
        environment_id=environment_id,
        q=q,
        from_dt=from_,
        to_dt=to,
        limit=limit,
        offset=offset,
    )
    return [_to_out(e) for e in items]


@router.post("", response_model=EventOut, status_code=201)
def create_event(
    body: EventCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles("publisher", "application_owner", "platform_administrator")),
) -> EventOut:
    data = body.model_dump()
    if body.recurrence is not None:
        data["recurrence"] = body.recurrence.model_dump(exclude_none=True)
    app_ids = {
        i.target_id
        for i in (body.impacts or [])
        if i.target_type == "application"
    }
    ensure_app_grants(db, user, app_ids, action="create event")
    try:
        if body.timezone:
            recurrence_service.resolve_tz(body.timezone)
        event = event_service.create_event(db, data=data, actor_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(event)


@router.get("/{event_id}", response_model=EventOut)
def get_event(
    event_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> EventOut:
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return _to_out(event)


@router.patch("/{event_id}", response_model=EventOut)
def update_event(
    event_id: str,
    body: EventUpdate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles("publisher", "application_owner", "platform_administrator")),
) -> EventOut:
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    _require_event_grant(db, user, event)
    try:
        updated = event_service.update_event_fields(
            db, event, data=body.model_dump(exclude_unset=True), actor_id=user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(updated)


@router.get("/{event_id}/recurrence", response_model=RecurrenceOut)
def get_recurrence(
    event_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> RecurrenceOut:
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    out = _recurrence_out(event)
    if not out:
        raise HTTPException(status_code=404, detail="No recurrence rule")
    return out


@router.put("/{event_id}/recurrence", response_model=EventOut)
def put_recurrence(
    event_id: str,
    body: RecurrenceSpec,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles("publisher", "application_owner", "platform_administrator")),
) -> EventOut:
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    _require_event_grant(db, user, event)
    try:
        updated = event_service.set_recurrence(
            db, event, recurrence=body.model_dump(exclude_none=True), actor_id=user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(updated)


@router.post("/{event_id}/occurrences/exception", response_model=EventOut)
def occurrence_exception(
    event_id: str,
    body: OccurrenceExceptionRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles("publisher", "application_owner", "platform_administrator")),
) -> EventOut:
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    _require_event_grant(db, user, event)
    try:
        updated = event_service.exception_for_occurrence(
            db,
            event,
            original_starts_at=body.original_starts_at,
            action=body.action,
            new_starts_at=body.new_starts_at,
            new_ends_at=body.new_ends_at,
            actor_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(updated)


@router.post("/{event_id}/series-edit", response_model=EventOut)
def series_edit(
    event_id: str,
    body: SeriesEditRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles("publisher", "application_owner", "platform_administrator")),
) -> EventOut:
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    _require_event_grant(db, user, event)
    try:
        updated = event_service.edit_series(
            db,
            event,
            scope=body.scope,
            original_starts_at=body.original_starts_at,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            title=body.title,
            description=body.description,
            expected_impact=body.expected_impact,
            approval_state=body.approval_state,
            recurrence=(
                body.recurrence.model_dump(exclude_none=True) if body.recurrence else None
            ),
            actor_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(updated)


@router.get("/{event_id}/occurrences")
def list_occurrences(
    event_id: str,
    from_: datetime = Query(..., alias="from"),
    to: datetime = Query(...),
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> list[dict]:
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    occs = recurrence_service.expand_event_occurrences(
        event, range_start=from_, range_end=to, include_cancelled=True
    )
    now = datetime.now(tz.utc)
    return [
        {
            "occurrence_id": o.occurrence_id,
            "event_id": o.event_id,
            "series_id": o.event_id,
            "original_starts_at": o.original_starts_at.isoformat(),
            "starts_at": o.starts_at.isoformat(),
            "ends_at": o.ends_at.isoformat(),
            "cancelled": o.cancelled,
            "is_exception": o.is_exception,
            "approval_state": event.approval_state.value,
            "status": event.status.value,
            "phase": comm.communication_phase(
                event, now=now, starts_at=o.starts_at, ends_at=o.ends_at
            ),
            "title": event.title,
        }
        for o in occs
    ]


@router.post("/{event_id}/transition", response_model=EventOut)
def transition(
    event_id: str,
    body: TransitionRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles("publisher", "application_owner", "platform_administrator")),
) -> EventOut:
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    _require_event_grant(db, user, event)
    try:
        updated = event_service.transition_event(
            db,
            event,
            target_status=EventStatus(body.status),
            actor_id=user.id,
            note=body.note,
            ends_at=body.ends_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_out(updated)


@router.post("/{event_id}/extend", response_model=EventOut)
def extend(
    event_id: str,
    body: ExtendRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles("publisher", "application_owner", "platform_administrator")),
) -> EventOut:
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    _require_event_grant(db, user, event)
    try:
        updated = event_service.extend_event(
            db, event, new_ends_at=body.new_ends_at, actor_id=user.id, note=body.note
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_out(updated)


@router.post("/{event_id}/reschedule", response_model=EventOut)
def reschedule(
    event_id: str,
    body: RescheduleRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles("publisher", "application_owner", "platform_administrator")),
) -> EventOut:
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    _require_event_grant(db, user, event)
    try:
        if event.is_recurring and body.scope != "all":
            updated = event_service.edit_series(
                db,
                event,
                scope=body.scope,
                original_starts_at=body.original_starts_at,
                starts_at=body.starts_at,
                ends_at=body.ends_at,
                actor_id=user.id,
            )
        else:
            updated = event_service.reschedule_event(
                db,
                event,
                starts_at=body.starts_at,
                ends_at=body.ends_at,
                actor_id=user.id,
                note=body.note,
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_out(updated)


@router.post("/{event_id}/cancel", response_model=EventOut)
def cancel(
    event_id: str,
    body: CancelRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles("publisher", "application_owner", "platform_administrator")),
) -> EventOut:
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    _require_event_grant(db, user, event)
    try:
        if event.is_recurring and body.scope == "this":
            if not body.original_starts_at:
                raise ValueError("original_starts_at required to cancel one occurrence")
            updated = event_service.exception_for_occurrence(
                db,
                event,
                original_starts_at=body.original_starts_at,
                action="cancel",
                actor_id=user.id,
            )
        else:
            updated = event_service.cancel_event(db, event, actor_id=user.id, note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_out(updated)


@router.get("/{event_id}/timeline", response_model=list[TimelineEntryOut])
def timeline(
    event_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> list[TimelineEntryOut]:
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return [TimelineEntryOut.model_validate(e) for e in event.timeline]


@router.post("/{event_id}/timeline", response_model=TimelineEntryOut, status_code=201)
def add_note(
    event_id: str,
    body: TimelineNoteCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles("publisher", "application_owner", "platform_administrator")),
) -> TimelineEntryOut:
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    _require_event_grant(db, user, event)
    entry = event_service.add_timeline_note(db, event, actor_id=user.id, note=body.note)
    return TimelineEntryOut.model_validate(entry)
