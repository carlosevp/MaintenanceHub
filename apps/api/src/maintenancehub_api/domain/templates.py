"""Simple notification template rendering (str.format placeholders)."""

from __future__ import annotations

from typing import Any


DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    "event.created": {
        "subject": "[MaintenanceHub] Scheduled: {title}",
        "body": (
            "A maintenance/outage communication was published.\n\n"
            "Title: {title}\nKind: {kind}\nStatus: {status}\n"
            "Approval: {approval_state}\nWindow: {starts_at} → {ends_at} ({timezone})\n"
            "Impact: {expected_impact}\n"
        ),
    },
    "event.transitioned": {
        "subject": "[MaintenanceHub] {status}: {title}",
        "body": (
            "Lifecycle update.\n\nTitle: {title}\nFrom: {from_status}\nTo: {status}\n"
            "Window: {starts_at} → {ends_at}\nNote: {note}\n"
        ),
    },
    "event.extended": {
        "subject": "[MaintenanceHub] Extended: {title}",
        "body": (
            "Maintenance window extended.\n\nTitle: {title}\n"
            "Previous end: {previous_ends_at}\nNew end: {ends_at}\nNote: {note}\n"
        ),
    },
    "event.rescheduled": {
        "subject": "[MaintenanceHub] Rescheduled: {title}",
        "body": (
            "Schedule changed.\n\nTitle: {title}\n"
            "New window: {starts_at} → {ends_at}\nNote: {note}\n"
        ),
    },
    "event.reminder": {
        "subject": "[MaintenanceHub] Reminder ({offset_label}): {title}",
        "body": (
            "Upcoming maintenance reminder.\n\nTitle: {title}\n"
            "Starts: {starts_at}\nEnds: {ends_at}\nOffset: {offset_label}\n"
        ),
    },
}


def render_template(template: str, context: dict[str, Any]) -> str:
    class _Safe(dict):
        def __missing__(self, key: str) -> str:
            return ""

    return template.format_map(_Safe(**{k: ("" if v is None else v) for k, v in context.items()}))
