"""Public experience-profile endpoint (M17)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from maintenancehub_api.config import get_settings
from maintenancehub_api.domain import experience as exp

router = APIRouter(tags=["experience"])


@router.get("/experience")
def get_experience() -> dict:
    """Unauthenticated: UI shapes chrome before login."""
    settings = get_settings()
    return exp.experience_payload(settings.experience_profile)


def require_capability(capability: str) -> None:
    settings = get_settings()
    if not exp.has_capability(settings.experience_profile, capability):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Capability '{capability}' is not enabled for experience profile "
                f"'{exp.normalize_profile(settings.experience_profile)}'."
            ),
        )
