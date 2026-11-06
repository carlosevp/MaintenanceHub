from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from maintenancehub_api.api.experience import require_capability
from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, get_current_user, require_roles
from maintenancehub_api.domain import template_manager as tmpl_mgr
from maintenancehub_api.domain.notifications import (
    create_delivery_idempotent,
    ensure_default_templates,
    render_template_parts,
    send_delivery,
)
from maintenancehub_api.domain.templates import render_template, sample_context
from maintenancehub_api.models import NotificationDelivery, NotificationTemplate, RoleName
from maintenancehub_api.schemas.subscriptions import (
    DeliveryOut,
    TemplateCloneRequest,
    TemplateCreate,
    TemplateOut,
    TemplatePatch,
    TemplatePreviewRequest,
    TemplateRestoreRequest,
    TestSendRequest,
)

router = APIRouter(tags=["notifications"])

_ADMIN = RoleName.platform_administrator.value


def _admin(user: AuthUser = Depends(require_roles(_ADMIN))) -> AuthUser:
    require_capability("notification_admin")
    return user


def _to_out(row: NotificationTemplate) -> dict:
    d = tmpl_mgr.template_to_dict(row)
    # FastAPI response_model coerces; ensure updated_at string if datetime slipped
    return d


@router.get("/notifications/deliveries", response_model=list[DeliveryOut])
def list_deliveries(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> list[NotificationDelivery]:
    q = db.query(NotificationDelivery)
    if not user.is_admin:
        # Users see deliveries for their subscriptions only — approximate via destination email match
        q = q.filter(NotificationDelivery.destination == user.email)
    if status:
        q = q.filter(NotificationDelivery.status == status)
    return q.order_by(NotificationDelivery.created_at.desc()).limit(limit).all()


@router.get("/notification-templates/catalog")
def template_catalog(
    _: AuthUser = Depends(get_current_user),
) -> dict:
    return tmpl_mgr.catalog()


@router.get("/notification-templates", response_model=list[TemplateOut])
def list_templates(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> list[dict]:
    rows = tmpl_mgr.list_templates(db, include_archived=include_archived)
    return [_to_out(r) for r in rows]


@router.post("/notification-templates", response_model=TemplateOut, status_code=201)
def create_template(
    body: TemplateCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(_admin),
) -> dict:
    try:
        row = tmpl_mgr.create_template(
            db,
            actor_id=user.id,
            key=body.key,
            name=body.name,
            event_type=body.event_type,
            subject_template=body.subject_template,
            body_plain_template=body.body_plain_template,
            body_html_template=body.body_html_template,
            channel=body.channel,
            description=body.description,
            activate=body.activate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(row)


@router.get("/notification-templates/{key}", response_model=TemplateOut)
def get_template_api(
    key: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> dict:
    row = tmpl_mgr.get_template_row(db, key)
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    return _to_out(row)


@router.patch("/notification-templates/{key}", response_model=TemplateOut)
def patch_template(
    key: str,
    body: TemplatePatch,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(_admin),
) -> dict:
    ensure_default_templates(db)
    row = db.query(NotificationTemplate).filter(NotificationTemplate.key == key).first()
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    plain = body.body_plain_template
    if plain is None and body.body_template is not None:
        plain = body.body_template
    try:
        row = tmpl_mgr.update_template(
            db,
            row,
            actor_id=user.id,
            name=body.name,
            description=body.description,
            event_type=body.event_type,
            channel=body.channel,
            subject_template=body.subject_template,
            body_plain_template=plain,
            body_html_template=body.body_html_template,
            change_note=body.change_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(row)


@router.post("/notification-templates/{key}/clone", response_model=TemplateOut, status_code=201)
def clone_template(
    key: str,
    body: TemplateCloneRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(_admin),
) -> dict:
    source = tmpl_mgr.get_template_row(db, key)
    if not source:
        raise HTTPException(status_code=404, detail="Template not found")
    row = tmpl_mgr.clone_template(
        db, source, actor_id=user.id, new_key=body.new_key, new_name=body.new_name
    )
    return _to_out(row)


@router.post("/notification-templates/{key}/activate", response_model=TemplateOut)
def activate_template(
    key: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(_admin),
) -> dict:
    row = tmpl_mgr.get_template_row(db, key)
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    try:
        row = tmpl_mgr.set_status(db, row, actor_id=user.id, status="active")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(row)


@router.post("/notification-templates/{key}/deactivate", response_model=TemplateOut)
def deactivate_template(
    key: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(_admin),
) -> dict:
    row = tmpl_mgr.get_template_row(db, key)
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    try:
        row = tmpl_mgr.set_status(db, row, actor_id=user.id, status="inactive")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(row)


@router.post("/notification-templates/{key}/archive", response_model=TemplateOut)
def archive_template(
    key: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(_admin),
) -> dict:
    row = tmpl_mgr.get_template_row(db, key)
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    try:
        row = tmpl_mgr.set_status(db, row, actor_id=user.id, status="archived")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(row)


@router.get("/notification-templates/{key}/versions")
def list_template_versions(
    key: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(_admin),
) -> list[dict]:
    row = tmpl_mgr.get_template_row(db, key)
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    versions = tmpl_mgr.list_versions(db, row.id)
    return [
        {
            "id": v.id,
            "version": v.version,
            "name": v.name,
            "event_type": v.event_type,
            "channel": v.channel,
            "subject_template": v.subject_template,
            "body_template": v.body_template,
            "body_plain_template": v.body_plain_template,
            "body_html_template": v.body_html_template,
            "status": v.status,
            "change_note": v.change_note,
            "changed_by": v.changed_by,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in versions
    ]


@router.post("/notification-templates/{key}/restore", response_model=TemplateOut)
def restore_template_version(
    key: str,
    body: TemplateRestoreRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(_admin),
) -> dict:
    row = tmpl_mgr.get_template_row(db, key)
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    try:
        row = tmpl_mgr.restore_version(db, row, actor_id=user.id, version=body.version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(row)


@router.post("/notification-templates/{key}/preview")
def preview_template(
    key: str,
    body: TemplatePreviewRequest,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> dict:
    row = tmpl_mgr.get_template_row(db, key)
    if not row and not (
        body.subject_template or body.body_plain_template or body.body_html_template
    ):
        raise HTTPException(status_code=404, detail="Template not found")
    ctx = sample_context()
    ctx.update(body.context or {})
    subject_src = body.subject_template or (row.subject_template if row else "")
    plain_src = body.body_plain_template or (
        (row.body_plain_template or row.body_template) if row else ""
    )
    html_src = body.body_html_template
    if html_src is None:
        html_src = row.body_html_template if row else ""
    return {
        "subject": render_template(subject_src, ctx, html_escape=False),
        "body_plain": render_template(plain_src, ctx, html_escape=False),
        "body_html": render_template(html_src or "", ctx, html_escape=True) if html_src else "",
        "context": ctx,
        "pa_note": (
            "Body line `To: <email>` is Power Automate Teams routing — not the SMTP To header."
        ),
    }


@router.post("/notifications/test")
def test_send(
    body: TestSendRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(
        require_roles(
            RoleName.publisher.value,
            RoleName.platform_administrator.value,
        )
    ),
) -> dict:
    """Preview/test send — uses log sink / capture when SMTP_ENABLED=false."""
    if user.is_admin:
        require_capability("notification_admin")
    ensure_default_templates(db)
    parts = render_template_parts(db, body.template_key)
    ctx = sample_context()
    ctx.update(
        {
            "title": "Test notification",
            "kind": "planned_maintenance",
            "status": "scheduled",
            "approval_state": "confirmed_scheduled",
            "approval_label": "Confirmed",
            "starts_at": "2026-11-10T02:00:00Z",
            "ends_at": "2026-11-10T04:00:00Z",
            "timezone": "UTC",
            "expected_impact": "None (test)",
            "note": "test send",
            **body.context,
        }
    )
    if body.teams_target_email:
        ctx["teams_target_email"] = body.teams_target_email
    if body.bridge_channel_key:
        ctx["bridge_channel_key"] = body.bridge_channel_key
        ctx.setdefault(
            "teams_target_email",
            body.teams_target_email or f"{body.bridge_channel_key}@example.com",
        )

    subject = render_template(parts["subject_template"], ctx, html_escape=False)
    body_plain = render_template(parts["body_plain_template"], ctx, html_escape=False)
    body_html = (
        render_template(parts["body_html_template"], ctx, html_escape=True)
        if parts["body_html_template"]
        else None
    )

    if body.destination_type == "teams_bridge_channel":
        from maintenancehub_api.adapters.bridge import render_bridge_subject

        key_name = parts.get("key") or body.template_key
        if key_name.startswith("pa.") or subject.strip().startswith("[TEAMS]"):
            # PA-compatible: keep template subject; SMTP To is bridge mailbox.
            pass
        else:
            subject = render_bridge_subject(
                channel_key=body.bridge_channel_key or "test-channel",
                title=ctx.get("title") or "Test notification",
            )
        channel = "bridge"
    else:
        channel = "smtp"

    key = f"test:{user.id}:{body.destination}:{body.template_key}:{uuid.uuid4().hex[:8]}"
    row, _created = create_delivery_idempotent(
        db,
        idempotency_key=key,
        channel=channel,
        destination_type=body.destination_type,
        destination=body.destination,
        subject=subject,
        body=body_plain,
        body_plain=body_plain,
        body_html=body_html,
        template_id=parts.get("template_id"),
        template_version=parts.get("template_version"),
        rendered_payload={
            "subject": subject,
            "body_plain": body_plain,
            "body_html": body_html or "",
            "teams_target_email": ctx.get("teams_target_email") or "",
            "bridge_channel_key": ctx.get("bridge_channel_key") or "",
            "template_key": parts.get("key"),
            "template_id": parts.get("template_id"),
            "template_version": parts.get("template_version"),
            "channel": channel,
            "destination": body.destination,
            "destination_type": body.destination_type,
            "test": True,
            "capture_only": body.capture_only,
        },
        event_id=None,
        subscription_id=None,
    )
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create test delivery")
    sent = send_delivery(db, row.id)
    return {
        "delivery_id": sent.id,
        "status": sent.status.value if hasattr(sent.status, "value") else sent.status,
        "channel": sent.channel,
        "subject": sent.subject,
        "provider_message_id": sent.provider_message_id,
        "rendered_payload": sent.rendered_payload,
        "preview": {
            "subject": subject,
            "body": body_plain,
            "body_plain": body_plain,
            "body_html": body_html or "",
        },
        "note": (
            "Teams via email bridge. Body `To:` is PA routing; SMTP To is the bridge mailbox."
            if body.destination_type == "teams_bridge_channel"
            else (
                "Demo capture / log sink (SMTP disabled or capture dir set)."
                if body.capture_only
                else "SMTP or log sink"
            )
        ),
    }
