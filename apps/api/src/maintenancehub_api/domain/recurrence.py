"""Recurrence expansion (M3b).

Occurrences are computed for a bounded query window — never unbounded DB materialization.
Uses event IANA timezone for wall-clock RRULE evaluation (DST-correct via zoneinfo).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import (
    DAILY,
    MONTHLY,
    WEEKLY,
    YEARLY,
    rrule,
    rrulestr,
)
from dateutil import rrule as rrule_mod

from maintenancehub_api.models import MaintenanceEvent, RecurrenceException, RecurrenceRule
from maintenancehub_api.schemas.common import ensure_utc

FREQ_MAP = {
    "DAILY": DAILY,
    "WEEKLY": WEEKLY,
    "MONTHLY": MONTHLY,
    "YEARLY": YEARLY,
}

WEEKDAY_MAP = {
    "MO": rrule_mod.MO,
    "TU": rrule_mod.TU,
    "WE": rrule_mod.WE,
    "TH": rrule_mod.TH,
    "FR": rrule_mod.FR,
    "SA": rrule_mod.SA,
    "SU": rrule_mod.SU,
}

# Max occurrences returned for any single expand call (safety).
MAX_OCCURRENCES = 500
# Default horizon when scheduling reminder jobs for recurring series.
REMINDER_HORIZON_DAYS = 45


@dataclass(frozen=True)
class Occurrence:
    event_id: str
    original_starts_at: datetime  # UTC, series DTSTART slot
    starts_at: datetime  # UTC effective (after exception reschedule)
    ends_at: datetime  # UTC effective
    cancelled: bool = False
    is_exception: bool = False

    @property
    def occurrence_id(self) -> str:
        """Stable logical id: series + original occurrence start (survives reschedule)."""
        return occurrence_id_for(self.event_id, self.original_starts_at)


def occurrence_id_for(event_id: str, original_starts_at: datetime) -> str:
    original_starts_at = ensure_utc(original_starts_at)
    return f"{event_id}@{original_starts_at.strftime('%Y%m%dT%H%M%SZ')}"


def parse_occurrence_id(occ_id: str) -> tuple[str, datetime] | None:
    if "@" not in occ_id:
        return None
    event_id, stamp = occ_id.split("@", 1)
    try:
        dt = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return event_id, dt


def resolve_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {name}") from exc


def duration_of(event: MaintenanceEvent) -> timedelta:
    return ensure_utc(event.ends_at) - ensure_utc(event.starts_at)


def build_rrule_string(spec: dict[str, Any], *, dtstart_utc: datetime, tz_name: str) -> str:
    """Build an RFC5545 RRULE body (without RRULE: prefix) from structured input or raw."""
    if spec.get("rrule"):
        raw = str(spec["rrule"]).strip()
        if raw.upper().startswith("RRULE:"):
            raw = raw[6:]
        return raw

    freq = str(spec.get("freq") or "WEEKLY").upper()
    if freq == "CUSTOM":
        raise ValueError("CUSTOM freq requires raw 'rrule' string")
    if freq not in FREQ_MAP:
        raise ValueError(f"Unsupported freq: {freq}")

    parts = [f"FREQ={freq}"]
    interval = int(spec.get("interval") or 1)
    if interval < 1:
        raise ValueError("interval must be >= 1")
    if interval != 1:
        parts.append(f"INTERVAL={interval}")

    byweekday = spec.get("byweekday") or spec.get("byday")
    if byweekday:
        if isinstance(byweekday, str):
            byweekday = [byweekday]
        days = []
        for d in byweekday:
            key = str(d).upper()[:2]
            if key not in WEEKDAY_MAP:
                raise ValueError(f"Invalid weekday: {d}")
            days.append(key)
        parts.append("BYDAY=" + ",".join(days))

    if spec.get("bymonthday") is not None:
        parts.append(f"BYMONTHDAY={int(spec['bymonthday'])}")

    if spec.get("count") is not None:
        parts.append(f"COUNT={int(spec['count'])}")

    until = spec.get("until") or spec.get("until_at")
    if until is not None:
        until_dt = ensure_utc(until if isinstance(until, datetime) else datetime.fromisoformat(str(until).replace("Z", "+00:00")))
        # UNTIL in UTC form
        parts.append(f"UNTIL={until_dt.strftime('%Y%m%dT%H%M%SZ')}")

    return ";".join(parts)


def human_summary(spec_or_rrule: str | dict[str, Any], *, timezone_name: str = "UTC") -> str:
    if isinstance(spec_or_rrule, dict):
        try:
            rrule_s = build_rrule_string(
                spec_or_rrule,
                dtstart_utc=datetime.now(timezone.utc),
                tz_name=timezone_name,
            )
        except ValueError as exc:
            return f"Invalid recurrence: {exc}"
    else:
        rrule_s = spec_or_rrule

    parts = dict(p.split("=", 1) for p in rrule_s.split(";") if "=" in p)
    freq = parts.get("FREQ", "WEEKLY")
    interval = int(parts.get("INTERVAL", "1"))
    byday = parts.get("BYDAY")
    bymonthday = parts.get("BYMONTHDAY")
    until = parts.get("UNTIL")
    count = parts.get("COUNT")

    unit = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "YEARLY": "year"}.get(freq, freq.lower())
    if interval == 1:
        lead = f"Every {unit}"
    else:
        lead = f"Every {interval} {unit}s"

    extras: list[str] = []
    if byday:
        extras.append("on " + ", ".join(byday.split(",")))
    if bymonthday:
        extras.append(f"on day {bymonthday}")
    if until:
        extras.append(f"until {until}")
    if count:
        extras.append(f"{count} times")
    extras.append(f"({timezone_name})")
    return lead + ((" " + " ".join(extras)) if extras else "")


def _parse_rule(event: MaintenanceEvent, rule: RecurrenceRule) -> rrule:
    tz = resolve_tz(event.timezone)
    dtstart_local = ensure_utc(event.starts_at).astimezone(tz).replace(tzinfo=None)
    body = rule.rrule.strip()
    if body.upper().startswith("RRULE:"):
        body = body[6:]
    # Feed DTSTART in floating local wall time; dateutil evaluates in naive, we re-attach TZ.
    full = f"DTSTART:{dtstart_local.strftime('%Y%m%dT%H%M%S')}\nRRULE:{body}"
    try:
        parsed = rrulestr(full, ignoretz=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid RRULE: {exc}") from exc
    return parsed  # type: ignore[return-value]


def _exception_index(exceptions: Iterable[RecurrenceException]) -> dict[datetime, RecurrenceException]:
    idx: dict[datetime, RecurrenceException] = {}
    for ex in exceptions or []:
        key = ensure_utc(ex.original_starts_at)
        idx[key] = ex
    return idx


def expand_event_occurrences(
    event: MaintenanceEvent,
    *,
    range_start: datetime,
    range_end: datetime,
    include_cancelled: bool = False,
) -> list[Occurrence]:
    """Expand master event into occurrences overlapping [range_start, range_end]."""
    range_start = ensure_utc(range_start)
    range_end = ensure_utc(range_end)
    if range_end <= range_start:
        return []

    dur = duration_of(event)
    if not event.is_recurring or not getattr(event, "recurrence_rule", None):
        # One-shot
        starts = ensure_utc(event.starts_at)
        ends = ensure_utc(event.ends_at)
        if ends < range_start or starts > range_end:
            return []
        return [
            Occurrence(
                event_id=event.id,
                original_starts_at=starts,
                starts_at=starts,
                ends_at=ends,
            )
        ]

    rule: RecurrenceRule = event.recurrence_rule
    tz = resolve_tz(event.timezone)
    parsed = _parse_rule(event, rule)

    # Expand with pad so long-duration events that started before window are included.
    pad_start = range_start - dur
    local_after = pad_start.astimezone(tz).replace(tzinfo=None)
    local_before = range_end.astimezone(tz).replace(tzinfo=None)

    try:
        starts_local = list(parsed.between(local_after, local_before, inc=True))
    except Exception:
        # Fallback: iterate with count limit from dtstart
        starts_local = list(parsed[:MAX_OCCURRENCES])

    ex_idx = _exception_index(rule.exceptions or [])
    out: list[Occurrence] = []
    for naive in starts_local:
        # Interpret as wall time in event TZ (DST-aware attach)
        local_aware = naive.replace(tzinfo=tz)
        original_utc = local_aware.astimezone(timezone.utc)
        ex = ex_idx.get(original_utc)
        # Also try matching without microseconds / alternate
        if ex is None:
            for k, v in ex_idx.items():
                if abs((k - original_utc).total_seconds()) < 1:
                    ex = v
                    break

        if ex and ex.action == "cancel":
            if include_cancelled:
                out.append(
                    Occurrence(
                        event_id=event.id,
                        original_starts_at=original_utc,
                        starts_at=original_utc,
                        ends_at=original_utc + dur,
                        cancelled=True,
                        is_exception=True,
                    )
                )
            continue

        if ex and ex.action == "reschedule" and ex.new_starts_at and ex.new_ends_at:
            starts = ensure_utc(ex.new_starts_at)
            ends = ensure_utc(ex.new_ends_at)
            is_ex = True
        else:
            starts = original_utc
            ends = original_utc + dur
            is_ex = bool(ex)

        if ends < range_start or starts > range_end:
            continue
        out.append(
            Occurrence(
                event_id=event.id,
                original_starts_at=original_utc,
                starts_at=starts,
                ends_at=ends,
                is_exception=is_ex,
            )
        )
        if len(out) >= MAX_OCCURRENCES:
            break

    out.sort(key=lambda o: o.starts_at)
    return out


def preview_occurrences(
    *,
    starts_at: datetime,
    ends_at: datetime,
    timezone_name: str,
    recurrence: dict[str, Any],
    count: int = 10,
    exceptions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Preview next N occurrences without persisting (for editor UX)."""
    starts_at = ensure_utc(starts_at)
    ends_at = ensure_utc(ends_at)
    if ends_at <= starts_at:
        raise ValueError("ends_at must be after starts_at")
    resolve_tz(timezone_name)
    from types import SimpleNamespace

    rrule_s = build_rrule_string(recurrence, dtstart_utc=starts_at, tz_name=timezone_name)

    fake_ex = []
    for ex in exceptions or []:
        fake_ex.append(
            SimpleNamespace(
                original_starts_at=ensure_utc(
                    ex["original_starts_at"]
                    if isinstance(ex["original_starts_at"], datetime)
                    else datetime.fromisoformat(str(ex["original_starts_at"]).replace("Z", "+00:00"))
                ),
                action=ex["action"],
                new_starts_at=(
                    ensure_utc(ex["new_starts_at"]) if ex.get("new_starts_at") else None
                ),
                new_ends_at=(ensure_utc(ex["new_ends_at"]) if ex.get("new_ends_at") else None),
            )
        )
    rule_obj = SimpleNamespace(rrule=rrule_s, exceptions=fake_ex)
    event_obj = SimpleNamespace(
        id="preview",
        starts_at=starts_at,
        ends_at=ends_at,
        timezone=timezone_name,
        is_recurring=True,
        recurrence_rule=rule_obj,
    )

    # Expand far enough to get `count` non-cancelled
    horizon = starts_at + timedelta(days=365 * 3)
    occs = expand_event_occurrences(
        event_obj,  # type: ignore[arg-type]
        range_start=starts_at - timedelta(seconds=1),
        range_end=horizon,
        include_cancelled=False,
    )
    return [
        {
            "original_starts_at": o.original_starts_at.isoformat(),
            "starts_at": o.starts_at.isoformat(),
            "ends_at": o.ends_at.isoformat(),
            "is_exception": o.is_exception,
        }
        for o in occs[:count]
    ]


