from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, get_current_user
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

ACTIVE_STATUSES = {
    EventStatus.scheduled,
    EventStatus.in_progress,
    EventStatus.extended,
    EventStatus.verifying,
}


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
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    occurrence_starts_at: datetime | None = None,
    is_occurrence: bool = False,
) -> EventOut:
    data = EventOut.model_validate(e)
    data.recurrence = _recurrence_out(e)
    if starts_at is not None:
        data.starts_at = starts_at
    if ends_at is not None:
        data.ends_at = ends_at
    data.occurrence_starts_at = occurrence_starts_at
    data.is_occurrence = is_occurrence
    return data


def _masters_query(db: Session):
    return db.query(MaintenanceEvent).options(
        joinedload(MaintenanceEvent.impacts),
        joinedload(MaintenanceEvent.recurrence_rule).joinedload(RecurrenceRule.exceptions),
    )


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
    base = _masters_query(db)

    if kind:
        base = base.filter(MaintenanceEvent.kind == EventKind(kind))
    if favorites_only:
        fav_ids = [
            f.application_id
            for f in db.query(Favorite).filter(Favorite.user_id == user.id).all()
        ]
        if not fav_ids:
            empty = DashboardSlice(count=0, items=[])
            return DashboardSummary(
                current=empty, upcoming=empty, recent=empty, outages=empty, as_of=now
            )
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

    # Load candidates that could intersect the window (masters + recurring)
    candidates = (
        base.filter(
            MaintenanceEvent.status != EventStatus.cancelled,
        )
        .all()
    )

    current_items: list[EventOut] = []
    upcoming_items: list[EventOut] = []
    outage_items: list[EventOut] = []

    for e in candidates:
        if e.status == EventStatus.completed:
            continue
        # Expand in a window covering current + upcoming horizon
        window_start = now - timedelta(days=1)
        window_end = horizon
        if e.is_recurring and e.recurrence_rule:
            occs = recurrence_service.expand_event_occurrences(
                e, range_start=window_start, range_end=window_end
            )
        else:
            occs = recurrence_service.expand_event_occurrences(
                e, range_start=window_start, range_end=window_end
            )
        for occ in occs:
            # Lifecycle for one-shot uses event.status; recurring masters stay scheduled
            # until series cancelled — occurrence "current" is time-based.
            is_current = occ.starts_at <= now <= occ.ends_at
            is_upcoming = occ.starts_at > now
            item = _event_out(
                e,
                starts_at=occ.starts_at,
                ends_at=occ.ends_at,
                occurrence_starts_at=occ.original_starts_at,
                is_occurrence=e.is_recurring,
            )
            if e.kind == EventKind.manual_outage and is_current:
                outage_items.append(item)
            if is_current and e.status in {
                EventStatus.in_progress,
                EventStatus.extended,
                EventStatus.verifying,
                EventStatus.scheduled,  # recurring occurrence in progress window
            }:
                current_items.append(item)
            elif is_upcoming and e.status in {
                EventStatus.scheduled,
                EventStatus.in_progress,
                EventStatus.extended,
            }:
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
        current=DashboardSlice(
            count=len(current_items), items=current_items[:limit]
        ),
        upcoming=DashboardSlice(
            count=len(upcoming_items), items=upcoming_items[:limit]
        ),
        recent=DashboardSlice(
            count=recent_q.count(), items=[_event_out(e) for e in recent_items]
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

    events = query.order_by(MaintenanceEvent.starts_at).all()
    out: list[CalendarEventOut] = []
    for e in events:
        # For one-shot, skip if outside window via expand; for recurring expand in range
        for occ in recurrence_service.expand_event_occurrences(
            e, range_start=from_, range_end=to
        ):
            out.append(
                CalendarEventOut(
                    id=occ.occurrence_id if e.is_recurring else e.id,
                    title=e.title,
                    kind=e.kind.value,
                    status=e.status.value,
                    approval_state=e.approval_state.value,
                    starts_at=occ.starts_at,
                    ends_at=occ.ends_at,
                    timezone=e.timezone,
                    is_occurrence=bool(e.is_recurring),
                    occurrence_starts_at=occ.original_starts_at if e.is_recurring else None,
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
