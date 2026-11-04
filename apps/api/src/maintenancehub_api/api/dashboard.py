from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, get_current_user
from maintenancehub_api.models import (
    Application,
    EventKind,
    EventStatus,
    Favorite,
    MaintenanceEvent,
)
from maintenancehub_api.schemas.dashboard import (
    CalendarEventOut,
    DashboardSlice,
    DashboardSummary,
    FavoriteOut,
    FavoritesPut,
)
from maintenancehub_api.schemas.events import EventOut

router = APIRouter(tags=["dashboard"])

ACTIVE_STATUSES = {
    EventStatus.scheduled,
    EventStatus.in_progress,
    EventStatus.extended,
    EventStatus.verifying,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _event_out(e: MaintenanceEvent) -> EventOut:
    return EventOut.model_validate(e)


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
    base = db.query(MaintenanceEvent).options(joinedload(MaintenanceEvent.impacts))

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

    current_q = base.filter(
        MaintenanceEvent.status.in_(
            [EventStatus.in_progress, EventStatus.extended, EventStatus.verifying]
        ),
        MaintenanceEvent.starts_at <= now,
        MaintenanceEvent.ends_at >= now,
    )
    upcoming_q = base.filter(
        MaintenanceEvent.status == EventStatus.scheduled,
        MaintenanceEvent.starts_at > now,
    )
    recent_q = base.filter(
        MaintenanceEvent.status == EventStatus.completed,
        MaintenanceEvent.ends_at >= now - timedelta(days=14),
    )
    outages_q = base.filter(
        MaintenanceEvent.kind == EventKind.manual_outage,
        MaintenanceEvent.status.in_(
            [EventStatus.in_progress, EventStatus.extended, EventStatus.verifying]
        ),
    )

    current_items = current_q.order_by(MaintenanceEvent.starts_at).limit(limit).all()
    upcoming_items = upcoming_q.order_by(MaintenanceEvent.starts_at).limit(limit).all()
    recent_items = recent_q.order_by(MaintenanceEvent.ends_at.desc()).limit(limit).all()
    outage_items = outages_q.order_by(MaintenanceEvent.starts_at).limit(limit).all()

    return DashboardSummary(
        current=DashboardSlice(count=current_q.count(), items=[_event_out(e) for e in current_items]),
        upcoming=DashboardSlice(
            count=upcoming_q.count(), items=[_event_out(e) for e in upcoming_items]
        ),
        recent=DashboardSlice(count=recent_q.count(), items=[_event_out(e) for e in recent_items]),
        outages=DashboardSlice(count=outages_q.count(), items=[_event_out(e) for e in outage_items]),
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

    query = db.query(MaintenanceEvent).filter(
        MaintenanceEvent.starts_at <= to,
        MaintenanceEvent.ends_at >= from_,
        MaintenanceEvent.status != EventStatus.cancelled,
    )
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
    # M3b: recurrence expansion incomplete — return master events only
    return [
        CalendarEventOut(
            id=e.id,
            title=e.title,
            kind=e.kind.value,
            status=e.status.value,
            approval_state=e.approval_state.value,
            starts_at=e.starts_at,
            ends_at=e.ends_at,
            timezone=e.timezone,
            is_occurrence=False,
        )
        for e in events
    ]


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
