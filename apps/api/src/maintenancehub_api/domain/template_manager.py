"""Admin notification template manager (M19) — CRUD, versions, activate/restore."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from maintenancehub_api.domain.audit import write_audit
from maintenancehub_api.domain.pa_routing import (
    PA_SUBJECT,
    apply_pa_contract,
    validate_pa_extractable,
)
from maintenancehub_api.domain.templates import (
    DEFAULT_TEMPLATES,
    PLACEHOLDERS,
    EVENT_TYPES,
    render_template,
    sample_context,
    sanitize_html_fragment,
)
from maintenancehub_api.models import NotificationTemplate, NotificationTemplateVersion

_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,98}$")


def ensure_default_templates(db: Session) -> None:
    """Create missing system templates (incl. PA Teams sample)."""
    for key, parts in DEFAULT_TEMPLATES.items():
        existing = db.query(NotificationTemplate).filter(NotificationTemplate.key == key).first()
        plain = parts["body"]
        html_body = parts.get("body_html")
        if not existing:
            db.add(
                NotificationTemplate(
                    key=key,
                    name=parts.get("name") or key,
                    description=None,
                    event_type=key,
                    status="active",
                    channel="smtp" if not key.startswith("pa.") else "bridge",
                    subject_template=parts["subject"],
                    body_template=plain,
                    body_plain_template=plain,
                    body_html_template=html_body,
                    version=1,
                    is_system=True,
                )
            )
        else:
            # Backfill M19 columns without clobbering admin edits to subject/body.
            if not existing.name:
                existing.name = parts.get("name") or key
            if not existing.event_type:
                existing.event_type = key
            if existing.body_plain_template is None:
                existing.body_plain_template = existing.body_template or plain
            if existing.body_html_template is None and html_body:
                existing.body_html_template = html_body
            existing.is_system = True
    db.commit()


def get_template_row(db: Session, key: str) -> NotificationTemplate | None:
    ensure_default_templates(db)
    return db.query(NotificationTemplate).filter(NotificationTemplate.key == key).first()


def resolve_active_template(db: Session, event_type: str) -> NotificationTemplate | None:
    """Deterministic active template for an event type / key.

    Order of preference (stable; ignores ``updated_at`` so edits don't reshuffle picks):
    1. Active row whose ``key`` equals ``event_type``
    2. Active rows with ``event_type`` match, ordered by ``key`` ASC
    """
    ensure_default_templates(db)
    exact = (
        db.query(NotificationTemplate)
        .filter(
            NotificationTemplate.key == event_type,
            NotificationTemplate.status == "active",
        )
        .first()
    )
    if exact:
        return exact
    return (
        db.query(NotificationTemplate)
        .filter(
            NotificationTemplate.event_type == event_type,
            NotificationTemplate.status == "active",
        )
        .order_by(NotificationTemplate.key.asc())
        .first()
    )


def _snapshot(row: NotificationTemplate, *, changed_by: str | None, note: str | None) -> None:
    db = Session.object_session(row)
    assert db is not None
    db.add(
        NotificationTemplateVersion(
            template_id=row.id,
            version=row.version,
            name=row.name,
            event_type=row.event_type,
            channel=row.channel,
            subject_template=row.subject_template,
            body_template=row.body_template,
            body_html_template=row.body_html_template,
            body_plain_template=row.body_plain_template,
            status=row.status,
            change_note=note,
            changed_by=changed_by,
        )
    )


def _sync_legacy_body(row: NotificationTemplate) -> None:
    plain = row.body_plain_template if row.body_plain_template is not None else row.body_template
    row.body_plain_template = plain
    row.body_template = plain or ""


def list_templates(
    db: Session,
    *,
    include_archived: bool = False,
) -> list[NotificationTemplate]:
    ensure_default_templates(db)
    q = db.query(NotificationTemplate)
    if not include_archived:
        q = q.filter(NotificationTemplate.status != "archived")
    return q.order_by(NotificationTemplate.key).all()


def create_template(
    db: Session,
    *,
    actor_id: str,
    key: str,
    name: str,
    event_type: str,
    subject_template: str,
    body_plain_template: str,
    body_html_template: str | None = None,
    channel: str = "smtp",
    description: str | None = None,
    activate: bool = True,
) -> NotificationTemplate:
    key = key.strip().lower()
    if not _KEY_RE.match(key):
        raise ValueError("Invalid template key (use lowercase letters, digits, . _ -)")
    if db.query(NotificationTemplate).filter(NotificationTemplate.key == key).first():
        raise ValueError(f"Template key already exists: {key}")
    html_body = sanitize_html_fragment(body_html_template) if body_html_template else None
    contracted = apply_pa_contract(
        key=key,
        channel=channel,
        subject_template=subject_template,
        body_plain=body_plain_template,
        body_html=html_body,
    )
    if contracted["pa_contract"]:
        check = validate_pa_extractable(
            subject_template=contracted["subject_template"],
            body_plain=contracted["body_plain_template"],
            body_html=contracted["body_html_template"],
        )
        if not check["ok"]:
            raise ValueError("; ".join(check["errors"]))
    row = NotificationTemplate(
        key=key,
        name=name.strip() or key,
        description=description,
        event_type=event_type,
        status="active" if activate else "inactive",
        channel=channel,
        subject_template=contracted["subject_template"],
        body_template=contracted["body_plain_template"],
        body_plain_template=contracted["body_plain_template"],
        body_html_template=contracted["body_html_template"],
        version=1,
        is_system=False,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(row)
    db.flush()
    _snapshot(row, changed_by=actor_id, note="created")
    write_audit(
        db,
        actor_id=actor_id,
        action="notification_template.create",
        entity_type="notification_template",
        entity_id=row.id,
        summary={"key": key, "event_type": event_type},
        commit=False,
    )
    db.commit()
    db.refresh(row)
    return row


def update_template(
    db: Session,
    row: NotificationTemplate,
    *,
    actor_id: str,
    name: str | None = None,
    description: str | None = None,
    event_type: str | None = None,
    channel: str | None = None,
    subject_template: str | None = None,
    body_plain_template: str | None = None,
    body_html_template: str | None = None,
    change_note: str | None = None,
) -> NotificationTemplate:
    if name is not None:
        row.name = name.strip() or row.name
    if description is not None:
        row.description = description
    if event_type is not None:
        row.event_type = event_type
    if channel is not None:
        row.channel = channel
    if subject_template is not None:
        row.subject_template = subject_template
    if body_plain_template is not None:
        row.body_plain_template = body_plain_template
    if body_html_template is not None:
        row.body_html_template = (
            sanitize_html_fragment(body_html_template) if body_html_template else None
        )
    # Protect PA routing contract from body/subject edits (canonical envelope).
    contracted = apply_pa_contract(
        key=row.key,
        channel=row.channel,
        subject_template=row.subject_template,
        body_plain=row.body_plain_template or row.body_template or "",
        body_html=row.body_html_template,
    )
    row.subject_template = contracted["subject_template"]
    row.body_plain_template = contracted["body_plain_template"]
    row.body_html_template = contracted["body_html_template"]
    if contracted["pa_contract"]:
        check = validate_pa_extractable(
            subject_template=row.subject_template,
            body_plain=row.body_plain_template or "",
            body_html=row.body_html_template,
        )
        if not check["ok"]:
            raise ValueError("; ".join(check["errors"]))
    _sync_legacy_body(row)
    row.version = int(row.version or 1) + 1
    row.updated_by = actor_id
    _snapshot(row, changed_by=actor_id, note=change_note or "updated")
    write_audit(
        db,
        actor_id=actor_id,
        action="notification_template.update",
        entity_type="notification_template",
        entity_id=row.id,
        summary={"key": row.key, "version": row.version, "note": change_note},
        commit=False,
    )
    db.commit()
    db.refresh(row)
    return row


def set_status(
    db: Session,
    row: NotificationTemplate,
    *,
    actor_id: str,
    status: str,
) -> NotificationTemplate:
    if status not in {"active", "inactive", "archived"}:
        raise ValueError("status must be active|inactive|archived")
    if row.is_system and status == "archived":
        raise ValueError("System templates cannot be archived; deactivate instead")
    row.status = status
    row.updated_by = actor_id
    row.version = int(row.version or 1) + 1
    _snapshot(row, changed_by=actor_id, note=f"status:{status}")
    write_audit(
        db,
        actor_id=actor_id,
        action=f"notification_template.{status}",
        entity_type="notification_template",
        entity_id=row.id,
        summary={"key": row.key, "status": status, "version": row.version},
        commit=False,
    )
    db.commit()
    db.refresh(row)
    return row


def clone_template(
    db: Session,
    source: NotificationTemplate,
    *,
    actor_id: str,
    new_key: str | None = None,
    new_name: str | None = None,
) -> NotificationTemplate:
    key = (new_key or f"{source.key}.copy").strip().lower()
    if not _KEY_RE.match(key):
        key = f"copy.{uuid.uuid4().hex[:8]}"
    base = key
    n = 1
    while db.query(NotificationTemplate).filter(NotificationTemplate.key == key).first():
        n += 1
        key = f"{base}-{n}"
    return create_template(
        db,
        actor_id=actor_id,
        key=key,
        name=new_name or f"{source.name or source.key} (copy)",
        event_type=source.event_type or source.key,
        subject_template=source.subject_template,
        body_plain_template=source.body_plain_template or source.body_template,
        body_html_template=source.body_html_template,
        channel=source.channel,
        description=source.description,
        activate=False,
    )


def restore_version(
    db: Session,
    row: NotificationTemplate,
    *,
    actor_id: str,
    version: int,
) -> NotificationTemplate:
    snap = (
        db.query(NotificationTemplateVersion)
        .filter(
            NotificationTemplateVersion.template_id == row.id,
            NotificationTemplateVersion.version == version,
        )
        .first()
    )
    if not snap:
        raise ValueError(f"Version {version} not found")
    return update_template(
        db,
        row,
        actor_id=actor_id,
        name=snap.name,
        event_type=snap.event_type,
        channel=snap.channel,
        subject_template=snap.subject_template,
        body_plain_template=snap.body_plain_template or snap.body_template,
        body_html_template=snap.body_html_template,
        change_note=f"restored from v{version}",
    )


def list_versions(db: Session, template_id: str) -> list[NotificationTemplateVersion]:
    return (
        db.query(NotificationTemplateVersion)
        .filter(NotificationTemplateVersion.template_id == template_id)
        .order_by(NotificationTemplateVersion.version.desc())
        .all()
    )


def preview_template(
    row: NotificationTemplate,
    context: dict[str, Any] | None = None,
) -> dict[str, str]:
    ctx = sample_context()
    if context:
        ctx.update(context)
    plain_src = row.body_plain_template or row.body_template or ""
    html_src = row.body_html_template or ""
    return {
        "subject": render_template(row.subject_template, ctx, html_escape=False),
        "body_plain": render_template(plain_src, ctx, html_escape=False),
        "body_html": render_template(html_src, ctx, html_escape=True) if html_src else "",
    }


def catalog() -> dict[str, Any]:
    return {
        "event_types": EVENT_TYPES,
        "placeholders": PLACEHOLDERS,
        "pa_notes": {
            "subject_default": PA_SUBJECT,
            "routing_line": f"To: {{{{teams_target_email}}}}",
            "routing_meaning": (
                "The body line To: <email> is consumed by Power Automate as the Teams "
                "routing address. SMTP To remains the configured bridge mailbox."
            ),
            "contract_protected": True,
        },
    }


def template_to_dict(row: NotificationTemplate) -> dict[str, Any]:
    return {
        "id": row.id,
        "key": row.key,
        "name": row.name or row.key,
        "description": row.description,
        "event_type": row.event_type or row.key,
        "status": row.status,
        "channel": row.channel,
        "subject_template": row.subject_template,
        "body_template": row.body_template,
        "body_plain_template": row.body_plain_template or row.body_template,
        "body_html_template": row.body_html_template,
        "version": row.version,
        "is_system": bool(row.is_system),
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
