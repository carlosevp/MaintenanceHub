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
    status: EventStatus | None = None,
) -> str:
    """Classify human-published state for an event or occurrence window.

    - approved_window: change window approved but not confirmed for communication
    - scheduled: confirmed, not yet / not marked executing
    - executing: human transitioned to in_progress|extended|verifying
    - completed / cancelled: terminal

    Pass ``status`` to evaluate a sparse occurrence record independently of the
    series master (recurring masters typically remain ``scheduled``).
    """
    effective = status if status is not None else event.status
    if effective == EventStatus.cancelled:
        return PHASE_CANCELLED
    if effective == EventStatus.completed:
        return PHASE_COMPLETED
    if event.approval_state == ApprovalState.approved_window:
        return PHASE_APPROVED_WINDOW
    if effective in {EventStatus.in_progress, EventStatus.extended, EventStatus.verifying}:
        return PHASE_EXECUTING
    return PHASE_SCHEDULED


def is_active_outage(
    event: MaintenanceEvent,
    *,
    now: datetime,
    starts_at: datetime,
    ends_at: datetime,
    status: EventStatus | None = None,
) -> bool:
    """Manual outage that is confirmed and currently executing in its window."""
    if event.kind != EventKind.manual_outage:
        return False
    if event.approval_state != ApprovalState.confirmed_scheduled:
        return False
    effective = status if status is not None else event.status
    if effective not in {
        EventStatus.in_progress,
        EventStatus.extended,
        EventStatus.verifying,
    }:
        return False
    now = ensure_utc(now)
    return ensure_utc(starts_at) <= now <= ensure_utc(ends_at)


def is_executing_now(
    event: MaintenanceEvent,
    *,
    now: datetime,
    starts_at: datetime,
    ends_at: datetime,
    status: EventStatus | None = None,
) -> bool:
    """Confirmed work human-marked as executing and overlapping now."""
    if communication_phase(event, now=now, status=status) != PHASE_EXECUTING:
        return False
    now = ensure_utc(now)
    return ensure_utc(starts_at) <= now <= ensure_utc(ends_at)


def is_upcoming_scheduled(
    event: MaintenanceEvent,
    *,
    now: datetime,
    starts_at: datetime,
    status: EventStatus | None = None,
) -> bool:
    """Future confirmed/approved activity that is not yet executing.

    Per-occurrence status only: an ``in_progress`` sibling must never make a
    later occurrence appear as \"In progress\" on Coming up. Executing statuses
    belong in the current strip when their own window overlaps now.
    """
    effective = status if status is not None else event.status
    if effective in {
        EventStatus.completed,
        EventStatus.cancelled,
        EventStatus.in_progress,
        EventStatus.extended,
        EventStatus.verifying,
    }:
        return False
    phase = communication_phase(event, now=now, status=effective)
    if phase == PHASE_APPROVED_WINDOW:
        return ensure_utc(starts_at) > ensure_utc(now)
    if phase != PHASE_SCHEDULED:
        return False
    return ensure_utc(starts_at) > ensure_utc(now)
