"""Unit tests for banner impact matching and presentation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from maintenancehub_api.domain.banner import (
    PRES_OUTAGE,
    PRES_UPCOMING,
    impact_matches_app_env,
    presentation_for,
)
from maintenancehub_api.domain.impacts import ImpactRef
from maintenancehub_api.models import ApprovalState, EventKind, EventStatus


def test_impact_matches_exact_app_env():
    impacts = [
        ImpactRef("application", "app-a", "env-1"),
        ImpactRef("application", "app-b", "env-2"),
    ]
    assert impact_matches_app_env(impacts, application_id="app-a", environment_id="env-1")
    assert not impact_matches_app_env(impacts, application_id="app-a", environment_id="env-2")
    assert not impact_matches_app_env(impacts, application_id="app-c", environment_id="env-1")
    assert impact_matches_app_env(impacts, application_id="app-a", environment_id=None)


def test_presentation_never_outage_when_not_confirmed():
    now = datetime.now(timezone.utc)
    event = SimpleNamespace(
        approval_state=ApprovalState.approved_window,
        kind=EventKind.manual_outage,
    )
    label = presentation_for(
        event,  # type: ignore[arg-type]
        now=now,
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(hours=1),
        status=EventStatus.in_progress,
    )
    assert label == PRES_UPCOMING


def test_presentation_outage_when_confirmed_manual_executing():
    now = datetime.now(timezone.utc)
    event = SimpleNamespace(
        approval_state=ApprovalState.confirmed_scheduled,
        kind=EventKind.manual_outage,
    )
    label = presentation_for(
        event,  # type: ignore[arg-type]
        now=now,
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(hours=1),
        status=EventStatus.in_progress,
    )
    assert label == PRES_OUTAGE
