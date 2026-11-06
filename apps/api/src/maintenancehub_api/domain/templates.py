"""Notification template rendering, placeholders, and PA-compatible defaults (M19).

Supports legacy ``{name}`` placeholders and Power Automate-style ``{{name}}``.
HTML rendering HTML-escapes all substituted values (XSS-safe).
"""

from __future__ import annotations

import html
import re
from typing import Any

# Double-brace first, then single-brace legacy.
_DOUBLE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
_SINGLE_RE = re.compile(r"(?<!\{)\{([a-zA-Z0-9_]+)\}(?!\})")

EVENT_TYPES: list[dict[str, str]] = [
    {"key": "event.created", "label": "Event created / confirmed"},
    {"key": "event.transitioned", "label": "Lifecycle transition"},
    {"key": "event.extended", "label": "Window extended"},
    {"key": "event.rescheduled", "label": "Rescheduled"},
    {"key": "event.reminder", "label": "Reminder"},
    {"key": "pa.teams_alert", "label": "Power Automate Teams alert"},
]

PLACEHOLDERS: list[dict[str, str]] = [
    {"key": "title", "label": "Event title", "sample": "Claims INT batch window"},
    {"key": "kind", "label": "Kind", "sample": "planned_maintenance"},
    {"key": "status", "label": "Lifecycle status", "sample": "in_progress"},
    {"key": "approval_state", "label": "Approval state", "sample": "confirmed_scheduled"},
    {"key": "approval_label", "label": "Approval label", "sample": "Confirmed"},
    {"key": "starts_at", "label": "Starts at (ISO)", "sample": "2026-11-10T02:00:00Z"},
    {"key": "ends_at", "label": "Ends at (ISO)", "sample": "2026-11-10T04:00:00Z"},
    {"key": "timezone", "label": "Timezone", "sample": "America/Chicago"},
    {"key": "expected_impact", "label": "Expected impact", "sample": "Brief read-only"},
    {"key": "detail_url", "label": "Detail URL", "sample": "https://mh.example.com/events/…"},
    {"key": "event_id", "label": "Event ID", "sample": "evt-…"},
    {"key": "from_status", "label": "Previous status", "sample": "scheduled"},
    {"key": "previous_ends_at", "label": "Previous end", "sample": "2026-11-10T03:00:00Z"},
    {"key": "note", "label": "Transition note", "sample": "Started on schedule"},
    {"key": "offset_label", "label": "Reminder offset", "sample": "24h before"},
    {
        "key": "teams_target_email",
        "label": "Teams target email (PA routing line)",
        "sample": "ops-payments-channel@example.com",
        "note": "Appears in the body as To: … for Power Automate to parse — not the SMTP To header.",
    },
    {"key": "bridge_channel_key", "label": "Bridge channel key", "sample": "ops-payments"},
]


DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    "event.created": {
        "name": "Event created",
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
        "body_html": (
            "<p>A maintenance/outage communication was published.</p>"
            "<ul>"
            "<li><strong>Title:</strong> {title}</li>"
            "<li><strong>Kind:</strong> {kind}</li>"
            "<li><strong>Status:</strong> {status}</li>"
            "<li><strong>Communication:</strong> {approval_label} ({approval_state})</li>"
            "<li><strong>Window:</strong> {starts_at} → {ends_at} ({timezone})</li>"
            "<li><strong>Impact:</strong> {expected_impact}</li>"
            "</ul>"
            "<p><a href=\"{detail_url}\">Open in MaintenanceHub</a></p>"
        ),
    },
    "event.transitioned": {
        "name": "Lifecycle transition",
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
        "body_html": (
            "<p>Lifecycle update (human-published — not monitoring).</p>"
            "<ul>"
            "<li><strong>Title:</strong> {title}</li>"
            "<li><strong>Change:</strong> {from_status} → {status}</li>"
            "<li><strong>Window:</strong> {starts_at} → {ends_at}</li>"
            "<li><strong>Note:</strong> {note}</li>"
            "</ul>"
            "<p><a href=\"{detail_url}\">Open in MaintenanceHub</a></p>"
        ),
    },
    "event.extended": {
        "name": "Window extended",
        "subject": "[MaintenanceHub] Extended: {title}",
        "body": (
            "Maintenance window extended (confirmed communication).\n\n"
            "Title: {title}\n"
            "What changed: end time {previous_ends_at} → {ends_at}\n"
            "Status: {status}\n"
            "Note: {note}\n"
            "Detail: {detail_url}\n"
        ),
        "body_html": (
            "<p>Maintenance window extended.</p>"
            "<ul>"
            "<li><strong>Title:</strong> {title}</li>"
            "<li><strong>End:</strong> {previous_ends_at} → {ends_at}</li>"
            "<li><strong>Note:</strong> {note}</li>"
            "</ul>"
            "<p><a href=\"{detail_url}\">Open in MaintenanceHub</a></p>"
        ),
    },
    "event.rescheduled": {
        "name": "Rescheduled",
        "subject": "[MaintenanceHub] Rescheduled: {title}",
        "body": (
            "Schedule changed.\n\n"
            "Title: {title}\n"
            "What changed: new window {starts_at} → {ends_at} ({timezone})\n"
            "Communication: {approval_label} ({approval_state})\n"
            "Note: {note}\n"
            "Detail: {detail_url}\n"
        ),
        "body_html": (
            "<p>Schedule changed.</p>"
            "<ul>"
            "<li><strong>Title:</strong> {title}</li>"
            "<li><strong>Window:</strong> {starts_at} → {ends_at} ({timezone})</li>"
            "<li><strong>Note:</strong> {note}</li>"
            "</ul>"
            "<p><a href=\"{detail_url}\">Open in MaintenanceHub</a></p>"
        ),
    },
    "event.reminder": {
        "name": "Reminder",
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
        "body_html": (
            "<p>Upcoming confirmed maintenance reminder.</p>"
            "<ul>"
            "<li><strong>Title:</strong> {title}</li>"
            "<li><strong>Starts:</strong> {starts_at}</li>"
            "<li><strong>Ends:</strong> {ends_at}</li>"
            "<li><strong>Offset:</strong> {offset_label}</li>"
            "</ul>"
            "<p><a href=\"{detail_url}\">Open in MaintenanceHub</a></p>"
        ),
    },
    # Power Automate–compatible sample (M19). Body "To:" is routing for PA — not SMTP To.
    "pa.teams_alert": {
        "name": "Power Automate Teams Alert",
        "subject": "[TEAMS] Maintenance Alert",
        "body": (
            "To: {{teams_target_email}}\n\n"
            "MaintenanceHub notice (human-published — not monitoring).\n\n"
            "Title: {{title}}\n"
            "Status: {{status}}\n"
            "Communication: {{approval_label}} ({{approval_state}})\n"
            "Window: {{starts_at}} → {{ends_at}} ({{timezone}})\n"
            "Impact: {{expected_impact}}\n"
            "Channel: {{bridge_channel_key}}\n"
            "Detail: {{detail_url}}\n\n"
            "Power Automate: parse the first body line `To: <email>` as the Teams "
            "routing address. The SMTP envelope recipient is the bridge mailbox.\n"
        ),
        "body_html": (
            "<p><strong>To:</strong> {{teams_target_email}}</p>"
            "<p>MaintenanceHub notice (human-published — not monitoring).</p>"
            "<ul>"
            "<li><strong>Title:</strong> {{title}}</li>"
            "<li><strong>Status:</strong> {{status}}</li>"
            "<li><strong>Window:</strong> {{starts_at}} → {{ends_at}} ({{timezone}})</li>"
            "<li><strong>Impact:</strong> {{expected_impact}}</li>"
            "<li><strong>Channel:</strong> {{bridge_channel_key}}</li>"
            "</ul>"
            "<p><a href=\"{{detail_url}}\">Open in MaintenanceHub</a></p>"
            "<p><em>PA: first <code>To:</code> line is routing, not SMTP To.</em></p>"
        ),
    },
}


def approval_label(approval_state: str) -> str:
    if approval_state == "confirmed_scheduled":
        return "Confirmed"
    if approval_state == "approved_window":
        return "Approved window (not yet confirmed)"
    return approval_state or "Unknown"


def _values(context: dict[str, Any], *, escape: bool) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in context.items():
        s = "" if v is None else str(v)
        out[k] = html.escape(s, quote=True) if escape else s
    return out


def render_template(template: str, context: dict[str, Any], *, html_escape: bool = False) -> str:
    """Render ``{{key}}`` and legacy ``{key}`` placeholders.

    Missing keys become empty strings. When ``html_escape`` is True, substituted
    values are HTML-escaped (template markup itself is trusted admin content).
    """
    vals = _values(context, escape=html_escape)

    def _dbl(match: re.Match[str]) -> str:
        return vals.get(match.group(1), "")

    def _sgl(match: re.Match[str]) -> str:
        return vals.get(match.group(1), "")

    text = _DOUBLE_RE.sub(_dbl, template)
    text = _SINGLE_RE.sub(_sgl, text)
    return text


def sample_context() -> dict[str, Any]:
    return {p["key"]: p["sample"] for p in PLACEHOLDERS}


def sanitize_html_fragment(fragment: str) -> str:
    """Strip script/style/on* attributes from admin HTML templates (defense in depth)."""
    # Remove script/style blocks
    cleaned = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", fragment)
    # Remove on* event handlers
    cleaned = re.sub(r'(?i)\s+on[a-z]+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', "", cleaned)
    # Remove javascript: URLs
    cleaned = re.sub(r'(?i)\s(href|src)\s*=\s*([\'"])\s*javascript:[^\'"]*\2', r' \1="#"', cleaned)
    return cleaned