def upsert_rule(
    db,
    event: MaintenanceEvent,
    *,
    recurrence: dict[str, Any],
) -> RecurrenceRule:
    rrule_s = build_rrule_string(
        recurrence, dtstart_utc=ensure_utc(event.starts_at), tz_name=event.timezone
    )
    until = recurrence.get("until") or recurrence.get("until_at")
    until_at = None
    if until is not None:
        until_at = ensure_utc(
            until if isinstance(until, datetime) else datetime.fromisoformat(str(until).replace("Z", "+00:00"))
        )

    rule = event.recurrence_rule
    if rule is None:
        rule = RecurrenceRule(event_id=event.id, rrule=rrule_s, until_at=until_at)
        db.add(rule)
    else:
        rule.rrule = rrule_s
        rule.until_at = until_at
    event.is_recurring = True
    db.flush()
    return rule


def add_or_replace_exception(
    db,
    event: MaintenanceEvent,
    *,
    original_starts_at: datetime,
    action: str,
    new_starts_at: datetime | None = None,
    new_ends_at: datetime | None = None,
) -> RecurrenceException:
    if not event.recurrence_rule:
        raise ValueError("Event has no recurrence rule")
    if action not in {"cancel", "reschedule"}:
        raise ValueError("action must be cancel or reschedule")
    original_starts_at = ensure_utc(original_starts_at)
    rule = event.recurrence_rule
    existing = None
    for ex in rule.exceptions or []:
        if abs((ensure_utc(ex.original_starts_at) - original_starts_at).total_seconds()) < 1:
            existing = ex
            break
    if existing:
        existing.action = action
        existing.new_starts_at = ensure_utc(new_starts_at) if new_starts_at else None
        existing.new_ends_at = ensure_utc(new_ends_at) if new_ends_at else None
        db.flush()
        return existing
    ex = RecurrenceException(
        rule_id=rule.id,
        event_id=event.id,
        original_starts_at=original_starts_at,
        action=action,
        new_starts_at=ensure_utc(new_starts_at) if new_starts_at else None,
        new_ends_at=ensure_utc(new_ends_at) if new_ends_at else None,
    )
    db.add(ex)
    db.flush()
    return ex


