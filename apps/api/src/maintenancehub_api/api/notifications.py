from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, get_current_user, require_roles
from maintenancehub_api.domain.notifications import (
    create_delivery_idempotent,
    ensure_default_templates,
    get_template,
    send_delivery,
)
from maintenancehub_api.domain.templates import render_template
from maintenancehub_api.models import NotificationDelivery, NotificationTemplate, RoleName
from maintenancehub_api.schemas.subscriptions import (
    DeliveryOut,
    TemplateOut,
    TemplatePatch,
    TestSendRequest,
)

router = APIRouter(tags=["notifications"])


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


@router.get("/notification-templates", response_model=list[TemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> list[NotificationTemplate]:
    ensure_default_templates(db)
    return db.query(NotificationTemplate).order_by(NotificationTemplate.key).all()


@router.patch("/notification-templates/{key}", response_model=TemplateOut)
def patch_template(
    key: str,
    body: TemplatePatch,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> NotificationTemplate:
    from maintenancehub_api.api.experience import require_capability

    require_capability("notification_admin")
    ensure_default_templates(db)
    row = db.query(NotificationTemplate).filter(NotificationTemplate.key == key).first()
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    if body.subject_template is not None:
        row.subject_template = body.subject_template
    if body.body_template is not None:
        row.body_template = body.body_template
    db.commit()
    db.refresh(row)
    return row


@router.post("/notifications/test")
def test_send(
    body: TestSendRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(
        RoleName.publisher.value,
        RoleName.platform_administrator.value,
    )),
) -> dict:
    """Preview/test send — uses log sink when SMTP_ENABLED=false."""
    ensure_default_templates(db)
    subject_t, body_t = get_template(db, body.template_key)
    ctx = {
        "title": "Test notification",
        "kind": "planned_maintenance",
        "status": "scheduled",
        "approval_state": "confirmed_scheduled",
        "starts_at": "2026-11-10T02:00:00Z",
        "ends_at": "2026-11-10T04:00:00Z",
        "timezone": "UTC",
        "expected_impact": "None (test)",
        "from_status": "",
        "previous_ends_at": "",
        "note": "test send",
        "offset_label": "",
        **body.context,
    }
    subject = render_template(subject_t, ctx)
    body_text = render_template(body_t, ctx)
    if body.destination_type == "teams_bridge_channel":
        from maintenancehub_api.adapters.bridge import render_bridge_subject

        subject = render_bridge_subject(
            channel_key=body.bridge_channel_key or "test-channel",
            title=ctx["title"],
        )
        channel = "bridge"
    else:
        channel = "smtp"

    key = f"test:{user.id}:{body.destination}:{body.template_key}"
    # Allow re-test by uniquifying
    import uuid

    key = f"{key}:{uuid.uuid4().hex[:8]}"
    row, _created = create_delivery_idempotent(
        db,
        idempotency_key=key,
        channel=channel,
        destination_type=body.destination_type,
        destination=body.destination,
        subject=subject,
        body=body_text,
        event_id=None,
        subscription_id=None,
    )
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create test delivery")
    sent = send_delivery(db, row.id)
    return {
        "delivery_id": sent.id,
        "status": sent.status.value,
        "channel": sent.channel,
        "subject": sent.subject,
        "provider_message_id": sent.provider_message_id,
        "preview": {"subject": subject, "body": body_text},
        "note": (
            "Teams via email bridge"
            if body.destination_type == "teams_bridge_channel"
            else "SMTP or log sink"
        ),
    }


# Integration connection tests live in api/admin_integrations.py (M9+)
