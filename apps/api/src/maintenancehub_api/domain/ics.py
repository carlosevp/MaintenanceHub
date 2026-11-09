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


def events_for_user(
    db: Session,
    user_id: str,
    *,
    scopes: list[str] | None = None,
    include_cancelled: bool = True,
) -> list[MaintenanceEvent]:
    """Events visible for calendar export / ICS for a user.

    Includes favorites and subscription targets. ``app_environment`` targets match
    exact (application, environment) pairs on the same impact row. Cancelled events
    are included by default so static downloads retain STATUS:CANCELLED.
    """
    scope_set = set(scopes or ["favorites", "subscriptions"])
    app_ids: set[str] = set()
    event_ids: set[str] = set()
    app_env_pairs: set[tuple[str, str]] = set()
    env_ids: set[str] = set()

    if "favorites" in scope_set or "all" in scope_set:
        favs = db.query(Favorite).filter(Favorite.user_id == user_id).all()
        app_ids.update(f.application_id for f in favs)

    if "subscriptions" in scope_set or "all" in scope_set:
        subs = (
            db.query(Subscription)
            .options(joinedload(Subscription.targets))
            .filter(Subscription.user_id == user_id, Subscription.is_active.is_(True))
            .all()
        )
        for sub in subs:
            for t in sub.targets:
                if t.target_type == "application":
                    app_ids.add(t.target_id)
                elif t.target_type == "event":
                    event_ids.add(t.target_id)
                elif t.target_type == "environment":
                    env_ids.add(t.target_id)
                elif t.target_type == "app_environment" and ":" in t.target_id:
                    a, e = t.target_id.split(":", 1)
                    app_env_pairs.add((a, e))

    if not app_ids and not event_ids and not app_env_pairs and not env_ids:
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

    if env_ids:
        env_event_ids = (
            db.query(EventImpact.event_id)
            .filter(EventImpact.environment_id.in_(env_ids))
            .all()
        )
        matched_ids.update(r[0] for r in env_event_ids)

    if app_env_pairs:
        # Load candidate impacts for the apps in pairs, then filter exact pairs.
        pair_apps = {a for a, _ in app_env_pairs}
        rows = (
            db.query(EventImpact.event_id, EventImpact.target_id, EventImpact.environment_id)
            .filter(
                EventImpact.target_type == ImpactTargetType.application,
                EventImpact.target_id.in_(pair_apps),
            )
            .all()
        )
        for event_id, target_id, environment_id in rows:
            if environment_id and (target_id, environment_id) in app_env_pairs:
                matched_ids.add(event_id)

    if not matched_ids:
        return []

    q = (
        db.query(MaintenanceEvent)
        .options(
            joinedload(MaintenanceEvent.recurrence_rule).joinedload(RecurrenceRule.exceptions)
        )
        .filter(MaintenanceEvent.id.in_(matched_ids))
    )
    if not include_cancelled:
        q = q.filter(MaintenanceEvent.status != EventStatus.cancelled)
    return q.order_by(MaintenanceEvent.starts_at.asc()).limit(500).all()


def events_for_token(db: Session, token: CalendarToken) -> list[MaintenanceEvent]:
    return events_for_user(
        db,
        token.user_id,
        scopes=list(token.scopes or []),
        include_cancelled=False,
    )


def events_for_application(
    db: Session,
    application_id: str,
    *,
    include_cancelled: bool = True,
) -> list[MaintenanceEvent]:
    """Events impacting a single application (any environment)."""
    impact_event_ids = (
        db.query(EventImpact.event_id)
        .filter(
            EventImpact.target_type == ImpactTargetType.application,
            EventImpact.target_id == application_id,
        )
        .all()
    )
    matched_ids = {r[0] for r in impact_event_ids}
    if not matched_ids:
        return []
    q = (
        db.query(MaintenanceEvent)
        .options(
            joinedload(MaintenanceEvent.recurrence_rule).joinedload(RecurrenceRule.exceptions)
        )
        .filter(MaintenanceEvent.id.in_(matched_ids))
    )
    if not include_cancelled:
        q = q.filter(MaintenanceEvent.status != EventStatus.cancelled)
    return q.order_by(MaintenanceEvent.starts_at.asc()).limit(500).all()


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
        is_approved_window = event.approval_state.value == "approved_window"
        is_cancelled = event.status == EventStatus.cancelled
        # Confirmed maintenance → CONFIRMED; approved (unconfirmed) windows → TENTATIVE.
        if is_cancelled:
            status = "CANCELLED"
        elif is_approved_window:
            status = "TENTATIVE"
        else:
            status = "CONFIRMED"
        title = event.title
        if is_approved_window and not is_cancelled:
            title = f"[Approved window] {event.title}"
        elif status == "CONFIRMED":
            # Keep titles readable; approval called out in DESCRIPTION.
            pass
        desc_parts = [
            event.description or "",
            f"Status: {event.status.value}",
            (
                "Approval: approved_window (tentative — not yet confirmed maintenance)"
                if is_approved_window
                else "Approval: confirmed_scheduled (confirmed maintenance)"
            ),
            f"Kind: {event.kind.value}",
        ]
        if event.expected_impact:
            desc_parts.append(f"Impact: {event.expected_impact}")
        description = _escape("\n".join(p for p in desc_parts if p))

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now}",
                f"DTSTART:{_fmt_dt(event.starts_at)}",
                f"DTEND:{_fmt_dt(event.ends_at)}",
                f"SUMMARY:{_escape(title)}",
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
                        f"SUMMARY:{_escape(title)}",
                        f"DESCRIPTION:{description}",
                        f"STATUS:{status}",
                        "END:VEVENT",
                    ]
                )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
