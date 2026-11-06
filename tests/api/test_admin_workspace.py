"""M15 — Administration workspace authz, grants, secrets redaction, retry idempotency."""

from __future__ import annotations

import io
from datetime import datetime, timezone

from maintenancehub_api.models import (
    Application,
    DeliveryStatus,
    Job,
    JobStatus,
    NotificationDelivery,
)
from tests.conftest import auth_header


def test_admin_overview_requires_admin(client):
    pub = auth_header(client, "publisher@test.example.com")
    denied = client.get("/api/v1/admin/overview", headers=pub)
    assert denied.status_code == 403

    admin = auth_header(client, "admin@test.example.com")
    ok = client.get("/api/v1/admin/overview", headers=admin)
    assert ok.status_code == 200
    body = ok.json()
    assert "catalog" in body
    assert "secrets" not in str(body).lower() or "never" in body.get("note", "").lower()


def test_secrets_status_never_exposes_password_values(client, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "super-secret-smtp")
    monkeypatch.setenv("SERVICENOW_PASSWORD", "sn-secret-value")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()

    pub = auth_header(client, "publisher@test.example.com")
    assert client.get("/api/v1/admin/secrets-status", headers=pub).status_code == 403

    admin = auth_header(client, "admin@test.example.com")
    res = client.get("/api/v1/admin/secrets-status", headers=admin)
    assert res.status_code == 200
    raw = res.text
    assert "super-secret-smtp" not in raw
    assert "sn-secret-value" not in raw
    body = res.json()
    assert body["smtp"]["password_configured"] is True
    assert body["servicenow"]["password_configured"] is True
    assert body["smtp"]["ui_editable"] is False
    assert "SMTP_PASSWORD" in body["openshift_only"]


def test_users_and_grants_crud_admin_only(client, db_session):
    pub = auth_header(client, "publisher@test.example.com")
    admin = auth_header(client, "admin@test.example.com")

    assert client.get("/api/v1/admin/users", headers=pub).status_code == 403
    users = client.get("/api/v1/admin/users", headers=admin)
    assert users.status_code == 200
    assert any(u["email"] == "admin@test.example.com" for u in users.json())

    app = Application(key="grant-app", name="Grant App")
    db_session.add(app)
    db_session.commit()

    publisher = db_session.publisher  # type: ignore[attr-defined]
    create = client.post(
        "/api/v1/admin/grants",
        headers=admin,
        json={
            "user_id": publisher.id,
            "application_id": app.id,
            "role": "publisher",
        },
    )
    assert create.status_code == 201, create.text
    grant_id = create.json()["id"]

    assert client.post(
        "/api/v1/admin/grants",
        headers=pub,
        json={"user_id": publisher.id, "application_id": app.id, "role": "publisher"},
    ).status_code == 403

    listed = client.get("/api/v1/admin/grants", headers=admin)
    assert any(g["id"] == grant_id for g in listed.json())

    deleted = client.delete(f"/api/v1/admin/grants/{grant_id}", headers=admin)
    assert deleted.status_code == 204

    audit = client.get("/api/v1/admin/audit?action=grant", headers=admin)
    assert audit.status_code == 200
    actions = {r["action"] for r in audit.json()}
    assert "grant.create" in actions
    assert "grant.delete" in actions


def test_dependency_self_ref_and_duplicate_rejected(client, db_session):
    admin = auth_header(client, "admin@test.example.com")
    a = Application(key="dep-a", name="Dep A")
    b = Application(key="dep-b", name="Dep B")
    db_session.add_all([a, b])
    db_session.commit()

    self_ref = client.post(
        "/api/v1/admin/dependencies",
        headers=admin,
        json={
            "from_type": "application",
            "from_id": a.id,
            "to_type": "application",
            "to_id": a.id,
        },
    )
    assert self_ref.status_code == 400

    created = client.post(
        "/api/v1/admin/dependencies",
        headers=admin,
        json={
            "from_type": "application",
            "from_id": a.id,
            "to_type": "application",
            "to_id": b.id,
        },
    )
    assert created.status_code == 201, created.text
    assert "Consumer depends on Provider" in created.json()["description"]

    dup = client.post(
        "/api/v1/admin/dependencies",
        headers=admin,
        json={
            "from_type": "application",
            "from_id": a.id,
            "to_type": "application",
            "to_id": b.id,
        },
    )
    assert dup.status_code == 409

    dep_id = created.json()["id"]
    assert client.delete(f"/api/v1/admin/dependencies/{dep_id}", headers=admin).status_code == 204


