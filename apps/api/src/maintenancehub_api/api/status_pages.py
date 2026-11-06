"""Shareable status pages — viewer-permitted communication status (M16)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, get_current_user
from maintenancehub_api.domain import communication as comm
from maintenancehub_api.domain import recurrence as recurrence_service
from maintenancehub_api.schemas.common import ensure_utc
from maintenancehub_api.models import (
    Application,
    ApprovalState,
    Environment,
    EventImpact,
    EventStatus,
    ImpactTargetType,
    MaintenanceEvent,
    RecurrenceRule,
)

router = APIRouter(prefix="/status", tags=["status-pages"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _public_event(e: MaintenanceEvent, *, phase: str | None = None) -> dict[str, Any]:
    return {
        "id": e.id,
        "kind": e.kind.value if hasattr(e.kind, "value") else e.kind,
        "title": e.title,
        "status": e.status.value if hasattr(e.status, "value") else e.status,
        "approval_state": (
            e.approval_state.value if hasattr(e.approval_state, "value") else e.approval_state
        ),
        "starts_at": e.starts_at.isoformat() if e.starts_at else None,
        "ends_at": e.ends_at.isoformat() if e.ends_at else None,
        "timezone": e.timezone,
        "expected_impact": e.expected_impact,
        "phase": phase
        or comm.communication_phase(e, now=_now(), starts_at=e.starts_at, ends_at=e.ends_at),
        "share_path": f"/status/events/{e.id}",
        # Never include internal notes / timeline / created_by
    }


@router.get("/applications/{application_key}")
def status_application(
    application_key: str,
    environment_key: str | None = Query(None),
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Viewer status for an application (optional environment). Confirmed communications only for active."""
    app = db.query(Application).filter(Application.key == application_key).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    env = None
    if environment_key:
        env = db.query(Environment).filter(Environment.key == environment_key).first()
        if not env:
            raise HTTPException(status_code=404, detail="Environment not found")

    now = _now()
    q = (
        db.query(MaintenanceEvent)
        .options(joinedload(MaintenanceEvent.impacts))
        .join(EventImpact)
        .filter(
            EventImpact.target_type == ImpactTargetType.application,
            EventImpact.target_id == app.id,
            MaintenanceEvent.status.in_(
                [
                    EventStatus.scheduled,
                    EventStatus.in_progress,
                    EventStatus.extended,
                    EventStatus.verifying,
                ]
            ),
            MaintenanceEvent.ends_at >= now - timedelta(hours=1),
        )
        .distinct()
    )
    if env:
        q = q.filter(EventImpact.environment_id == env.id)

    events = q.order_by(MaintenanceEvent.starts_at.asc()).limit(40).all()
    active: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    approved_only: list[dict[str, Any]] = []
    for e in events:
        starts = ensure_utc(e.starts_at)
        ends = ensure_utc(e.ends_at)
        phase = comm.communication_phase(e, now=now, starts_at=starts, ends_at=ends)
        item = _public_event(e, phase=phase)
        if e.approval_state == ApprovalState.approved_window:
            approved_only.append(item)
            continue
        if phase == "executing" and starts <= now <= ends:
            active.append(item)
        elif starts > now:
            upcoming.append(item)

    return {
        "application": {"id": app.id, "key": app.key, "name": app.name},
        "environment": (
            {"id": env.id, "key": env.key, "name": env.name} if env else None
        ),
        "as_of": now.isoformat(),
        "active": active,
        "upcoming_confirmed": upcoming,
        "approved_window_not_confirmed": approved_only,
        "note": (
            "Active status requires confirmed communication and human-published executing "
            "lifecycle — never inferred from the scheduled window alone."
        ),
        "share_path": (
            f"/status/apps/{app.key}"
            + (f"/envs/{env.key}" if env else "")
        ),
        "ics_note": (
            "ICS feeds refresh on client poll intervals; they are not push-realtime. "
            "Create a token under Subscriptions."
        ),
    }


def _event_status_payload(db: Session, event_id: str) -> dict[str, Any]:
    e = (
        db.query(MaintenanceEvent)
        .options(
            joinedload(MaintenanceEvent.impacts),
            joinedload(MaintenanceEvent.recurrence_rule).joinedload(RecurrenceRule.exceptions),
        )
        .filter(MaintenanceEvent.id == event_id)
        .first()
    )
    if not e:
        raise HTTPException(status_code=404, detail="Event not found")
    now = _now()
    phase = comm.communication_phase(e, now=now, starts_at=e.starts_at, ends_at=e.ends_at)
    impacts = [
        {
            "target_type": i.target_type.value if hasattr(i.target_type, "value") else i.target_type,
            "target_id": i.target_id,
            "environment_id": i.environment_id,
        }
        for i in (e.impacts or [])
    ]
    occs: list[dict[str, Any]] = []
    if e.is_recurring:
        for occ in recurrence_service.expand_event_occurrences(
            e, range_start=now - timedelta(days=1), range_end=now + timedelta(days=30)
        )[:10]:
            occs.append(
                {
                    "original_starts_at": occ.original_starts_at.isoformat(),
                    "starts_at": occ.starts_at.isoformat(),
                    "ends_at": occ.ends_at.isoformat(),
                }
            )
    return {
        **_public_event(e, phase=phase),
        "impacts": impacts,
        "is_recurring": e.is_recurring,
        "upcoming_occurrences": occs,
        "note": (
            "Shareable status for authenticated viewers. Description/internal notes omitted. "
            "Approved windows are listed separately from confirmed communication."
        ),
    }


@router.get("/events/{event_id}")
def status_event(
    event_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> dict[str, Any]:
    return _event_status_payload(db, event_id)


@router.get("/scheduled/{event_id}")
def status_scheduled(
    event_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Shareable scheduled-window status (same viewer-permitted fields as event status)."""
    payload = _event_status_payload(db, event_id)
    payload["share_path"] = f"/status/scheduled/{event_id}"
    payload["view"] = "scheduled"
    return payload
