from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, get_current_user, require_roles
from maintenancehub_api.domain import events as event_service
from maintenancehub_api.domain.authz import ensure_app_grants
from maintenancehub_api.models import EventStatus, ImpactTargetType
from maintenancehub_api.schemas.events import (
    CancelRequest,
    EventCreate,
    EventOut,
    EventUpdate,
    ExtendRequest,
    RescheduleRequest,
    TimelineEntryOut,
    TimelineNoteCreate,
    TransitionRequest,
)

router = APIRouter(prefix="/events", tags=["events"])


def _to_out(event) -> EventOut:  # noqa: ANN001
    return EventOut.model_validate(event)


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
    if body.recurrence is not None:
        # M3b incomplete — reject silent fake-success; allow create without applying RRULE
        pass
    app_ids = {
        i.target_id
        for i in (body.impacts or [])
        if i.target_type == "application"
    }
    ensure_app_grants(db, user, app_ids, action="create event")
    try:
        event = event_service.create_event(db, data=body.model_dump(), actor_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.recurrence is not None:
        # Persist flag only; expansion not implemented (see docs/LIMITATIONS.md)
        event.is_recurring = True
        db.commit()
        event = event_service.get_event(db, event.id)
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
