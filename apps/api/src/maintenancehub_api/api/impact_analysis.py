"""M14 — Impact analysis preview (read-only) and confirmation publish."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from maintenancehub_api.api.events import _to_out
from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, require_roles
from maintenancehub_api.domain import events as event_service
from maintenancehub_api.domain import impact_preview as preview_service
from maintenancehub_api.domain import impact_validation as impact_val
from maintenancehub_api.domain.authz import ensure_impact_mutation
from maintenancehub_api.domain.impacts import application_ids, impacts_from_dicts, series_impacts
from maintenancehub_api.schemas.events import EventOut
from maintenancehub_api.schemas.impact_analysis import ImpactConfirmRequest, ImpactPreviewRequest

router = APIRouter(prefix="/impact-analysis", tags=["impact-analysis"])

_PUBLISHER_ROLES = ("publisher", "application_owner", "platform_administrator")


@router.post("/preview")
def preview_impact(
    body: ImpactPreviewRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(*_PUBLISHER_ROLES)),
) -> dict:
    """Read-only impact + audience + conflict preview. Never sends notifications.

    Viewers are rejected. Destination addresses are included only for authorized
    publishers (counts always returned).
    """
    if body.ends_at <= body.starts_at:
        raise HTTPException(status_code=400, detail="ends_at must be after starts_at")
    seeds = impacts_from_dicts([s.model_dump() for s in body.seeds])
    try:
        for s in seeds:
            impact_val.ensure_catalog_target_exists(db, s)
        impact_val.ensure_preview_access(db, user, seeds)
        if body.event_id:
            event = event_service.get_event(db, body.event_id)
            if not event:
                raise HTTPException(status_code=404, detail="Event not found")
        include_dest = impact_val.audience_may_include_destinations(db, user, seeds)
        return preview_service.build_preview(
            db,
            seeds=[s.model_dump() for s in body.seeds],
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            event_id=body.event_id,
            original_starts_at=body.original_starts_at,
            exclusions=body.exclusions,
            manual_additions=[m.model_dump() for m in body.manual_additions],
            max_depth=body.max_depth,
            include_destinations=include_dest,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/events/{event_id}/confirm", response_model=EventOut)
def confirm_impact(
    event_id: str,
    body: ImpactConfirmRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(*_PUBLISHER_ROLES)),
) -> EventOut:
    """Persist confirmed impacts after revision validation; optionally publish (outbox).

    Downstream includes must appear in calculated suggestions. Manual adds require
    catalog validity + grants. Notify downstream ≠ assert those apps unavailable.
    """
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    seeds = impacts_from_dicts([s.model_dump() for s in body.seeds])
    try:
        for s in seeds:
            impact_val.ensure_catalog_target_exists(db, s)
        impact_val.ensure_confirm_event_access(db, user, event, seeds)
        impact_val.validate_manual_additions(
            db, user, [m.model_dump() for m in body.manual_additions]
        )
        if body.include_downstream is not None:
            impact_val.validate_include_downstream(
                db,
                seeds=seeds,
                include_downstream=[m.model_dump() for m in body.include_downstream],
                max_depth=body.max_depth,
            )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    prior = series_impacts(event)
    next_rows = [s.model_dump() for s in body.seeds]
    if body.include_downstream:
        next_rows.extend(m.model_dump() for m in body.include_downstream)
    if body.manual_additions:
        next_rows.extend(m.model_dump() for m in body.manual_additions)
    excl = {
        (x.get("target_type"), x.get("target_id"), x.get("environment_id"))
        for x in (body.exclusions or [])
    }
    next_imps = [
        r
        for r in impacts_from_dicts(next_rows)
        if (r.target_type, r.target_id, r.environment_id) not in excl
    ]
    ownership_basis = seeds if application_ids(seeds) else (prior if prior else seeds)
    if application_ids(ownership_basis) or not application_ids(next_imps):
        ensure_impact_mutation(
            db,
            user,
            prior_impacts=ownership_basis,
            next_impacts=next_imps,
            action="confirm impact analysis",
        )

    try:
        updated = preview_service.confirm_impact_analysis(
            db,
            event,
            revision_token=body.revision_token,
            seeds=[s.model_dump() for s in body.seeds],
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            exclusions=body.exclusions,
            manual_additions=[m.model_dump() for m in body.manual_additions],
            include_downstream=(
                [m.model_dump() for m in body.include_downstream]
                if body.include_downstream is not None
                else None
            ),
            original_starts_at=body.original_starts_at,
            actor_id=user.id,
            max_depth=body.max_depth,
            publish=body.publish,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 409 if ("Stale" in detail or "unreviewed" in detail) else 400
        raise HTTPException(status_code=code, detail=detail) from exc
    return _to_out(updated)