def truncate_series_before(
    event: MaintenanceEvent,
    *,
    from_occurrence_start: datetime,
) -> str:
    """Set UNTIL on existing RRULE to the instant before this occurrence (for this_and_future split).

    Historical exceptions (original_starts_at <= cutoff) are preserved on the old series for
    audit/ICS. Exceptions strictly after the split point remain stored but no longer expand
    because they fall after UNTIL — they are not copied onto the new series (subscriptions
    stay on the master event id that owned the impact targets at create time; the new series
    gets fresh impacts and its own reminder schedule).
    """
    if not event.recurrence_rule:
        raise ValueError("Event has no recurrence rule")
    cutoff = ensure_utc(from_occurrence_start) - timedelta(seconds=1)
    body = event.recurrence_rule.rrule
    # Remove existing UNTIL/COUNT
    parts = [p for p in body.split(";") if not p.upper().startswith("UNTIL=") and not p.upper().startswith("COUNT=")]
    parts.append(f"UNTIL={cutoff.strftime('%Y%m%dT%H%M%SZ')}")
    event.recurrence_rule.rrule = ";".join(parts)
    event.recurrence_rule.until_at = cutoff
    return event.recurrence_rule.rrule


def master_may_intersect_window(
    event: MaintenanceEvent,
    *,
    range_start: datetime,
    range_end: datetime,
) -> bool:
    """Cheap pre-filter before expand — avoids loading irrelevant history."""
    range_start = ensure_utc(range_start)
    range_end = ensure_utc(range_end)
    starts = ensure_utc(event.starts_at)
    ends = ensure_utc(event.ends_at)
    if not event.is_recurring or not getattr(event, "recurrence_rule", None):
        return ends >= range_start and starts <= range_end
    # Recurring: DTSTART before window end; if until_at set, must not end before window start
    if starts > range_end:
        return False
    until = event.recurrence_rule.until_at
    if until is not None and ensure_utc(until) < range_start:
        return False
    return True
