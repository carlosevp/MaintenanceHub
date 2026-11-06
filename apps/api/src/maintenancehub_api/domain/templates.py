"""Simple notification template rendering (str.format placeholders)."""

from __future__ import annotations

from typing import Any


DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    "event.created": {
        "subject": "[MaintenanceHub] {approval_label}: {title}",
        "body": (
            "A maintenance/outage communication was published.\n\n"
            "Title: {title}\n"
            "Kind: {kind}\n"
            "Lifecycle status: {status}\n"
            "Communication: {approval_label} ({approval_state})\n"
            "Window: {starts_at} → {ends_at} ({timezone})\n"
            "Expected impact: {expected_impact}\n"
            "Detail: {detail_url}\n\n"
            "Note: Approval state is independent of the calendar window — "
            "an approved window is not confirmed communication until confirmed.\n"
        ),
    },
    "event.transitioned": {
        "subject": "[MaintenanceHub] {status}: {title}",
        "body": (
            "Lifecycle update (human-published — not monitoring).\n\n"
            "Title: {title}\n"
            "What changed: {from_status} → {status}\n"
            "Communication: {approval_label} ({approval_state})\n"
            "Window: {starts_at} → {ends_at} ({timezone})\n"
            "Note: {note}\n"
            "Detail: {detail_url}\n"
        ),
    },
    "event.extended": {
        "subject": "[MaintenanceHub] Extended: {title}",
        "body": (
            "Maintenance window extended (confirmed communication).\n\n"
            "Title: {title}\n"
            "What changed: end time {previous_ends_at} → {ends_at}\n"
            "Status: {status}\n"
            "Note: {note}\n"
            "Detail: {detail_url}\n"
        ),
    },
    "event.rescheduled": {
        "subject": "[MaintenanceHub] Rescheduled: {title}",
        "body": (
            "Schedule changed.\n\n"
            "Title: {title}\n"
            "What changed: new window {starts_at} → {ends_at} ({timezone})\n"
            "Communication: {approval_label} ({approval_state})\n"
            "Note: {note}\n"
            "Detail: {detail_url}\n"
        ),
    },
    "event.reminder": {
        "subject": "[MaintenanceHub] Reminder ({offset_label}): {title}",
        "body": (
            "Upcoming confirmed maintenance reminder.\n\n"
            "Title: {title}\n"
            "Starts: {starts_at}\n"
            "Ends: {ends_at}\n"
            "Timezone: {timezone}\n"
            "Offset: {offset_label}\n"
            "Expected impact: {expected_impact}\n"
            "Detail: {detail_url}\n\n"
            "You may receive one message even if multiple subscriptions match "
            "(deduplicated by destination).\n"
        ),
    },
}


def approval_label(approval_state: str) -> str:
    if approval_state == "confirmed_scheduled":
        return "Confirmed"
    if approval_state == "approved_window":
        return "Approved window (not yet confirmed)"
    return approval_state or "Unknown"


def render_template(template: str, context: dict[str, Any]) -> str:
    class _Safe(dict):
        def __missing__(self, key: str) -> str:
            return ""

    return template.format_map(_Safe(**{k: ("" if v is None else v) for k, v in context.items()}))
