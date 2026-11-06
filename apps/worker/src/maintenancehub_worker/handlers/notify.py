"""Job handlers for outbox drain, notify, and ServiceNow poll."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from maintenancehub_api.domain.notifications import (
    process_notify_dispatch,
    process_notify_reminder,
    process_outbox,
    send_delivery,
)
from maintenancehub_api.domain.servicenow_sync import run_poll


def handle_outbox_drain(db: Session, _payload: dict[str, Any]) -> dict[str, Any]:
    n = process_outbox(db)
    return {"processed": n}


def handle_notify_dispatch(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    return process_notify_dispatch(db, payload)


def handle_notify_send(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    delivery_id = payload.get("delivery_id")
    if not delivery_id:
        raise ValueError("notify_send missing delivery_id")
    row = send_delivery(db, delivery_id)
    return {"delivery_id": row.id, "status": row.status.value}


def handle_notify_reminder(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    return process_notify_reminder(db, payload)


def handle_sn_poll(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from maintenancehub_api.config import get_settings
    from maintenancehub_api.domain import experience as exp

    settings = get_settings()
    if not exp.has_capability(settings.experience_profile, "servicenow"):
        return {
            "skipped": True,
            "reason": (
                f"servicenow capability disabled for profile "
                f"{exp.normalize_profile(settings.experience_profile)}"
            ),
        }
    fixture = payload.get("fixture_records")
    return run_poll(db, fixture_records=fixture)


HANDLERS = {
    "outbox_drain": handle_outbox_drain,
    "notify_dispatch": handle_notify_dispatch,
    "notify_send": handle_notify_send,
    "notify_reminder": handle_notify_reminder,
    "sn_poll": handle_sn_poll,
}
