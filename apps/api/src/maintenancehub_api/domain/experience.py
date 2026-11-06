"""Centralized experience-profile capability registry (M17).

UI, API, and workers consult this map. There is no scattered feature-flag
matrix and no admin UI for toggling capabilities.
"""

from __future__ import annotations

from typing import Any, Literal

ExperienceProfile = Literal["essentials", "team", "enterprise"]

# Ordered for progressive disclosure: Essentials ⊂ Team ⊂ Enterprise
_CAPABILITIES: dict[str, dict[str, bool]] = {
    "essentials": {
        "overview": True,
        "calendar": True,
        "my_alerts": True,
        "quick_publish": True,
        "event_detail": True,
        "status_pages": True,
        "catalog_browse": True,
        "impact_analysis": False,
        "recurrence_editor": False,
        "banner_embed": False,
        "admin_workspace": False,
        "admin_users": False,
        "servicenow": False,
        "csv_import": False,
        "oidc_ldap_surfaces": False,
        "notification_admin": False,
    },
    "team": {
        "overview": True,
        "calendar": True,
        "my_alerts": True,
        "quick_publish": True,
        "event_detail": True,
        "status_pages": True,
        "catalog_browse": True,
        "impact_analysis": True,
        "recurrence_editor": True,
        "banner_embed": True,
        "admin_workspace": False,
        "admin_users": False,
        "servicenow": False,
        "csv_import": False,
        "oidc_ldap_surfaces": False,
        "notification_admin": True,
    },
    "enterprise": {
        "overview": True,
        "calendar": True,
        "my_alerts": True,
        "quick_publish": True,
        "event_detail": True,
        "status_pages": True,
        "catalog_browse": True,
        "impact_analysis": True,
        "recurrence_editor": True,
        "banner_embed": True,
        "admin_workspace": True,
        "admin_users": True,
        "servicenow": True,
        "csv_import": True,
        "oidc_ldap_surfaces": True,
        "notification_admin": True,
    },
}

_PROFILE_LABELS = {
    "essentials": "Essentials",
    "team": "Team",
    "enterprise": "Enterprise",
}


def normalize_profile(raw: str | None) -> ExperienceProfile:
    value = (raw or "enterprise").strip().lower()
    if value not in _CAPABILITIES:
        return "enterprise"
    return value  # type: ignore[return-value]


def capabilities_for(profile: str | None) -> dict[str, bool]:
    return dict(_CAPABILITIES[normalize_profile(profile)])


def has_capability(profile: str | None, capability: str) -> bool:
    caps = capabilities_for(profile)
    return bool(caps.get(capability, False))


def experience_payload(profile: str | None) -> dict[str, Any]:
    p = normalize_profile(profile)
    return {
        "profile": p,
        "label": _PROFILE_LABELS[p],
        "capabilities": capabilities_for(p),
        "note": (
            "Experience profile is set via EXPERIENCE_PROFILE at deploy time. "
            "There is no in-app feature-admin UI."
        ),
    }
