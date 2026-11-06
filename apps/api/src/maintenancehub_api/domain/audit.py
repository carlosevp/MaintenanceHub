"""Append-only audit log helper."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from maintenancehub_api.models import AuditLog


def write_audit(
    db: Session,
    *,
    actor_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    summary: dict[str, Any] | None = None,
    commit: bool = True,
) -> AuditLog:
    row = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary or {},
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    return row
