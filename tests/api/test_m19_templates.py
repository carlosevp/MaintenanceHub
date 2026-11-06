"""M19 Power Automate Notification Template Manager — CRUD, versions, preview, worker payload."""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import auth_header


def test_catalog_and_pa_sample(client):
    admin = auth_header(client, "admin@test.example.com")
    catalog = client.get("/api/v1/notification-templates/catalog", headers=admin)
    assert catalog.status_code == 200, catalog.text
    body = catalog.json()
    assert any(e["key"] == "pa.teams_alert" for e in body["event_types"])
    assert any(p["key"] == "teams_target_email" for p in body["placeholders"])
    assert body["pa_notes"]["subject_default"] == "[TEAMS] Maintenance Alert"

    templates = client.get("/api/v1/notification-templates", headers=admin)
    assert templates.status_code == 200
    keys = {t["key"] for t in templates.json()}
    assert "pa.teams_alert" in keys
    assert "event.created" in keys
    pa = next(t for t in templates.json() if t["key"] == "pa.teams_alert")
    assert pa["subject_template"] == "[TEAMS] Maintenance Alert"
    assert "To: {{teams_target_email}}" in (pa["body_plain_template"] or pa["body_template"])
    assert pa["is_system"] is True
    assert pa["status"] == "active"


def test_crud_clone_activate_restore_audit(client, db_session):
    admin = auth_header(client, "admin@test.example.com")
    viewer = auth_header(client, "viewer@test.example.com")

    denied = client.post(
        "/api/v1/notification-templates",
        headers=viewer,
        json={
            "key": "custom.denied",
            "name": "Denied",
            "event_type": "event.created",
            "subject_template": "x",
            "body_plain_template": "y",
        },
    )
    assert denied.status_code in {401, 403}

    created = client.post(
        "/api/v1/notification-templates",
        headers=admin,
        json={
            "key": "custom.ops",
            "name": "Ops alert",
            "event_type": "event.created",
            "subject_template": "[MaintenanceHub] {{title}}",
            "body_plain_template": "Hello {{title}}",
            "body_html_template": '<p onclick="x">Hello {{title}}</p><script>bad()</script>',
            "activate": True,
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["key"] == "custom.ops"
    assert row["version"] == 1
    assert "onclick" not in (row["body_html_template"] or "").lower()
    assert "<script" not in (row["body_html_template"] or "").lower()

    patched = client.patch(
        "/api/v1/notification-templates/custom.ops",
        headers=admin,
        json={
            "subject_template": "[MaintenanceHub] Updated {{title}}",
            "body_plain_template": "Updated {{title}}",
            "change_note": "tweak subject",
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["version"] == 2

    versions = client.get("/api/v1/notification-templates/custom.ops/versions", headers=admin)
    assert versions.status_code == 200
    vers = versions.json()
    assert {v["version"] for v in vers} >= {1, 2}

    cloned = client.post(
        "/api/v1/notification-templates/custom.ops/clone",
        headers=admin,
        json={"new_key": "custom.ops.copy", "new_name": "Ops copy"},
    )
    assert cloned.status_code == 201, cloned.text
    assert cloned.json()["status"] == "inactive"

    activated = client.post(
        "/api/v1/notification-templates/custom.ops.copy/activate", headers=admin
    )
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"

    deactivated = client.post(
        "/api/v1/notification-templates/custom.ops.copy/deactivate", headers=admin
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["status"] == "inactive"

    restored = client.post(
        "/api/v1/notification-templates/custom.ops/restore",
        headers=admin,
        json={"version": 1},
    )
    assert restored.status_code == 200, restored.text
    assert "Updated" not in restored.json()["subject_template"]
    assert restored.json()["version"] >= 3

    # System templates cannot be archived
    bad_archive = client.post(
        "/api/v1/notification-templates/pa.teams_alert/archive", headers=admin
    )
    assert bad_archive.status_code == 400

    from maintenancehub_api.models import AuditLog

    actions = {
        a.action
        for a in db_session.query(AuditLog)
        .filter(AuditLog.entity_type == "notification_template")
        .all()
    }
    assert "notification_template.create" in actions
    assert "notification_template.update" in actions


def test_preview_and_test_send_pa_capture(client, tmp_path, monkeypatch):
    monkeypatch.setenv("MH_NOTIFICATION_CAPTURE_DIR", str(tmp_path))
    admin = auth_header(client, "admin@test.example.com")

    preview = client.post(
        "/api/v1/notification-templates/pa.teams_alert/preview",
        headers=admin,
        json={
            "context": {
                "teams_target_email": "channel@contoso.com",
                "title": "INT cutover",
            }
        },
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["subject"] == "[TEAMS] Maintenance Alert"
    assert body["body_plain"].startswith("To: channel@contoso.com")
    assert "<" not in body["body_html"] or "INT cutover" in body["body_html"]

    # XSS: substituted HTML escaped
    xss = client.post(
        "/api/v1/notification-templates/pa.teams_alert/preview",
        headers=admin,
        json={"context": {"title": "<img src=x onerror=alert(1)>"}, "body_html_template": "<p>{{title}}</p>"},
    )
    assert xss.status_code == 200
    assert "<img" not in xss.json()["body_html"]
    assert "&lt;img" in xss.json()["body_html"]

    send = client.post(
        "/api/v1/notifications/test",
        headers=admin,
        json={
            "template_key": "pa.teams_alert",
            "destination_type": "teams_bridge_channel",
            "destination": "bridge-mailbox@example.com",
            "bridge_channel_key": "ops-payments",
            "teams_target_email": "ops-channel@contoso.com",
            "capture_only": True,
        },
    )
    assert send.status_code == 200, send.text
    payload = send.json()
    assert payload["status"] == "sent"
    assert payload["channel"] in {"log", "bridge"}
    assert payload["subject"] == "[TEAMS] Maintenance Alert"
    assert payload["preview"]["body_plain"].startswith("To: ops-channel@contoso.com")
    assert payload["rendered_payload"]["teams_target_email"] == "ops-channel@contoso.com"
    assert "PA routing" in payload["note"] or "bridge" in payload["note"].lower()

    captures = list(Path(tmp_path).glob("*.json"))
    assert captures, "expected MH_NOTIFICATION_CAPTURE_DIR file"
    captured = json.loads(captures[0].read_text())
    assert captured["subject"] == "[TEAMS] Maintenance Alert"
    assert captured["body"].startswith("To: ops-channel@contoso.com")
    # SMTP To is bridge mailbox — not the PA routing address
    assert captured["to"] == "bridge-mailbox@example.com"


def test_worker_persists_rendered_payload(client, db_session):
    from datetime import datetime, timedelta, timezone

    from maintenancehub_api.domain.notifications import (
        enqueue_deliveries_for_event,
        send_delivery,
    )
    from maintenancehub_api.models import (
        ApprovalState,
        DeliveryStatus,
        EventKind,
        EventStatus,
        MaintenanceEvent,
        NotificationDelivery,
        Subscription,
        SubscriptionTarget,
    )

    admin = auth_header(client, "admin@test.example.com")
    # Ensure templates exist via API
    assert client.get("/api/v1/notification-templates", headers=admin).status_code == 200

    now = datetime.now(timezone.utc)
    event = MaintenanceEvent(
        title="Payload event",
        kind=EventKind.planned_maintenance,
        status=EventStatus.scheduled,
        approval_state=ApprovalState.confirmed_scheduled,
        starts_at=now + timedelta(hours=2),
        ends_at=now + timedelta(hours=4),
        timezone="UTC",
        expected_impact="brief",
        created_by=db_session.admin.id,
    )
    db_session.add(event)
    db_session.flush()
    sub = Subscription(
        user_id=db_session.admin.id,
        destination_type="email_address",
        destination="ops@example.com",
        is_active=True,
    )
    db_session.add(sub)
    db_session.flush()
    db_session.add(
        SubscriptionTarget(subscription_id=sub.id, target_type="event", target_id=event.id)
    )
    db_session.commit()

    n = enqueue_deliveries_for_event(
        db_session, event, template_key="event.created", reason="event.created"
    )
    assert n == 1
    delivery = (
        db_session.query(NotificationDelivery)
        .filter(NotificationDelivery.event_id == event.id)
        .first()
    )
    assert delivery is not None
    assert delivery.rendered_payload is not None
    assert delivery.rendered_payload["subject"]
    assert delivery.body_plain or delivery.body
    assert delivery.template_id
    assert delivery.template_version
    assert delivery.status == DeliveryStatus.pending

    sent = send_delivery(db_session, delivery.id)
    assert sent.status == DeliveryStatus.sent


def test_legacy_bridge_test_still_embeds_channel(client):
    pub = auth_header(client, "publisher@test.example.com")
    res = client.post(
        "/api/v1/notifications/test",
        json={
            "template_key": "event.created",
            "destination_type": "teams_bridge_channel",
            "destination": "bridge@example.com",
            "bridge_channel_key": "ops-test",
        },
        headers=pub,
    )
    assert res.status_code == 200, res.text
    assert "ops-test" in res.json()["subject"]
