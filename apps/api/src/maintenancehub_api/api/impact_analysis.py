"""M14 — Impact analysis preview (read-only) and confirmation publish."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, get_current_user, require_roles
from maintenancehub_api.domain import events as event_service
from maintenancehub_api.domain import impact_preview as preview_service
from maintenancehub_api.domain.authz import ensure_app_grants, ensure_impact_mutation
from maintenancehub_api.domain.impacts import application_ids, impacts_from_dicts, series_impacts
from maintenancehub_api.schemas.events import EventOut
from maintenancehub_api.schemas.impact_analysis import ImpactConfirmRequest, ImpactPreviewRequest
from maintenancehub_api.api.events import _to_out

router = APIRouter(prefix="/impact-analysis", tags=["impact-analysis"])


@router.post("/preview")
def preview_impact(
    body: ImpactPreviewRequest,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> dict:
    """Read-only impact + audience + conflict preview. Never sends notifications."""
    if body.ends_at <= body.starts_at:
        raise HTTPException(status_code=400, detail="ends_at must be after starts_at")
    if body.event_id:
        event = event_service.get_event(db, body.event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
    try:
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
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/events/{event_id}/confirm", response_model=EventOut)
def confirm_impact(
    event_id: str,
    body: ImpactConfirmRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(
        require_roles("publisher", "application_owner", "platform_administrator")
    ),
) -> EventOut:
    """Persist confirmed impacts after revision validation; optionally publish (outbox).

    Authz: publisher must own seed applications. Downstream includes are notification
    suggestions — not permission to assert those apps unavailable. Reassigning solely
    to unowned apps is rejected.
    """
    event = event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    seeds = impacts_from_dicts([s.model_dump() for s in body.seeds])
    seed_apps = application_ids(seeds)
    # Ownership is on seed applications only. Downstream suggestions are notify-reach
    # candidates — not permission to assert those apps unavailable.
    ensure_app_grants(
        db, user, seed_apps, action="confirm impact analysis on seed apps"
    )
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
    # Prefer seed apps as ownership basis so infra-only seeds can still notify
    # downstream apps without requiring grants on every suggested consumer.
    ownership_basis = seeds if seed_apps else (prior if prior else seeds)
    if application_ids(ownership_basis) or not application_ids(next_imps):
        ensure_impact_mutation(
            db,
            user,
            prior_impacts=ownership_basis,
            next_impacts=next_imps,
            action="confirm impact analysis",
        )
    # else: infra/service-only seeds + downstream apps — role gate above is enough;
    # notify downstream ≠ assert unavailable on those apps.

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
        code = 409 if "Stale" in detail else 400
        raise HTTPException(status_code=code, detail=detail) from exc
    return _to_out(updated)
