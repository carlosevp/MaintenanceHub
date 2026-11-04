"""Application-scoped authorization (server-side grants)."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from maintenancehub_api.deps import AuthUser
from maintenancehub_api.models import ApplicationGrant, RoleName


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
