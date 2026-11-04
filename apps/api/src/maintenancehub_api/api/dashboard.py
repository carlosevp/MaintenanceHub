from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, get_current_user
from maintenancehub_api.domain import communication as comm
from maintenancehub_api.domain import recurrence as recurrence_service
from maintenancehub_api.models import (
    Application,
    EventKind,
    EventStatus,
    Favorite,
    MaintenanceEvent,
    RecurrenceRule,
)
from maintenancehub_api.schemas.dashboard import (
    CalendarEventOut,
    DashboardSlice,
    DashboardSummary,
    FavoriteOut,
    FavoritesPut,
)
from maintenancehub_api.schemas.events import EventOut, RecurrenceExceptionOut, RecurrenceOut

router = APIRouter(tags=["dashboard"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _recurrence_out(e: MaintenanceEvent) -> RecurrenceOut | None:
    rule = getattr(e, "recurrence_rule", None)
    if not rule:
        return None
    return RecurrenceOut(
        rrule=rule.rrule,
        until_at=rule.until_at,
        summary=recurrence_service.human_summary(rule.rrule, timezone_name=e.timezone),
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


def _event_out(
    e: MaintenanceEvent,
    *,
    now: datetime,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    occurrence_starts_at: datetime | None = None,
    is_occurrence: bool = False,
    status: EventStatus | None = None,
) -> EventOut:
    data = EventOut.model_validate(e)
    data.recurrence = _recurrence_out(e)
    if starts_at is not None:
        data.starts_at = starts_at
    if ends_at is not None:
        data.ends_at = ends_at
    if status is not None:
        data.status = status.value
    data.occurrence_starts_at = occurrence_starts_at
    data.is_occurrence = is_occurrence
    data.series_id = e.id if is_occurrence else None
    data.phase = comm.communication_phase(
        e,
        now=now,
        starts_at=starts_at or e.starts_at,
        ends_at=ends_at or e.ends_at,
        status=status,
    )
    return data


def _masters_query(db: Session):
    return db.query(MaintenanceEvent).options(
        joinedload(MaintenanceEvent.impacts),
        joinedload(MaintenanceEvent.recurrence_rule).joinedload(RecurrenceRule.exceptions),
    )


def _apply_filters(base, *, kind, favorites_only, application_id, environment_id, user, db):
    if kind:
        base = base.filter(MaintenanceEvent.kind == EventKind(kind))
    if favorites_only:
        fav_ids = [
            f.application_id
            for f in db.query(Favorite).filter(Favorite.user_id == user.id).all()
        ]
        if not fav_ids:
            return None
        from maintenancehub_api.models import EventImpact, ImpactTargetType

        base = (
            base.join(EventImpact)
            .filter(
                EventImpact.target_type == ImpactTargetType.application,
                EventImpact.target_id.in_(fav_ids),
            )
            .distinct()
        )
    if application_id:
        from maintenancehub_api.models import EventImpact, ImpactTargetType

        base = (
            base.join(EventImpact)
            .filter(
                EventImpact.target_type == ImpactTargetType.application,
                EventImpact.target_id == application_id,
            )
            .distinct()
        )
    if environment_id:
        from maintenancehub_api.models import EventImpact

        base = base.join(EventImpact).filter(EventImpact.environment_id == environment_id).distinct()
    return base


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(
    application_id: str | None = None,
    environment_id: str | None = None,
    kind: str | None = None,
    favorites_only: bool = False,
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> DashboardSummary:
    now = _now()
    horizon = now + timedelta(days=60)
    empty = DashboardSlice(count=0, items=[])
    base = _apply_filters(
        _masters_query(db),
        kind=kind,
        favorites_only=favorites_only,
        application_id=application_id,
        environment_id=environment_id,
        user=user,
        db=db,
    )
    if base is None:
        return DashboardSummary(
            current=empty, upcoming=empty, recent=empty, outages=empty, as_of=now
        )

    candidates = base.filter(MaintenanceEvent.status != EventStatus.cancelled).all()

    current_items: list[EventOut] = []
    upcoming_items: list[EventOut] = []
    outage_items: list[EventOut] = []

    window_start = now - timedelta(days=1)
    window_end = horizon

    from maintenancehub_api.domain import occurrences as occurrence_service

    for e in candidates:
        if e.status == EventStatus.completed and not e.is_recurring:
            continue
        if not recurrence_service.master_may_intersect_window(
            e, range_start=window_start, range_end=window_end
        ):
            continue
        status_map = occurrence_service.overlay_status_for_expand(db, e)
        occs = recurrence_service.expand_event_occurrences(
            e, range_start=window_start, range_end=window_end
        )
        for occ in occs:
            occ_status = None
            for k, v in status_map.items():
                if abs((k - occ.original_starts_at).total_seconds()) < 1:
                    occ_status = v
                    break
            if occ_status is None and not e.is_recurring:
                occ_status = e.status
            elif occ_status is None:
                occ_status = EventStatus.scheduled
            if occ_status in {EventStatus.completed, EventStatus.cancelled}:
                continue
            record = occurrence_service.find_record(db, e.id, occ.original_starts_at)
            starts, ends = occurrence_service.effective_times(occ, record)
            item = _event_out(
                e,
                now=now,
                starts_at=starts,
                ends_at=ends,
                occurrence_starts_at=occ.original_starts_at,
                is_occurrence=bool(e.is_recurring),
                status=occ_status,
            )
            # Active outage: manual + confirmed + executing + in window (never approved-only)
            if comm.is_active_outage(
                e, now=now, starts_at=starts, ends_at=ends, status=occ_status
            ):
                outage_items.append(item)
            # Current = human-published executing + in window (not approved_window, not merely scheduled)
            if comm.is_executing_now(
                e, now=now, starts_at=starts, ends_at=ends, status=occ_status
            ):
                current_items.append(item)
            elif comm.is_upcoming_scheduled(
                e, now=now, starts_at=starts, status=occ_status
            ):
                upcoming_items.append(item)

    current_items.sort(key=lambda x: x.starts_at)
    upcoming_items.sort(key=lambda x: x.starts_at)
    outage_items.sort(key=lambda x: x.starts_at)

    recent_q = base.filter(
        MaintenanceEvent.status == EventStatus.completed,
        MaintenanceEvent.ends_at >= now - timedelta(days=14),
    )
    recent_items = recent_q.order_by(MaintenanceEvent.ends_at.desc()).limit(limit).all()

    return DashboardSummary(
        current=DashboardSlice(count=len(current_items), items=current_items[:limit]),
        upcoming=DashboardSlice(count=len(upcoming_items), items=upcoming_items[:limit]),
        recent=DashboardSlice(
            count=recent_q.count(), items=[_event_out(e, now=now) for e in recent_items]
        ),
        outages=DashboardSlice(count=len(outage_items), items=outage_items[:limit]),
        as_of=now,
    )


@router.get("/calendar/events", response_model=list[CalendarEventOut])
def calendar_events(
    view: str = Query("month", pattern="^(day|week|month)$"),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    application_id: str | None = None,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> list[CalendarEventOut]:
    now = _now()
    if from_ is None:
        from_ = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if to is None:
        if view == "day":
            to = from_ + timedelta(days=1)
        elif view == "week":
            to = from_ + timedelta(days=7)
        else:
            to = from_ + timedelta(days=31)

    query = _masters_query(db).filter(MaintenanceEvent.status != EventStatus.cancelled)
    if application_id:
        from maintenancehub_api.models import EventImpact, ImpactTargetType

        query = (
            query.join(EventImpact)
            .filter(
                EventImpact.target_type == ImpactTargetType.application,
                EventImpact.target_id == application_id,
            )
            .distinct()
        )

    # Pre-filter: skip masters that cannot intersect the visible window
    events = [
        e
        for e in query.order_by(MaintenanceEvent.starts_at).all()
        if recurrence_service.master_may_intersect_window(e, range_start=from_, range_end=to)
    ]
    from maintenancehub_api.domain import occurrences as occurrence_service

    out: list[CalendarEventOut] = []
    for e in events:
        status_map = occurrence_service.overlay_status_for_expand(db, e)
        for occ in recurrence_service.expand_event_occurrences(
            e, range_start=from_, range_end=to
        ):
            occ_status = EventStatus.scheduled if e.is_recurring else e.status
            for k, v in status_map.items():
                if abs((k - occ.original_starts_at).total_seconds()) < 1:
                    occ_status = v
                    break
            if occ_status == EventStatus.cancelled:
                continue
            record = occurrence_service.find_record(db, e.id, occ.original_starts_at)
            starts, ends = occurrence_service.effective_times(occ, record)
            phase = comm.communication_phase(
                e, now=now, starts_at=starts, ends_at=ends, status=occ_status
            )
            out.append(
                CalendarEventOut(
                    id=(
                        recurrence_service.occurrence_id_for(e.id, occ.original_starts_at)
                        if e.is_recurring
                        else e.id
                    ),
                    title=e.title,
                    kind=e.kind.value,
                    status=occ_status.value,
                    approval_state=e.approval_state.value,
                    starts_at=starts,
                    ends_at=ends,
                    timezone=e.timezone,
                    is_occurrence=bool(e.is_recurring),
                    occurrence_starts_at=occ.original_starts_at if e.is_recurring else None,
                    series_id=e.id if e.is_recurring else None,
                    phase=phase,
                )
            )
    out.sort(key=lambda x: x.starts_at)
    return out


@router.get("/me/favorites", response_model=FavoriteOut)
def get_favorites(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> FavoriteOut:
    rows = db.query(Favorite).filter(Favorite.user_id == user.id).all()
    return FavoriteOut(application_ids=[r.application_id for r in rows])


@router.put("/me/favorites", response_model=FavoriteOut)
def put_favorites(
    body: FavoritesPut,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> FavoriteOut:
    db.query(Favorite).filter(Favorite.user_id == user.id).delete()
    for app_id in body.application_ids:
        if db.get(Application, app_id):
            db.add(Favorite(user_id=user.id, application_id=app_id))
    db.commit()
    return get_favorites(db, user)
