"""Application-scoped authorization (server-side grants)."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from maintenancehub_api.deps import AuthUser
from maintenancehub_api.domain.impacts import ImpactRef, application_ids, effective_impacts
from maintenancehub_api.models import ApplicationGrant, MaintenanceEvent, OccurrenceRecord, RoleName


def granted_application_ids(db: Session, user: AuthUser) -> set[str]:
    if user.is_admin:
        return set()  # unused when admin; callers short-circuit
    rows = (
        db.query(ApplicationGrant)
        .filter(ApplicationGrant.user_id == user.id)
        .all()
    )
    return {g.application_id for g in rows}


def ensure_app_grants(
    db: Session,
    user: AuthUser,
    application_ids: list[str] | set[str],
    *,
    action: str = "mutate",
) -> None:
    """Require ApplicationGrant for each app unless platform administrator.

    Publishers / application owners must hold a grant on every impacted application.
    Global role alone is insufficient — closes the gap where any publisher could
    mutate any catalog app.
    """
    ids = {a for a in application_ids if a}
    if not ids:
        return
    if user.is_admin:
        return
    if user.is_service:
        # Service credentials are scoped separately; publication scopes are future work.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Service credentials cannot perform this action",
        )

    grants = (
        db.query(ApplicationGrant)
        .filter(
            ApplicationGrant.user_id == user.id,
            ApplicationGrant.application_id.in_(ids),
        )
        .all()
    )
    granted = {g.application_id for g in grants}
    missing = ids - granted
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Missing application grant to {action} applications: "
                f"{', '.join(sorted(missing))}"
            ),
        )


def ensure_lifecycle_access(
    db: Session,
    user: AuthUser,
    event: MaintenanceEvent,
    record: OccurrenceRecord | None = None,
    *,
    action: str = "lifecycle",
) -> None:
    """Lifecycle transitions require grants on every *effective* impacted application.

    Empty explicit occurrence override → no app gate (series-level admin/publisher
    with empty impacts is rare; still allow if no apps to authorize).
    """
    apps = application_ids(effective_impacts(event, record))
    ensure_app_grants(db, user, apps, action=action)


def ensure_impact_mutation(
    db: Session,
    user: AuthUser,
    *,
    prior_impacts: list[ImpactRef],
    next_impacts: list[ImpactRef],
    action: str = "change impacts",
) -> None:
    """Authorize writing impacts on a maintenance / occurrence.

    - User must hold grants on all *prior* application impacts (owns the maintenance).
      If prior is empty, require grants on all next apps (initial assignment).
    - Newly added apps beyond prior are **proposed downstream impacts** and do not
      require grants (informational cross-app effect).
    - Next set must retain at least one granted app when non-empty — cannot reassign
      the occurrence/event so that only unowned apps remain (that would be modifying
      another application's maintenance state).
    """
    if user.is_admin:
        return
    if user.is_service:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Service credentials cannot perform this action",
        )

    prior_apps = application_ids(prior_impacts)
    next_apps = application_ids(next_impacts)
    granted = granted_application_ids(db, user)

    if prior_apps:
        ensure_app_grants(db, user, prior_apps, action=f"own maintenance to {action}")
    elif next_apps:
        ensure_app_grants(db, user, next_apps, action=action)

    if next_apps and not (next_apps & granted):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Cannot reassign impacts solely to applications outside your grants "
                f"({', '.join(sorted(next_apps))}); proposing downstream apps is "
                "allowed only while retaining at least one owned application"
            ),
        )


def grant_user_on_application(
    db: Session,
    *,
    user_id: str,
    application_id: str,
    role: str = RoleName.publisher.value,
) -> ApplicationGrant:
    existing = (
        db.query(ApplicationGrant)
        .filter(
            ApplicationGrant.user_id == user_id,
            ApplicationGrant.application_id == application_id,
            ApplicationGrant.role == role,
        )
        .first()
    )
    if existing:
        return existing
    row = ApplicationGrant(
        user_id=user_id,
        application_id=application_id,
        role=role,
    )
    db.add(row)
    db.flush()
    return row
