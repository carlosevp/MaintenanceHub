"""Human-published communication phases — not monitoring-derived status."""

from __future__ import annotations

from datetime import datetime

from maintenancehub_api.models import ApprovalState, EventKind, EventStatus, MaintenanceEvent
from maintenancehub_api.schemas.common import ensure_utc

# Phases exposed on dashboard/calendar DTOs
PHASE_APPROVED_WINDOW = "approved_window"
PHASE_SCHEDULED = "scheduled"
PHASE_EXECUTING = "executing"
PHASE_COMPLETED = "completed"
PHASE_CANCELLED = "cancelled"


def communication_phase(
    event: MaintenanceEvent,
    *,
    now: datetime,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> str:
    """Classify human-published state for an event or occurrence window.

    - approved_window: change window approved but not confirmed for communication
    - scheduled: confirmed, not yet / not marked executing
    - executing: human transitioned to in_progress|extended|verifying
    - completed / cancelled: terminal
    """
    status = event.status
    if status == EventStatus.cancelled:
        return PHASE_CANCELLED
    if status == EventStatus.completed:
        return PHASE_COMPLETED
    if event.approval_state == ApprovalState.approved_window:
        return PHASE_APPROVED_WINDOW
    if status in {EventStatus.in_progress, EventStatus.extended, EventStatus.verifying}:
        return PHASE_EXECUTING
    return PHASE_SCHEDULED


def is_active_outage(event: MaintenanceEvent, *, now: datetime, starts_at: datetime, ends_at: datetime) -> bool:
    """Manual outage that is confirmed and currently executing in its window."""
    if event.kind != EventKind.manual_outage:
        return False
    if event.approval_state != ApprovalState.confirmed_scheduled:
        return False
    if event.status not in {
        EventStatus.in_progress,
        EventStatus.extended,
        EventStatus.verifying,
    }:
        return False
    now = ensure_utc(now)
    return ensure_utc(starts_at) <= now <= ensure_utc(ends_at)


def is_executing_now(event: MaintenanceEvent, *, now: datetime, starts_at: datetime, ends_at: datetime) -> bool:
    """Confirmed work human-marked as executing and overlapping now."""
    if communication_phase(event, now=now) != PHASE_EXECUTING:
        return False
    now = ensure_utc(now)
    return ensure_utc(starts_at) <= now <= ensure_utc(ends_at)


def is_upcoming_scheduled(
    event: MaintenanceEvent, *, now: datetime, starts_at: datetime
) -> bool:
    """Future confirmed scheduled activity (not approved-only, not terminal)."""
    phase = communication_phase(event, now=now)
    if phase not in {PHASE_SCHEDULED, PHASE_EXECUTING}:
        # approved_window future still useful on calendar; dashboard upcoming includes it
        # as non-executing communication — include approved upcoming separately
        if phase == PHASE_APPROVED_WINDOW and ensure_utc(starts_at) > ensure_utc(now):
            return True
        return False
    if event.status in {EventStatus.completed, EventStatus.cancelled}:
        return False
    return ensure_utc(starts_at) > ensure_utc(now)
