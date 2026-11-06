import pytest

from maintenancehub_api.domain.lifecycle import (
    ALLOWED_TRANSITIONS,
    IllegalTransitionError,
    assert_transition,
    can_cancel,
    can_extend,
)
from maintenancehub_api.models import EventStatus


def test_scheduled_can_start_or_cancel():
    assert EventStatus.in_progress in ALLOWED_TRANSITIONS[EventStatus.scheduled]
    assert EventStatus.cancelled in ALLOWED_TRANSITIONS[EventStatus.scheduled]


def test_illegal_transition_from_completed():
    with pytest.raises(IllegalTransitionError):
        assert_transition(EventStatus.completed, EventStatus.in_progress)


def test_illegal_jump_scheduled_to_completed():
    with pytest.raises(IllegalTransitionError):
        assert_transition(EventStatus.scheduled, EventStatus.completed)


def test_extend_allowed_states():
    assert can_extend(EventStatus.scheduled)
    assert can_extend(EventStatus.in_progress)
    assert can_extend(EventStatus.extended)
    assert not can_extend(EventStatus.completed)
    assert not can_extend(EventStatus.cancelled)


def test_cancel_terminal():
    assert can_cancel(EventStatus.in_progress)
    assert not can_cancel(EventStatus.completed)
    assert not can_cancel(EventStatus.cancelled)


def test_verifying_to_completed():
    assert_transition(EventStatus.verifying, EventStatus.completed)
