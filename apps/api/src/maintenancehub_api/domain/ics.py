"""Personalized ICS feed generation (ADR-006). Outlook-oriented VCALENDAR."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.models import (
    CalendarToken,
    EventImpact,
    EventStatus,
    Favorite,
    ImpactTargetType,
    MaintenanceEvent,
    RecurrenceRule,
    Subscription,
)
from maintenancehub_api.schemas.common import ensure_utc


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_calendar_token(
    db: Session,
    *,
    user_id: str,
    scopes: list[str] | None = None,
    label: str | None = None,
    expires_at: datetime | None = None,
) -> tuple[CalendarToken, str]:
    """Returns (row, raw_secret_once)."""
    raw = secrets.token_urlsafe(32)
    row = CalendarToken(
        user_id=user_id,
        token_hash=hash_token(raw),
        scopes=scopes or ["favorites", "subscriptions"],
        label=label,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, raw


def resolve_token(db: Session, raw: str) -> CalendarToken | None:
    row = (
        db.query(CalendarToken)
        .filter(CalendarToken.token_hash == hash_token(raw))
        .first()
    )
    if not row:
        return None
    if row.revoked_at is not None:
        return None
    if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc):
        return None
    return row


def revoke_token(db: Session, token_id: str, user_id: str) -> bool:
    row = (
        db.query(CalendarToken)
        .filter(CalendarToken.id == token_id, CalendarToken.user_id == user_id)
        .first()
    )
    if not row:
        return False
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return True


def events_for_token(db: Session, token: CalendarToken) -> list[MaintenanceEvent]:
    scopes = set(token.scopes or [])
    app_ids: set[str] = set()
    event_ids: set[str] = set()

    if "favorites" in scopes or "all" in scopes:
        favs = db.query(Favorite).filter(Favorite.user_id == token.user_id).all()
        app_ids.update(f.application_id for f in favs)

    if "subscriptions" in scopes or "all" in scopes:
        subs = (
            db.query(Subscription)
            .options(joinedload(Subscription.targets))
            .filter(Subscription.user_id == token.user_id, Subscription.is_active.is_(True))
            .all()
        )
        for sub in subs:
            for t in sub.targets:
                if t.target_type == "application":
                    app_ids.add(t.target_id)
                elif t.target_type == "event":
                    event_ids.add(t.target_id)

    if not app_ids and not event_ids:
        return []

    matched_ids: set[str] = set(event_ids)
    if app_ids:
        impact_event_ids = (
            db.query(EventImpact.event_id)
            .filter(
                EventImpact.target_type == ImpactTargetType.application,
                EventImpact.target_id.in_(app_ids),
            )
            .all()
        )
        matched_ids.update(r[0] for r in impact_event_ids)

    return (
        db.query(MaintenanceEvent)
        .options(
            joinedload(MaintenanceEvent.recurrence_rule).joinedload(RecurrenceRule.exceptions)
        )
        .filter(
            MaintenanceEvent.id.in_(matched_ids),
            MaintenanceEvent.status != EventStatus.cancelled,
        )
        .order_by(MaintenanceEvent.starts_at.asc())
        .limit(500)
        .all()
    )


def _fmt_dt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def series_uid(event_id: str) -> str:
    """Stable ICS UID for a series/master (shared by overrides via RECURRENCE-ID)."""
    return f"{event_id}@maintenancehub"


def build_ics(
    events: Iterable[MaintenanceEvent],
    *,
    calendar_name: str = "MaintenanceHub",
) -> str:
    """Build Outlook-compatible VCALENDAR.

    Recurring masters emit RRULE + EXDATE for cancels. Rescheduled occurrences emit a
    separate VEVENT with the same UID and RECURRENCE-ID = original occurrence start
    (stable logical identity).
    """
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//MaintenanceHub//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(calendar_name)}",
    ]
    now = _fmt_dt(datetime.now(timezone.utc))
    for event in events:
        uid = series_uid(event.id)
        desc_parts = [
            event.description or "",
            f"Status: {event.status.value}",
            f"Approval: {event.approval_state.value}",
            f"Kind: {event.kind.value}",
        ]
        if event.expected_impact:
            desc_parts.append(f"Impact: {event.expected_impact}")
        description = _escape("\n".join(p for p in desc_parts if p))
        status = "CANCELLED" if event.status == EventStatus.cancelled else "CONFIRMED"
        # Approved windows are still published as tentative in ICS when not confirmed
        if event.approval_state.value == "approved_window" and status == "CONFIRMED":
            status = "TENTATIVE"

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now}",
                f"DTSTART:{_fmt_dt(event.starts_at)}",
                f"DTEND:{_fmt_dt(event.ends_at)}",
                f"SUMMARY:{_escape(event.title)}",
                f"DESCRIPTION:{description}",
                f"STATUS:{status}",
            ]
        )
        if event.timezone and event.timezone != "UTC":
            lines.append(f"X-WR-TIMEZONE:{event.timezone}")
        if event.is_recurring and getattr(event, "recurrence_rule", None):
            lines.append(f"RRULE:{event.recurrence_rule.rrule}")
            for ex in event.recurrence_rule.exceptions or []:
                if ex.action == "cancel":
                    lines.append(f"EXDATE:{_fmt_dt(ex.original_starts_at)}")
        lines.append("END:VEVENT")

        # Reschedule overrides — same UID, RECURRENCE-ID = original start
        if event.is_recurring and getattr(event, "recurrence_rule", None):
            for ex in event.recurrence_rule.exceptions or []:
                if ex.action != "reschedule" or not ex.new_starts_at or not ex.new_ends_at:
                    continue
                lines.extend(
                    [
                        "BEGIN:VEVENT",
                        f"UID:{uid}",
                        f"DTSTAMP:{now}",
                        f"RECURRENCE-ID:{_fmt_dt(ensure_utc(ex.original_starts_at))}",
                        f"DTSTART:{_fmt_dt(ensure_utc(ex.new_starts_at))}",
                        f"DTEND:{_fmt_dt(ensure_utc(ex.new_ends_at))}",
                        f"SUMMARY:{_escape(event.title)}",
                        f"DESCRIPTION:{description}",
                        f"STATUS:{status}",
                        "END:VEVENT",
                    ]
                )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
