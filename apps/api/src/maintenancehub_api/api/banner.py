"""Read-only public banner API — minimal DTO, no internal notes (M12)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, require_scopes
from maintenancehub_api.models import (
    Application,
    ApprovalState,
    Environment,
    EventImpact,
    EventStatus,
    ImpactTargetType,
    MaintenanceEvent,
)

router = APIRouter(tags=["banner"])

# Fields intentionally excluded from public DTO: description, timeline, created_by, raw SN payload
PUBLIC_BANNER_FIELDS = (
    "id",
    "kind",
    "title",
    "status",
    "starts_at",
    "ends_at",
    "expected_impact",
    "approval_state",
)


def _to_public_dto(event: MaintenanceEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "kind": event.kind.value if hasattr(event.kind, "value") else event.kind,
        "title": event.title,
        "status": event.status.value if hasattr(event.status, "value") else event.status,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat(),
        "expected_impact": event.expected_impact,
        "approval_state": (
            event.approval_state.value
            if hasattr(event.approval_state, "value")
            else event.approval_state
        ),
    }


@router.get("/public/banner")
def public_banner(
    application_key: str = Query(..., description="Application catalog key"),
    environment_key: str | None = Query(
        default=None, description="Optional global environment key (e.g. PROD)"
    ),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_scopes("banner:read")),
) -> list[dict[str, Any]]:
    """Active + upcoming confirmed messages for an app (and optional env).

    Auth: service credential with `banner:read`, or publisher/admin user.
    """
    if user.is_service and not user.has_scope("banner:read"):
        raise HTTPException(status_code=403, detail="banner:read required")

    app = db.query(Application).filter(Application.key == application_key).first()
    if not app:
        return []

    now = datetime.now(timezone.utc)
    q = (
        db.query(MaintenanceEvent)
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
            MaintenanceEvent.approval_state == ApprovalState.confirmed_scheduled,
            MaintenanceEvent.ends_at >= now,
        )
    )
    if environment_key:
        env = db.query(Environment).filter(Environment.key == environment_key).first()
        if not env:
            return []
        q = q.filter(EventImpact.environment_id == env.id)

    events = q.distinct().order_by(MaintenanceEvent.starts_at.asc()).limit(20).all()
    return [_to_public_dto(e) for e in events]
