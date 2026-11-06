"""Server-side validation of impact confirm payloads (M14 harden)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from maintenancehub_api.deps import AuthUser
from maintenancehub_api.domain import dependency_analysis as dep_analysis
from maintenancehub_api.domain.authz import ensure_app_grants, granted_application_ids
from maintenancehub_api.domain.impacts import ImpactRef, application_ids, impacts_from_dicts, series_impacts
from maintenancehub_api.models import (
    Application,
    Environment,
    InfraComponent,
    MaintenanceEvent,
    Service,
)


def _key(t: str, i: str, e: str | None) -> tuple[str, str, str | None]:
    return (t, i, e)


def ref_key(r: ImpactRef) -> tuple[str, str, str | None]:
    return _key(r.target_type, r.target_id, r.environment_id)


def dict_key(row: dict[str, Any]) -> tuple[str, str, str | None]:
    return _key(row["target_type"], row["target_id"], row.get("environment_id"))


def ensure_catalog_target_exists(db: Session, ref: ImpactRef) -> None:
    if ref.target_type == "application":
        if not db.get(Application, ref.target_id):
            raise ValueError(f"Unknown application id {ref.target_id}")
    elif ref.target_type == "service":
        if not db.get(Service, ref.target_id):
            raise ValueError(f"Unknown service id {ref.target_id}")
    elif ref.target_type == "infra_component":
        if not db.get(InfraComponent, ref.target_id):
            raise ValueError(f"Unknown infra_component id {ref.target_id}")
    else:
        raise ValueError(f"Unsupported target_type {ref.target_type}")
    if ref.environment_id and not db.get(Environment, ref.environment_id):
        raise ValueError(f"Unknown environment id {ref.environment_id}")


def ensure_preview_access(
    db: Session,
    user: AuthUser,
    seeds: list[ImpactRef],
) -> None:
    """Publishers/owners/admins only; seed apps require grants."""
    if not user.can_publish:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Impact preview requires publisher, application_owner, or platform_administrator",
        )
    ensure_app_grants(db, user, application_ids(seeds), action="preview impact analysis")


def ensure_confirm_event_access(
    db: Session,
    user: AuthUser,
    event: MaintenanceEvent,
    seeds: list[ImpactRef],
) -> None:
    """Prevent infra-only confirm from hijacking arbitrary events.

    - Seed apps → grants on those apps.
    - Else prior series app impacts → grants on those.
    - Else infra/service-only → creator or admin.
    """
    if user.is_admin:
        return
    seed_apps = application_ids(seeds)
    if seed_apps:
        ensure_app_grants(db, user, seed_apps, action="confirm impact analysis on seed apps")
        return
    prior_apps = application_ids(series_impacts(event))
    if prior_apps:
        ensure_app_grants(
            db, user, prior_apps, action="confirm impact analysis on owned event"
        )
        return
    if event.created_by and event.created_by == user.id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Cannot confirm impact analysis on this event without seed-app grants "
            "or being the event creator"
        ),
    )


def validate_manual_additions(
    db: Session,
    user: AuthUser,
    manuals: list[dict[str, Any]] | None,
) -> list[ImpactRef]:
    """Manual adds must reference real catalog rows; apps require grants (or admin)."""
    refs = impacts_from_dicts(manuals or [])
    for r in refs:
        ensure_catalog_target_exists(db, r)
    app_ids = application_ids(refs)
    if app_ids and not user.is_admin:
        # Authorized manual add = grant on that application
        ensure_app_grants(db, user, app_ids, action="manually add impacted application")
    return refs


def validate_include_downstream(
    db: Session,
    *,
    seeds: list[ImpactRef],
    include_downstream: list[dict[str, Any]] | None,
    max_depth: int,
) -> list[ImpactRef]:
    """Downstream includes must be in the freshly calculated suggestion set."""
    if include_downstream is None:
        return []
    analysis = dep_analysis.analyze_downstream_impacts(
        db, seeds=seeds, max_depth=max_depth
    )
    suggested = {sug.key for sug in analysis.downstream}
    seed_keys = {ref_key(s) for s in seeds}
    out: list[ImpactRef] = []
    seen: set[tuple[str, str, str | None]] = set()
    for row in include_downstream:
        ref = impacts_from_dicts([row])[0]
        ensure_catalog_target_exists(db, ref)
        k = ref_key(ref)
        if k in seed_keys:
            continue  # seeds already included
        if k not in suggested:
            raise ValueError(
                "include_downstream contains a target that is not a calculated "
                f"suggestion ({ref.target_type}:{ref.target_id}); re-run preview"
            )
        if k in seen:
            continue
        seen.add(k)
        out.append(ref)
    return out


def audience_may_include_destinations(
    db: Session,
    user: AuthUser,
    seeds: list[ImpactRef],
) -> bool:
    """Recipient addresses only for authorized publishers (not bare viewers)."""
    if not user.can_publish:
        return False
    if user.is_admin:
        return True
    seed_apps = application_ids(seeds)
    if not seed_apps:
        # Infra/service-only seeds: publisher role is enough for destination lists
        return True
    granted = granted_application_ids(db, user)
    return seed_apps <= granted
