"""Map ServiceNow change records → maintenance events (idempotent by sys_id)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from maintenancehub_api.adapters.servicenow import (
    SOURCE_SYSTEM,
    ChangeRecord,
    get_change_adapter,
)
from maintenancehub_api.config import get_settings
from maintenancehub_api.models import (
    ApprovalState,
    EventKind,
    EventStatus,
    EventTimelineEntry,
    MaintenanceEvent,
    OutboxEvent,
    SnChangeSnapshot,
    SnUnmatchedRecord,
    TimelineEntryType,
)

logger = logging.getLogger("maintenancehub.sn_sync")

# SN state strings treated as cancelled
CANCEL_STATES = {"3", "4", "cancelled", "canceled", "-3", "closed_cancelled"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # SN often sends "2026-11-10 02:00:00"
        v = value.replace("Z", "+00:00")
        if " " in v and "T" not in v:
            v = v.replace(" ", "T", 1)
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _is_cancelled(state: str) -> bool:
    return state.strip().lower() in CANCEL_STATES or state.strip() in CANCEL_STATES


def run_poll(db: Session, *, fixture_records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    adapter = get_change_adapter(fixture_records=fixture_records)
    records = adapter.poll()
    stats = {"fetched": len(records), "created": 0, "updated": 0, "unchanged": 0, "unmatched": 0, "cancelled": 0}
    for rec in records:
        if not rec.external_id:
            continue
        result = upsert_change(db, rec)
        stats[result] = stats.get(result, 0) + 1
    db.commit()
    return stats


def upsert_change(db: Session, rec: ChangeRecord) -> str:
    """Returns created|updated|unchanged|unmatched|cancelled."""
    settings = get_settings()
    digest = rec.content_hash()
    snap = (
        db.query(SnChangeSnapshot)
        .filter(
            SnChangeSnapshot.source_system == SOURCE_SYSTEM,
            SnChangeSnapshot.external_id == rec.external_id,
        )
        .first()
    )

    event = (
        db.query(MaintenanceEvent)
        .filter(
            MaintenanceEvent.source_system == SOURCE_SYSTEM,
            MaintenanceEvent.external_id == rec.external_id,
        )
        .first()
    )

    if snap and snap.content_hash == digest and event and not _is_cancelled(rec.state):
        snap.last_seen_at = _now()
        return "unchanged"

    starts = _parse_dt(rec.start) or (_now() + timedelta(days=1))
    ends = _parse_dt(rec.end) or (starts + timedelta(hours=2))
    if ends <= starts:
        ends = starts + timedelta(hours=1)

    title = f"[SN {rec.number}] {rec.short_description}".strip()
    if len(title) > 300:
        title = title[:297] + "..."

    if _is_cancelled(rec.state):
        if event:
            if event.status != EventStatus.cancelled:
                prev = event.status
                event.status = EventStatus.cancelled
                event.updated_at = _now()
                db.add(
                    EventTimelineEntry(
                        event_id=event.id,
                        at=_now(),
                        actor_id=None,
                        entry_type=TimelineEntryType.system,
                        payload={"from": prev.value, "to": "cancelled", "source": SOURCE_SYSTEM},
                    )
                )
                db.add(
                    OutboxEvent(
                        aggregate_type="maintenance_event",
                        aggregate_id=event.id,
                        event_type="event.transitioned",
                        payload={"event_id": event.id, "from": prev.value, "to": "cancelled"},
                    )
                )
            _upsert_snapshot(db, snap, rec, digest, event.id)
            return "cancelled"
        if settings.servicenow_cancel_policy == "unmatched":
            _queue_unmatched(db, rec, reason="cancelled_without_mapped_event")
            _upsert_snapshot(db, snap, rec, digest, None)
            return "unmatched"
        # No event to cancel — queue for review
        _queue_unmatched(db, rec, reason="cancelled_orphan")
        _upsert_snapshot(db, snap, rec, digest, None)
        return "unmatched"

    # Require mappable window; otherwise unmatched
    if not rec.short_description and not rec.number:
        _queue_unmatched(db, rec, reason="missing_title")
        _upsert_snapshot(db, snap, rec, digest, None)
        return "unmatched"

    if event is None:
        # Create as approved_window pending confirmation (ADR-005)
        event = MaintenanceEvent(
            kind=EventKind.planned_maintenance,
            title=title,
            description=rec.description or None,
            expected_impact="Imported from ServiceNow change",
            status=EventStatus.scheduled,
            approval_state=ApprovalState.approved_window,
            starts_at=starts,
            ends_at=ends,
            timezone="UTC",
            is_recurring=False,
            source_system=SOURCE_SYSTEM,
            external_id=rec.external_id,
            created_by="servicenow",
            updated_by="servicenow",
        )
        db.add(event)
        db.flush()
        db.add(
            EventTimelineEntry(
                event_id=event.id,
                at=_now(),
                actor_id=None,
                entry_type=TimelineEntryType.system,
                payload={"action": "created", "source": SOURCE_SYSTEM, "number": rec.number},
            )
        )
        db.add(
            OutboxEvent(
                aggregate_type="maintenance_event",
                aggregate_id=event.id,
                event_type="event.created",
                payload={"event_id": event.id, "event_type": "event.created", "source": SOURCE_SYSTEM},
            )
        )
        _upsert_snapshot(db, snap, rec, digest, event.id)
        # Close any open unmatched for this external id
        for u in (
            db.query(SnUnmatchedRecord)
            .filter(
                SnUnmatchedRecord.external_id == rec.external_id,
                SnUnmatchedRecord.status == "open",
            )
            .all()
        ):
            u.status = "created"
            u.resolved_event_id = event.id
            u.resolved_at = _now()
        return "created"

    # Update existing
    changed = False
    if event.title != title:
        event.title = title
        changed = True
    if rec.description and event.description != rec.description:
        event.description = rec.description
        changed = True
    if event.starts_at != starts or event.ends_at != ends:
        payload = {
            "previous_starts_at": event.starts_at.isoformat(),
            "previous_ends_at": event.ends_at.isoformat(),
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "source": SOURCE_SYSTEM,
        }
        event.starts_at = starts
        event.ends_at = ends
        if event.status not in {EventStatus.completed, EventStatus.cancelled}:
            event.status = EventStatus.scheduled
        db.add(
            EventTimelineEntry(
                event_id=event.id,
                at=_now(),
                actor_id=None,
                entry_type=TimelineEntryType.reschedule,
                payload=payload,
            )
        )
        db.add(
            OutboxEvent(
                aggregate_type="maintenance_event",
                aggregate_id=event.id,
                event_type="event.rescheduled",
                payload={"event_id": event.id, **payload},
            )
        )
        changed = True
    event.updated_by = "servicenow"
    _upsert_snapshot(db, snap, rec, digest, event.id)
    return "updated" if changed else "unchanged"


def _upsert_snapshot(
    db: Session,
    snap: SnChangeSnapshot | None,
    rec: ChangeRecord,
    digest: str,
    event_id: str | None,
) -> None:
    if snap is None:
        snap = SnChangeSnapshot(
            source_system=SOURCE_SYSTEM,
            external_id=rec.external_id,
            content_hash=digest,
            sys_updated_on=rec.sys_updated_on,
            raw_payload=rec.raw,
            maintenance_event_id=event_id,
            last_seen_at=_now(),
        )
        db.add(snap)
    else:
        snap.content_hash = digest
        snap.sys_updated_on = rec.sys_updated_on
        snap.raw_payload = rec.raw
        snap.maintenance_event_id = event_id
        snap.last_seen_at = _now()


def _queue_unmatched(db: Session, rec: ChangeRecord, *, reason: str) -> None:
    existing = (
        db.query(SnUnmatchedRecord)
        .filter(
            SnUnmatchedRecord.external_id == rec.external_id,
            SnUnmatchedRecord.status == "open",
        )
        .first()
    )
    if existing:
        existing.raw_payload = rec.raw
        existing.reason = reason
        return
    db.add(
        SnUnmatchedRecord(
            source_system=SOURCE_SYSTEM,
            external_id=rec.external_id,
            reason=reason,
            raw_payload=rec.raw,
            status="open",
        )
    )


def resolve_unmatched(
    db: Session,
    unmatched_id: str,
    *,
    action: str,
    event_id: str | None = None,
    actor_id: str | None = None,
) -> SnUnmatchedRecord:
    row = db.get(SnUnmatchedRecord, unmatched_id)
    if not row or row.status != "open":
        raise ValueError("Unmatched record not found or already resolved")

    if action == "ignore":
        row.status = "ignored"
        row.resolved_at = _now()
    elif action == "link":
        if not event_id:
            raise ValueError("event_id required for link")
        event = db.get(MaintenanceEvent, event_id)
        if not event:
            raise ValueError("Event not found")
        event.source_system = SOURCE_SYSTEM
        event.external_id = row.external_id
        row.status = "linked"
        row.resolved_event_id = event.id
        row.resolved_at = _now()
        snap = (
            db.query(SnChangeSnapshot)
            .filter(SnChangeSnapshot.external_id == row.external_id)
            .first()
        )
        if snap:
            snap.maintenance_event_id = event.id
    elif action == "create":
        rec = ChangeRecord(
            external_id=row.external_id,
            number=str((row.raw_payload or {}).get("number") or ""),
            short_description=str(
                (row.raw_payload or {}).get("short_description")
                or (row.raw_payload or {}).get("title")
                or "ServiceNow change"
            ),
            description=str((row.raw_payload or {}).get("description") or ""),
            state=str((row.raw_payload or {}).get("state") or "1"),
            start=(row.raw_payload or {}).get("start_date")
            or (row.raw_payload or {}).get("planned_start_date"),
            end=(row.raw_payload or {}).get("end_date")
            or (row.raw_payload or {}).get("planned_end_date"),
            sys_updated_on=(row.raw_payload or {}).get("sys_updated_on"),
            raw=row.raw_payload or {},
        )
        upsert_change(db, rec)
        event = (
            db.query(MaintenanceEvent)
            .filter(
                MaintenanceEvent.source_system == SOURCE_SYSTEM,
                MaintenanceEvent.external_id == row.external_id,
            )
            .first()
        )
        row.status = "created"
        row.resolved_event_id = event.id if event else None
        row.resolved_at = _now()
    else:
        raise ValueError(f"Unknown action {action}")

    db.commit()
    db.refresh(row)
    return row
