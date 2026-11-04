"""Maintenance event lifecycle state machine."""

from __future__ import annotations

from maintenancehub_api.models import EventStatus

# Legal transitions (from → allowed next statuses)
ALLOWED_TRANSITIONS: dict[EventStatus, set[EventStatus]] = {
    EventStatus.scheduled: {
        EventStatus.in_progress,
        EventStatus.cancelled,
        EventStatus.extended,  # extend while scheduled also allowed via extend endpoint
    },
    EventStatus.in_progress: {
        EventStatus.extended,
        EventStatus.verifying,
        EventStatus.completed,
        EventStatus.cancelled,
    },
    EventStatus.extended: {
        EventStatus.in_progress,
        EventStatus.verifying,
        EventStatus.completed,
        EventStatus.cancelled,
        EventStatus.extended,
    },
    EventStatus.verifying: {
        EventStatus.completed,
        EventStatus.in_progress,
        EventStatus.cancelled,
    },
    EventStatus.completed: set(),
    EventStatus.cancelled: set(),
}


class IllegalTransitionError(ValueError):
    pass


def assert_transition(current: EventStatus, target: EventStatus) -> None:
    if current == target and current is EventStatus.extended:
        return
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise IllegalTransitionError(
            f"Cannot transition from {current.value} to {target.value}"
        )


def can_extend(current: EventStatus) -> bool:
    return current in {
        EventStatus.scheduled,
        EventStatus.in_progress,
        EventStatus.extended,
    }


def can_reschedule(current: EventStatus) -> bool:
    return current in {EventStatus.scheduled, EventStatus.extended}


def can_cancel(current: EventStatus) -> bool:
    return current not in {EventStatus.completed, EventStatus.cancelled}