def test_csv_preview_commit_via_admin_flow(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    csv_body = """sys_id,name,short_description,description
ci-m15,m15-app,M15 App,Admin CSV
"""
    assert (
        client.post(
            "/api/v1/admin/imports/csv",
            headers=pub,
            data={"kind": "cmdb_ci"},
            files={"file": ("m15.csv", io.BytesIO(csv_body.encode()), "text/csv")},
        ).status_code
        == 403
    )

    up = client.post(
        "/api/v1/admin/imports/csv",
        headers=admin,
        data={"kind": "cmdb_ci"},
        files={"file": ("m15.csv", io.BytesIO(csv_body.encode()), "text/csv")},
    )
    assert up.status_code == 200
    job_id = up.json()["id"]
    preview = client.post(f"/api/v1/admin/imports/{job_id}/preview", headers=admin)
    assert preview.status_code == 200
    assert preview.json()["valid_rows"] >= 1
    commit = client.post(f"/api/v1/admin/imports/{job_id}/commit", headers=admin)
    assert commit.status_code == 200


def test_job_retry_authz_and_sent_delivery_idempotency(client, db_session):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")

    delivery = NotificationDelivery(
        idempotency_key="m15-retry-sent",
        channel="log",
        destination_type="email_address",
        destination="ops@example.com",
        subject="hello",
        body="world",
        status=DeliveryStatus.sent,
        attempt_count=1,
    )
    db_session.add(delivery)
    db_session.flush()

    job = Job(
        job_type="notify_send",
        payload={"delivery_id": delivery.id},
        idempotency_key=f"send:{delivery.id}",
        status=JobStatus.failed,
        run_at=datetime.now(timezone.utc),
        last_error="simulated",
    )
    db_session.add(job)
    db_session.commit()

    assert client.post(f"/api/v1/admin/jobs/{job.id}/retry", headers=pub).status_code == 403

    refused = client.post(f"/api/v1/admin/jobs/{job.id}/retry", headers=admin)
    assert refused.status_code == 409
    assert "already sent" in refused.json()["detail"].lower()

    delivery2 = NotificationDelivery(
        idempotency_key="m15-retry-failed",
        channel="log",
        destination_type="email_address",
        destination="ops2@example.com",
        subject="hello",
        body="world",
        status=DeliveryStatus.failed,
        attempt_count=2,
    )
    db_session.add(delivery2)
    db_session.flush()
    job2 = Job(
        job_type="notify_send",
        payload={"delivery_id": delivery2.id},
        idempotency_key=f"send:{delivery2.id}:retry:2",
        status=JobStatus.dead,
        run_at=datetime.now(timezone.utc),
        last_error="still failing",
    )
    db_session.add(job2)
    db_session.commit()

    ok = client.post(f"/api/v1/admin/jobs/{job2.id}/retry", headers=admin)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "queued"

    # Idempotent: retry while queued is rejected
    again = client.post(f"/api/v1/admin/jobs/{job2.id}/retry", headers=admin)
    assert again.status_code == 409


def test_role_mapping_delete_and_cred_revoke(client):
    admin = auth_header(client, "admin@test.example.com")
    created = client.post(
        "/api/v1/admin/role-mappings",
        headers=admin,
        json={"directory_group": "mh-m15-test", "role": "viewer"},
    )
    assert created.status_code == 201
    mid = created.json()["id"]
    assert client.delete(f"/api/v1/admin/role-mappings/{mid}", headers=admin).status_code == 204

    cred = client.post(
        "/api/v1/admin/service-credentials",
        headers=admin,
        json={"name": "m15-banner", "scopes": ["banner:read"]},
    )
    assert cred.status_code == 201
    assert "client_secret" in cred.json()
    cid = cred.json()["id"]
    rev = client.post(f"/api/v1/admin/service-credentials/{cid}/revoke", headers=admin)
    assert rev.status_code == 200
    listed = client.get("/api/v1/admin/service-credentials", headers=admin).json()
    row = next(c for c in listed if c["id"] == cid)
    assert row["revoked_at"] is not None
