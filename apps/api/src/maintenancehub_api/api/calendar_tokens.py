from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.config import get_settings
from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, get_current_user
from maintenancehub_api.domain import ics as ics_service
from maintenancehub_api.domain.calendar_reachability import assess_public_base_url
from maintenancehub_api.models import Application, CalendarToken, MaintenanceEvent
from maintenancehub_api.schemas.subscriptions import (
    CalendarFeedReachability,
    CalendarTokenCreate,
    CalendarTokenCreated,
    CalendarTokenOut,
)

router = APIRouter(tags=["calendar-tokens"])


def _reachability() -> CalendarFeedReachability:
    return CalendarFeedReachability.model_validate(
        assess_public_base_url(get_settings().public_base_url)
    )


@router.get("/calendar/reachability", response_model=CalendarFeedReachability)
def calendar_reachability(
    _: AuthUser = Depends(get_current_user),
) -> CalendarFeedReachability:
    return _reachability()


def _events_with_recurrence(
    db: Session, events: list[MaintenanceEvent]
) -> list[MaintenanceEvent]:
    if not events:
        return []
    ids = [e.id for e in events]
    return (
        db.query(MaintenanceEvent)
        .options(joinedload(MaintenanceEvent.recurrence_rule))
        .filter(MaintenanceEvent.id.in_(ids))
        .order_by(MaintenanceEvent.starts_at.asc())
        .all()
    )


@router.get("/calendar/download.ics")
def download_ics(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
    application_id: str | None = Query(
        default=None,
        description="Optional: download events for one application instead of favorites+subscriptions.",
    ),
    include_alarms: bool = Query(
        default=False,
        description=(
            "When true, emit VALARM from the caller's My Alerts reminder offsets "
            "on events matching those subscriptions."
        ),
    ),
) -> Response:
    """Authenticated static ICS snapshot.

    Default scope: favorites + active subscriptions. With ``application_id``, scope is
    that application's impacts only (safe reuse of ICS generation). Empty scope still
    returns a valid empty calendar. Snapshot is not auto-updated.
    """
    cal_name = "MaintenanceHub"
    filename = "maintenancehub-calendar.ics"
    if application_id:
        app = db.get(Application, application_id)
        if not app:
            raise HTTPException(status_code=404, detail="Application not found")
        events = ics_service.events_for_application(
            db, application_id, include_cancelled=True
        )
        cal_name = f"MaintenanceHub — {app.name}"
        safe_key = "".join(c if c.isalnum() or c in "-_" else "-" for c in app.key) or "app"
        filename = f"maintenancehub-{safe_key}.ics"
    else:
        events = ics_service.events_for_user(
            db,
            user.id,
            scopes=["favorites", "subscriptions"],
            include_cancelled=True,
        )
    events = _events_with_recurrence(db, events)
    alarm_map = (
        ics_service.alarm_offsets_for_user(db, user.id, events) if include_alarms else None
    )
    body = ics_service.build_ics(
        events,
        calendar_name=cal_name,
        alarm_offsets_by_event=alarm_map,
    )
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-MH-Calendar-Event-Count": str(len(events)),
            "X-MH-Calendar-Include-Alarms": "1" if include_alarms else "0",
        },
    )


@router.post("/calendar-tokens", response_model=CalendarTokenCreated, status_code=201)
def create_token(
    body: CalendarTokenCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> CalendarTokenCreated:
    row, raw = ics_service.create_calendar_token(
        db,
        user_id=user.id,
        scopes=body.scopes,
        label=body.label,
        include_alarms=body.include_alarms,
    )
    reach = _reachability()
    base = (get_settings().public_base_url or "").rstrip("/")
    feed_url = f"{base}/api/v1/public/ics/{raw}" if base else f"/api/v1/public/ics/{raw}"
    return CalendarTokenCreated(
        id=row.id,
        scopes=row.scopes or [],
        label=row.label,
        include_alarms=bool(row.include_alarms),
        expires_at=row.expires_at.isoformat() if row.expires_at else None,
        revoked_at=None,
        created_at=row.created_at.isoformat() if row.created_at else None,
        token=raw,
        feed_url=feed_url,
        reachability=reach,
    )


@router.get("/calendar-tokens", response_model=list[CalendarTokenOut])
def list_tokens(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> list[CalendarTokenOut]:
    rows = (
        db.query(CalendarToken)
        .filter(CalendarToken.user_id == user.id)
        .order_by(CalendarToken.created_at.desc())
        .all()
    )
    return [
        CalendarTokenOut(
            id=r.id,
            scopes=r.scopes or [],
            label=r.label,
            include_alarms=bool(r.include_alarms),
            expires_at=r.expires_at.isoformat() if r.expires_at else None,
            revoked_at=r.revoked_at.isoformat() if r.revoked_at else None,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]


@router.delete("/calendar-tokens/{token_id}", status_code=204)
def revoke_token(
    token_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> None:
    if not ics_service.revoke_token(db, token_id, user.id):
        raise HTTPException(status_code=404, detail="Token not found")


@router.get("/public/ics/{token}")
def public_ics(token: str, db: Session = Depends(get_db)) -> Response:
    row = ics_service.resolve_token(db, token)
    if not row:
        raise HTTPException(status_code=401, detail="Invalid or revoked calendar token")
    events = ics_service.events_for_token(db, row)
    events = _events_with_recurrence(db, events)
    alarm_map = None
    if row.include_alarms:
        alarm_map = ics_service.alarm_offsets_for_user(db, row.user_id, events)
    body = ics_service.build_ics(
        events,
        calendar_name="MaintenanceHub",
        alarm_offsets_by_event=alarm_map,
    )
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="maintenancehub.ics"',
            "X-MH-Calendar-Include-Alarms": "1" if row.include_alarms else "0",
        },
    )
