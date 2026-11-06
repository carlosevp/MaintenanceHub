"""Centralized experience-profile capability registry (M17).

UI, API, and workers consult this map. There is no scattered feature-flag
matrix and no admin UI for toggling capabilities.

Unknown profiles fail closed (never silently become Enterprise).
Demo scenario selection is presentation-only and cannot unlock capabilities.
"""

from __future__ import annotations

from typing import Any, Literal

ExperienceProfile = Literal["essentials", "team", "enterprise"]

VALID_PROFILES: frozenset[str] = frozenset({"essentials", "team", "enterprise"})

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
        # Embed screen is part of Essentials Claims INT story (M18).
        "banner_embed": True,
        "admin_workspace": False,
        "admin_users": False,
        "servicenow": False,
        "csv_import": False,
        "oidc_ldap_surfaces": False,
        "notification_admin": False,
        "demo_scenarios": True,
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
        "demo_scenarios": True,
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
        "demo_scenarios": True,
    },
}

_PROFILE_LABELS = {
    "essentials": "Essentials",
    "team": "Team",
    "enterprise": "Enterprise",
}

# Presentation-only demo stories. Selecting a story never changes the profile
# or unlocks APIs — it only guides the UI toward seeded synthetic data.
DEMO_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "essentials-claims-int",
        "label": "Essentials · Claims INT",
        "profile_hint": "essentials",
        "summary": "Find and subscribe to Claims in INT; simple Quick Publish.",
        "focus": {
            "application_key": "claims",
            "environment_key": "INT",
            "path": "/alerts",
        },
        "requires": [],
    },
    {
        "id": "essentials-claims-int-banner",
        "label": "Essentials · Claims INT banner",
        "profile_hint": "essentials",
        "summary": "Embed MaintenanceHub notices into Claims INT via the public banner API.",
        "focus": {
            "application_key": "claims",
            "environment_key": "INT",
            "path": "/banner-demo",
        },
        "requires": ["banner_embed"],
    },
    {
        "id": "team-weekly-payments",
        "label": "Team · Weekly Payments",
        "profile_hint": "team",
        "summary": "Recurring Payments Gateway PROD window on the calendar.",
        "focus": {
            "application_key": "payments-gateway",
            "environment_key": "PROD",
            "path": "/calendar",
            "title_contains": "Weekly Payments",
        },
        "requires": ["recurrence_editor"],
    },
    {
        "id": "advanced-oracle-nonprod",
        "label": "Advanced · Oracle NON-PROD",
        "profile_hint": "team",
        "summary": "Shared infra impact preview (Oracle NON-PROD → downstream apps).",
        "focus": {
            "path": "/events/new",
            "target_hint": "oracle",
            "environment_key": "NON-PROD",
        },
        "requires": ["impact_analysis"],
    },
]


class UnknownExperienceProfileError(ValueError):
    """Raised when EXPERIENCE_PROFILE is missing from the registry."""


def normalize_profile(raw: str | None) -> ExperienceProfile:
    """Fail closed: unknown values raise — never silently upgrade to Enterprise."""
    if raw is None or str(raw).strip() == "":
        # Empty → Essentials (safest local default); never Enterprise by silence.
        return "essentials"
    value = str(raw).strip().lower()
    if value not in VALID_PROFILES:
        raise UnknownExperienceProfileError(
            f"Unknown EXPERIENCE_PROFILE={raw!r}. "
            f"Valid values: {', '.join(sorted(VALID_PROFILES))}."
        )
    return value  # type: ignore[return-value]


def capabilities_for(profile: str | None) -> dict[str, bool]:
    return dict(_CAPABILITIES[normalize_profile(profile)])


def has_capability(profile: str | None, capability: str) -> bool:
    """Unknown capability names are denied (fail closed)."""
    caps = capabilities_for(profile)
    return bool(caps.get(capability, False))


def scenarios_for(profile: str | None) -> list[dict[str, Any]]:
    """Return demo stories visible under the active profile (presentation only)."""
    caps = capabilities_for(profile)
    out: list[dict[str, Any]] = []
    for s in DEMO_SCENARIOS:
        reqs = s.get("requires") or []
        if all(caps.get(r, False) for r in reqs):
            out.append(
                {
                    "id": s["id"],
                    "label": s["label"],
                    "summary": s["summary"],
                    "profile_hint": s["profile_hint"],
                    "focus": s["focus"],
                    "available": True,
                }
            )
        else:
            out.append(
                {
                    "id": s["id"],
                    "label": s["label"],
                    "summary": s["summary"],
                    "profile_hint": s["profile_hint"],
                    "focus": s["focus"],
                    "available": False,
                    "blocked_by": [r for r in reqs if not caps.get(r, False)],
                }
            )
    return out


def experience_payload(profile: str | None) -> dict[str, Any]:
    import os

    p = normalize_profile(profile)
    # Optional deploy/demo default (e.g. America/Chicago). UI prefers this over a
    # bare UTC browser default common in headless/cloud agents.
    configured_tz = (os.environ.get("MH_DEFAULT_TIMEZONE") or "").strip() or None
    return {
        "profile": p,
        "label": _PROFILE_LABELS[p],
        "capabilities": capabilities_for(p),
        "scenarios": scenarios_for(p),
        "default_timezone": configured_tz,
        "note": (
            "Experience profile is set via EXPERIENCE_PROFILE at deploy/demo time. "
            "Demo scenario selection is presentation-only and cannot unlock APIs. "
            "There is no in-app feature-admin UI."
        ),
    }
