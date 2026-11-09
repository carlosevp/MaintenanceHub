"""Resolve subscription targets to human-readable catalog labels."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from maintenancehub_api.models import (
    DEFAULT_NOTIFY_EVENTS,
    Application,
    Environment,
    MaintenanceEvent,
    Subscription,
)

CHANNEL_LABELS = {
    "email_address": "Email",
    "teams_bridge_channel": "Teams (email bridge)",
}

NOTIFY_EVENT_LABELS = {
    "start": "Start",
    "extension": "Extension",
    "cancellation": "Cancellation",
    "completion": "Completion",
}

# Map lifecycle / template keys → interest categories on the subscription.
LIFECYCLE_TO_NOTIFY: dict[str, str] = {
    "event.created": "start",
    "event.confirmed": "start",
    "event.scheduled": "start",
    "event.transitioned": "start",
    "event.impacts_changed": "start",
    "event.reminder": "start",
    "event.extended": "extension",
    "event.rescheduled": "extension",
    "event.cancelled": "cancellation",
    "event.completed": "completion",
}


def normalize_notify_events(raw: Any) -> list[str]:
    """Empty/null → all default interests (backward compatible)."""
    if not raw:
        return list(DEFAULT_NOTIFY_EVENTS)
    out: list[str] = []
    for item in raw:
        key = str(item).strip().lower()
        if key in NOTIFY_EVENT_LABELS and key not in out:
            out.append(key)
    return out or list(DEFAULT_NOTIFY_EVENTS)


def subscription_allows_lifecycle(sub: Subscription, *, template_key: str, reason: str) -> bool:
    interests = set(normalize_notify_events(sub.notify_events))
    category = LIFECYCLE_TO_NOTIFY.get(template_key)
    if category is None and reason == "reminder":
        category = "start"
    if category is None:
        # Unknown lifecycle types still deliver (fail open for new keys).
        return True
    return category in interests


def format_reminder_label(offset_minutes: int) -> str:
    abs_m = abs(offset_minutes)
    prefix = "before start" if offset_minutes <= 0 else "after start"
    if abs_m % 1440 == 0:
        days = abs_m // 1440
        return f"{days}d {prefix}"
    if abs_m % 60 == 0:
        hours = abs_m // 60
        return f"{hours}h {prefix}"
    return f"{abs_m}m {prefix}"


def resolve_target_label(
    db: Session,
    *,
    target_type: str,
    target_id: str,
) -> dict[str, Any]:
    """Build a friendly target payload; never raise on missing catalog refs."""
    base: dict[str, Any] = {
        "target_type": target_type,
        "target_id": target_id,
        "application_id": None,
        "application_name": None,
        "application_key": None,
        "environment_id": None,
        "environment_name": None,
        "environment_key": None,
        "event_title": None,
        "label": "",
        "scope_label": "",
        "missing": False,
    }

    if target_type == "application":
        app = db.get(Application, target_id)
        if not app:
            base["missing"] = True
            base["label"] = "Unknown application (removed from catalog)"
            base["scope_label"] = "Entire application"
            return base
        base["application_id"] = app.id
        base["application_name"] = app.name
        base["application_key"] = app.key
        base["label"] = app.name
        base["scope_label"] = "Entire application (any environment)"
        return base

    if target_type == "app_environment":
        app_id, env_id = (target_id.split(":", 1) + [""])[:2] if ":" in target_id else ("", "")
        app = db.get(Application, app_id) if app_id else None
        env = db.get(Environment, env_id) if env_id else None
        base["application_id"] = app_id or None
        base["environment_id"] = env_id or None
        missing_parts: list[str] = []
        if app:
            base["application_name"] = app.name
            base["application_key"] = app.key
        else:
            missing_parts.append("application")
            base["application_name"] = "Unknown application"
        if env:
            base["environment_name"] = env.name
            base["environment_key"] = env.key
        else:
            missing_parts.append("environment")
            base["environment_name"] = "Unknown environment"
            base["environment_key"] = env_id[:8] if env_id else "?"
        base["missing"] = bool(missing_parts)
        app_label = base["application_name"]
        env_label = f"{base['environment_name']} ({base['environment_key']})"
        base["label"] = f"{app_label} · {env_label}"
        base["scope_label"] = f"Environment: {env_label}"
        return base

    if target_type == "environment":
        env = db.get(Environment, target_id)
        if not env:
            base["missing"] = True
            base["label"] = "Unknown environment (removed from catalog)"
            base["scope_label"] = "Environment"
            return base
        base["environment_id"] = env.id
        base["environment_name"] = env.name
        base["environment_key"] = env.key
        base["label"] = f"{env.name} ({env.key})"
        base["scope_label"] = "Any application in this environment"
        return base

    if target_type == "event":
        event = db.get(MaintenanceEvent, target_id)
        if not event:
            base["missing"] = True
            base["label"] = "Unknown maintenance event"
            base["scope_label"] = "Single event"
            return base
        base["event_title"] = event.title
        base["label"] = event.title
        base["scope_label"] = "Single event"
        return base

    base["missing"] = True
    base["label"] = f"Unsupported target ({target_type})"
    base["scope_label"] = target_type
    return base


def enrich_subscription(db: Session, sub: Subscription) -> dict[str, Any]:
    notify = normalize_notify_events(sub.notify_events)
    channel = CHANNEL_LABELS.get(sub.destination_type, sub.destination_type)
    targets_out = []
    for t in sub.targets or []:
        resolved = resolve_target_label(db, target_type=t.target_type, target_id=t.target_id)
        targets_out.append(
            {
                "id": t.id,
                **resolved,
            }
        )
    reminders_out = [
        {
            "id": r.id,
            "offset_minutes": r.offset_minutes,
            "label": format_reminder_label(r.offset_minutes),
        }
        for r in sorted(sub.reminders or [], key=lambda x: x.offset_minutes)
    ]
    return {
        "id": sub.id,
        "user_id": sub.user_id,
        "is_active": sub.is_active,
        "digest_mode": sub.digest_mode,
        "destination_type": sub.destination_type,
        "destination": sub.destination,
        "bridge_channel_key": sub.bridge_channel_key,
        "notify_events": notify,
        "notify_event_labels": [NOTIFY_EVENT_LABELS[k] for k in notify],
        "channel_label": channel,
        "targets": targets_out,
        "reminders": reminders_out,
    }
