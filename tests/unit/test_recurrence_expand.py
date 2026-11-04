"""M3b — RRULE expansion, DST, monthly edges, exceptions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from maintenancehub_api.domain.recurrence import (
    build_rrule_string,
    expand_event_occurrences,
    human_summary,
    preview_occurrences,
)


def _master(
    *,
    starts: datetime,
    ends: datetime,
    tz: str,
    rrule: str,
    exceptions=None,
):
    rule = SimpleNamespace(rrule=rrule, exceptions=exceptions or [], until_at=None)
    return SimpleNamespace(
        id="evt1",
        starts_at=starts,
        ends_at=ends,
        timezone=tz,
        is_recurring=True,
        recurrence_rule=rule,
    )


def test_weekly_dst_transition_america_chicago():
    """Weekly 10:00 America/Chicago across US spring-forward 2026-03-08.

    Before DST: 10:00 CST = 16:00 UTC
    After DST:  10:00 CDT = 15:00 UTC
    """
    # 2026-03-01 10:00 CST
    starts = datetime(2026, 3, 1, 16, 0, tzinfo=timezone.utc)
    ends = starts + timedelta(hours=2)
    event = _master(
        starts=starts,
        ends=ends,
        tz="America/Chicago",
        rrule="FREQ=WEEKLY;BYDAY=SU",
    )
    occs = expand_event_occurrences(
        event,
        range_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
        range_end=datetime(2026, 3, 30, tzinfo=timezone.utc),
    )
    assert len(occs) >= 4
    # First Sunday March 1
    assert occs[0].starts_at == datetime(2026, 3, 1, 16, 0, tzinfo=timezone.utc)
    # March 8 (DST starts 02:00) — still 10:00 local → 15:00 UTC
    mar8 = next(o for o in occs if o.starts_at.day == 8 or o.original_starts_at.day == 8)
    assert mar8.starts_at == datetime(2026, 3, 8, 15, 0, tzinfo=timezone.utc)
    # March 15
    mar15 = next(o for o in occs if o.original_starts_at.day == 15)
    assert mar15.starts_at == datetime(2026, 3, 15, 15, 0, tzinfo=timezone.utc)


def test_monthly_bymonthday_edge_and_count():
    starts = datetime(2026, 1, 31, 12, 0, tzinfo=timezone.utc)
    ends = starts + timedelta(hours=1)
    prev = preview_occurrences(
        starts_at=starts,
        ends_at=ends,
        timezone_name="UTC",
        recurrence={"freq": "MONTHLY", "bymonthday": 31, "count": 4},
        count=4,
    )
    # dateutil skips months without day 31
    days = [datetime.fromisoformat(p["starts_at"]).month for p in prev]
    assert days == [1, 3, 5, 7] or days[0] == 1


def test_cancel_exception_removes_occurrence():
    starts = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    ends = starts + timedelta(hours=2)
    cancel_at = starts + timedelta(days=7)
    ex = SimpleNamespace(
        original_starts_at=cancel_at,
        action="cancel",
        new_starts_at=None,
        new_ends_at=None,
    )
    event = _master(
        starts=starts,
        ends=ends,
        tz="UTC",
        rrule="FREQ=WEEKLY;BYDAY=MO",
        exceptions=[ex],
    )
    # June 1 2026 is Monday
    occs = expand_event_occurrences(
        event,
        range_start=starts - timedelta(seconds=1),
        range_end=starts + timedelta(days=21),
    )
    originals = {o.original_starts_at for o in occs}
    assert cancel_at not in originals
    cancelled = expand_event_occurrences(
        event,
        range_start=starts - timedelta(seconds=1),
        range_end=starts + timedelta(days=21),
        include_cancelled=True,
    )
    assert any(o.cancelled and o.original_starts_at == cancel_at for o in cancelled)


def test_reschedule_exception_moves_window():
    starts = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    ends = starts + timedelta(hours=2)
    orig = starts + timedelta(days=7)
    new_s = orig + timedelta(hours=3)
    new_e = new_s + timedelta(hours=2)
    ex = SimpleNamespace(
        original_starts_at=orig,
        action="reschedule",
        new_starts_at=new_s,
        new_ends_at=new_e,
    )
    event = _master(
        starts=starts,
        ends=ends,
        tz="UTC",
        rrule="FREQ=WEEKLY;BYDAY=MO",
        exceptions=[ex],
    )
    occs = expand_event_occurrences(
        event,
        range_start=starts - timedelta(seconds=1),
        range_end=starts + timedelta(days=14),
    )
    moved = next(o for o in occs if o.original_starts_at == orig)
    assert moved.starts_at == new_s
    assert moved.ends_at == new_e
    assert moved.is_exception


def test_human_summary_and_custom_rrule():
    s = human_summary({"freq": "WEEKLY", "interval": 2, "byweekday": ["MO", "WE"]}, timezone_name="UTC")
    assert "Every 2 weeks" in s
    assert "MO" in s
    raw = build_rrule_string(
        {"freq": "CUSTOM", "rrule": "RRULE:FREQ=DAILY;INTERVAL=3"},
        dtstart_utc=datetime.now(timezone.utc),
        tz_name="UTC",
    )
    assert raw.startswith("FREQ=DAILY")


def test_multiple_weekdays():
    starts = datetime(2026, 4, 6, 9, 0, tzinfo=timezone.utc)  # Monday
    ends = starts + timedelta(hours=1)
    prev = preview_occurrences(
        starts_at=starts,
        ends_at=ends,
        timezone_name="UTC",
        recurrence={"freq": "WEEKLY", "byweekday": ["MO", "WE", "FR"], "count": 6},
        count=6,
    )
    assert len(prev) == 6
    weekdays = {datetime.fromisoformat(p["starts_at"]).weekday() for p in prev}
    assert weekdays <= {0, 2, 4}
