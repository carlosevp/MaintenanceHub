"""Public / internal banner message selection (M18).

Exact application + environment matching against *confirmed* effective impacts
(series defaults or occurrence overrides, including confirmed downstream apps).
Approved-only windows never appear. Advance window is configurable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.domain import communication as comm
from maintenancehub_api.domain import occurrences as occurrence_service
from maintenancehub_api.domain import recurrence as recurrence_service
from maintenancehub_api.domain.impacts import ImpactRef, effective_impacts
from maintenancehub_api.models import (
    Application,
    ApprovalState,
    Environment,
    EventStatus,
    MaintenanceEvent,
)
from maintenancehub_api.schemas.common import ensure_utc

# Safe public presentation labels — never "approved" as outage.
PRES_OUTAGE = "outage"
PRES_IN_PROGRESS = "in_progress"
PRES_EXTENDED = "extended"
PRES_VERIFYING = "verifying"
PRES_UPCOMING = "upcoming"

PUBLIC_KEYS = frozenset(
    {
        "id",
        "event_id",
        "kind",
        "title",
        "status",
        "presentation",
        "starts_at",
        "ends_at",
        "expected_impact",
        "approval_state",
        "revision",
        "dismissible",
        "occurrence_starts_at",
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def impact_matches_app_env(
    impacts: list[ImpactRef],
    *,
    application_id: str,
    environment_id: str | None,
) -> bool:
    """Exact app(+env) match. Unrelated apps never match.

    When ``environment_id`` is set, the impact pair must match exactly
    ``(application_id, environment_id)``. Impacts with a null environment do
    not satisfy a specific env filter (exactness).
    When env is omitted, any impact for the application matches.
    """
    for ref in impacts:
        if not ref.is_application:
            continue
        if ref.target_id != application_id:
            continue
        if environment_id is None:
            return True
        if ref.environment_id == environment_id:
            return True
    return False


def presentation_for(
    event: MaintenanceEvent,
    *,
    now: datetime,
    starts_at: datetime,
    ends_at: datetime,
    status: EventStatus,
) -> str:
    """Map lifecycle to a public presentation label.

    Approved windows are never returned by the query layer; this still refuses
    to label anything as an outage unless it is a confirmed manual outage that
    is actively executing.
    """
    if event.approval_state != ApprovalState.confirmed_scheduled:
        return PRES_UPCOMING
    if comm.is_active_outage(
        event, now=now, starts_at=starts_at, ends_at=ends_at, status=status
    ):
        return PRES_OUTAGE
    if status == EventStatus.extended and ensure_utc(starts_at) <= ensure_utc(now) <= ensure_utc(
        ends_at
    ):
        return PRES_EXTENDED
    if status == EventStatus.verifying and ensure_utc(starts_at) <= ensure_utc(now) <= ensure_utc(
        ends_at
    ):
        return PRES_VERIFYING
    if status in {EventStatus.in_progress, EventStatus.extended, EventStatus.verifying}:
        if ensure_utc(starts_at) <= ensure_utc(now) <= ensure_utc(ends_at):
            return PRES_IN_PROGRESS
    return PRES_UPCOMING


def _revision(
    *,
    ends_at: datetime,
    status: EventStatus,
    updated_at: datetime | None,
) -> str:
    """Opaque token so dismissed upcoming banners re-show after extend/update."""
    stamp = ensure_utc(updated_at).isoformat() if updated_at else ""
    return f"{ensure_utc(ends_at).isoformat()}|{status.value}|{stamp}"


def _message_dict(
    event: MaintenanceEvent,
    *,
    now: datetime,
    starts_at: datetime,
    ends_at: datetime,
    status: EventStatus,
    occurrence_starts_at: datetime | None,
    is_occurrence: bool,
    updated_at: datetime | None,
) -> dict[str, Any]:
    if is_occurrence and occurrence_starts_at is not None:
        msg_id = recurrence_service.occurrence_id_for(event.id, occurrence_starts_at)
    else:
        msg_id = event.id
    presentation = presentation_for(
        event, now=now, starts_at=starts_at, ends_at=ends_at, status=status
    )
    dismissible = presentation == PRES_UPCOMING
    return {
        "id": msg_id,
        "event_id": event.id,
        "kind": event.kind.value if hasattr(event.kind, "value") else str(event.kind),
        "title": event.title,
        "status": status.value if hasattr(status, "value") else str(status),
        "presentation": presentation,
        "starts_at": ensure_utc(starts_at).isoformat().replace("+00:00", "Z"),
        "ends_at": ensure_utc(ends_at).isoformat().replace("+00:00", "Z"),
        "expected_impact": event.expected_impact,
        "approval_state": (
            event.approval_state.value
            if hasattr(event.approval_state, "value")
            else str(event.approval_state)
        ),
        "revision": _revision(ends_at=ends_at, status=status, updated_at=updated_at),
        "dismissible": dismissible,
        "occurrence_starts_at": (
            ensure_utc(occurrence_starts_at).isoformat().replace("+00:00", "Z")
            if occurrence_starts_at is not None and is_occurrence
            else None
        ),
    }


def list_banner_messages(
    db: Session,
    *,
    application_key: str,
    environment_key: str | None = None,
    advance_hours: float = 24.0,
    now: datetime | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return confirmed active + upcoming messages for exact app(+env).

    Includes confirmed downstream impacts (stored as effective impacts).
    Never includes ``approved_window`` or cancelled/completed occurrences.
    """
    now = ensure_utc(now or _now())
    advance_hours = max(0.0, min(float(advance_hours), 168.0))
    horizon = now + timedelta(hours=advance_hours)
    window_start = now - timedelta(hours=1)

    app = db.query(Application).filter(Application.key == application_key).one_or_none()
    if app is None:
        return []

    env_id: str | None = None
    if environment_key:
        env = db.query(Environment).filter(Environment.key == environment_key).one_or_none()
        if env is None:
            return []
        env_id = env.id

    # Confirmed masters only — approved_window never surfaces as outage/maintenance.
    candidates = (
        db.query(MaintenanceEvent)
        .options(
            joinedload(MaintenanceEvent.impacts),
            joinedload(MaintenanceEvent.occurrence_records),
        )
        .filter(
            MaintenanceEvent.approval_state == ApprovalState.confirmed_scheduled,
            MaintenanceEvent.status != EventStatus.cancelled,
        )
        .all()
    )

    out: list[dict[str, Any]] = []

    for event in candidates:
        if event.status == EventStatus.completed and not event.is_recurring:
            continue
        if not recurrence_service.master_may_intersect_window(
            event, range_start=window_start, range_end=horizon
        ):
            continue

        status_map = occurrence_service.overlay_status_for_expand(db, event)
        occs = recurrence_service.expand_event_occurrences(
            event, range_start=window_start, range_end=horizon
        )
        for occ in occs:
            occ_status: EventStatus | None = None
            for k, v in status_map.items():
                if abs((k - occ.original_starts_at).total_seconds()) < 1:
                    occ_status = v
                    break
            if occ_status is None and not event.is_recurring:
                occ_status = event.status
            elif occ_status is None:
                occ_status = EventStatus.scheduled
            if occ_status in {EventStatus.completed, EventStatus.cancelled}:
                continue

            record = occurrence_service.find_record(db, event.id, occ.original_starts_at)
            starts, ends = occurrence_service.effective_times(occ, record)
            starts_u, ends_u = ensure_utc(starts), ensure_utc(ends)

            # Active in window OR upcoming within advance horizon
            active = starts_u <= now <= ends_u and occ_status in {
                EventStatus.in_progress,
                EventStatus.extended,
                EventStatus.verifying,
                EventStatus.scheduled,  # rare: scheduled but window already open
            }
            upcoming = starts_u > now and starts_u <= horizon and occ_status == EventStatus.scheduled
            # Also surface executing that overlaps now even if "scheduled" bleed avoided
            executing_now = comm.is_executing_now(
                event, now=now, starts_at=starts_u, ends_at=ends_u, status=occ_status
            )
            if not (active or upcoming or executing_now):
                # Scheduled window that already started but not transitioned — still show if in window
                if occ_status == EventStatus.scheduled and starts_u <= now <= ends_u:
                    pass
                else:
                    continue

            impacts = effective_impacts(event, record)
            if not impact_matches_app_env(
                impacts, application_id=app.id, environment_id=env_id
            ):
                continue

            updated = None
            if record is not None and getattr(record, "updated_at", None):
                updated = record.updated_at
            elif getattr(event, "updated_at", None):
                updated = event.updated_at

            out.append(
                _message_dict(
                    event,
                    now=now,
                    starts_at=starts_u,
                    ends_at=ends_u,
                    status=occ_status,
                    occurrence_starts_at=occ.original_starts_at,
                    is_occurrence=bool(event.is_recurring),
                    updated_at=updated,
                )
            )

    # Prefer active / outage first, then soonest start
    rank = {
        PRES_OUTAGE: 0,
        PRES_EXTENDED: 1,
        PRES_IN_PROGRESS: 2,
        PRES_VERIFYING: 3,
        PRES_UPCOMING: 4,
    }
    out.sort(key=lambda m: (rank.get(m["presentation"], 9), m["starts_at"]))
    return out[:limit]
