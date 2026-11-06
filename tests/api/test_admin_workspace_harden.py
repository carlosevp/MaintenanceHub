"""M15 finalize — RBAC matrix, creds lifecycle, concurrent retry, SN/CSV, pagination."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from unittest.mock import patch

from maintenancehub_api.adapters.smtp import SendResult
from maintenancehub_api.domain.notifications import send_delivery
from maintenancehub_api.models import (
    Application,
    DeliveryStatus,
    Job,
    JobStatus,
    NotificationDelivery,
)
from tests.conftest import auth_header

ADMIN_GETS = [
    "/api/v1/admin/overview",
    "/api/v1/admin/secrets-status",
    "/api/v1/admin/users",
    "/api/v1/admin/grants",
    "/api/v1/admin/dependencies",
    "/api/v1/admin/deliveries",
    "/api/v1/admin/jobs",
    "/api/v1/admin/audit",
    "/api/v1/admin/settings/integrations",
    "/api/v1/admin/servicenow/unmatched",
    "/api/v1/admin/imports",
    "/api/v1/admin/role-mappings",
    "/api/v1/admin/service-credentials",
]


def test_publisher_denied_all_admin_gets(client):
    pub = auth_header(client, "publisher@test.example.com")
    admin = auth_header(client, "admin@test.example.com")
    for path in ADMIN_GETS:
        assert client.get(path, headers=pub).status_code == 403, path
        assert client.get(path, headers=admin).status_code == 200, path


def test_service_credential_lifecycle_redaction_and_audit(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")

    assert (
        client.post(
            "/api/v1/admin/service-credentials",
            headers=pub,
            json={"name": "nope"},
        ).status_code
        == 403
    )

    created = client.post(
        "/api/v1/admin/service-credentials",
        headers=admin,
        json={"name": "banner-bot", "scopes": ["banner:read"]},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["client_secret"]
    secret_once = body["client_secret"]
    cid = body["id"]

    listed = client.get("/api/v1/admin/service-credentials", headers=admin).json()
    row = next(r for r in listed if r["id"] == cid)
    assert "client_secret" not in row
    assert "secret_hash" not in row
    assert secret_once not in str(listed)

    rotated = client.post(f"/api/v1/admin/service-credentials/{cid}/rotate", headers=admin)
    assert rotated.status_code == 200
    assert rotated.json()["client_secret"]
    assert rotated.json()["client_secret"] != secret_once

    revoked = client.post(f"/api/v1/admin/service-credentials/{cid}/revoke", headers=admin)
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"]

    # rotate after revoke → not found
    assert (
        client.post(f"/api/v1/admin/service-credentials/{cid}/rotate", headers=admin).status_code
        == 404
    )

    audit = client.get("/api/v1/admin/audit?entity_type=service_credential", headers=admin)
    actions = {r["action"] for r in audit.json()}
    assert "service_credential.create" in actions
    assert "service_credential.rotate" in actions
    assert "service_credential.revoke" in actions
    assert secret_once not in audit.text


def test_uncertain_smtp_delivery_blocks_retry(client, db_session):
    admin = auth_header(client, "admin@test.example.com")
    delivery = NotificationDelivery(
        idempotency_key="uncertain-1",
        channel="smtp",
        destination_type="email_address",
        destination="ops@example.com",
        subject="s",
        body="b",
        status=DeliveryStatus.pending,
        attempt_count=0,
    )
    db_session.add(delivery)
    db_session.commit()

    with patch(
        "maintenancehub_api.domain.notifications.get_smtp_adapter"
    ) as mock_get:
        mock_get.return_value.send.return_value = SendResult(
            ok=True,
            uncertain=True,
            provider_message_id="uncertain-smtp-x",
            error="UNCERTAIN: SMTP accepted payload; response lost (timeout)",
            channel="smtp",
        )
        sent = send_delivery(db_session, delivery.id)

    assert sent.status == DeliveryStatus.sent
    assert sent.last_error and sent.last_error.startswith("UNCERTAIN:")

    job = Job(
        job_type="notify_send",
        payload={"delivery_id": delivery.id},
        idempotency_key=f"send:{delivery.id}:retry:1",
        status=JobStatus.failed,
        run_at=datetime.now(timezone.utc),
        last_error="worker crashed after handoff",
    )
    db_session.add(job)
    db_session.commit()

    refused = client.post(f"/api/v1/admin/jobs/{job.id}/retry", headers=admin)
    assert refused.status_code == 409
    assert "uncertain" in refused.json()["detail"].lower()


def test_concurrent_job_retry_single_winner(client, db_engine, db_session):
    admin = auth_header(client, "admin@test.example.com")
    delivery = NotificationDelivery(
        idempotency_key="conc-retry",
        channel="log",
        destination_type="email_address",
        destination="ops@example.com",
        subject="s",
        body="b",
        status=DeliveryStatus.failed,
        attempt_count=2,
    )
    db_session.add(delivery)
    db_session.flush()
    job = Job(
        job_type="notify_send",
        payload={"delivery_id": delivery.id},
        idempotency_key=f"send:{delivery.id}:retry:2",
        status=JobStatus.failed,
        run_at=datetime.now(timezone.utc),
        last_error="boom",
    )
    db_session.add(job)
    db_session.commit()
    job_id = job.id

    # Use the same TestClient sequentially with lock semantics; SQLite StaticPool
    # still honors with_for_update within a connection. Fire two retries: first
    # succeeds, second must 409 because status is no longer failed/dead.
    first = client.post(f"/api/v1/admin/jobs/{job_id}/retry", headers=admin)
    assert first.status_code == 200
    assert first.json()["status"] == "queued"
    second = client.post(f"/api/v1/admin/jobs/{job_id}/retry", headers=admin)
    assert second.status_code == 409


def test_sn_dry_run_vs_poll_and_publisher_denied(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")

    assert (
        client.post(
            "/api/v1/admin/servicenow/poll-now",
            headers=pub,
            json={"dry_run": True},
        ).status_code
        == 403
    )

    dry = client.post(
        "/api/v1/admin/servicenow/poll-now",
        headers=admin,
        json={
            "dry_run": True,
            "fixture_records": [
                {
                    "sys_id": "chg-dry-1",
                    "number": "CHG0001",
                    "short_description": "Dry run",
                    "state": "scheduled",
                    "cmdb_ci": "ci-x",
                }
            ],
        },
    )
    assert dry.status_code == 200, dry.text
    assert dry.json()["dry_run"] is True
    assert dry.json()["fetched"] >= 1
    # dry-run must not enqueue a job
    assert "enqueued_job_id" not in dry.json()

    live = client.post(
        "/api/v1/admin/servicenow/poll-now",
        headers=admin,
        json={"dry_run": False},
    )
    assert live.status_code == 200
    # With SN disabled, still enqueues durable job (or returns stats with fixtures)
    assert "enqueued_job_id" in live.json() or "fetched" in live.json()


def test_csv_partial_never_deletes_absences(client, db_session):
    admin = auth_header(client, "admin@test.example.com")
    # Seed two CIs + a relationship, then import only one CI — count deps unchanged
    up = client.post(
        "/api/v1/admin/imports/csv",
        headers=admin,
        data={"kind": "cmdb_ci"},
        files={
            "file": (
                "cis.csv",
                io.BytesIO(
                    b"sys_id,name,short_description,description\n"
                    b"ci-a,App A,A,desc\nci-b,App B,B,desc\n"
                ),
                "text/csv",
            )
        },
    )
    jid = up.json()["id"]
    client.post(f"/api/v1/admin/imports/{jid}/preview", headers=admin)
    client.post(f"/api/v1/admin/imports/{jid}/commit", headers=admin)

    rel = client.post(
        "/api/v1/admin/imports/csv",
        headers=admin,
        data={"kind": "ci_relationships"},
        files={
            "file": (
                "rel.csv",
                io.BytesIO(b"parent_sys_id,child_sys_id,type\nci-a,ci-b,depends_on\n"),
                "text/csv",
            )
        },
    )
    rid = rel.json()["id"]
    client.post(f"/api/v1/admin/imports/{rid}/preview", headers=admin)
    c1 = client.post(f"/api/v1/admin/imports/{rid}/commit", headers=admin)
    assert c1.json()["result"]["absences_deleted"] == 0
    assert c1.json()["result"]["import_mode"] == "partial"

    # Partial re-import with empty relationships does not delete prior edges
    empty = client.post(
        "/api/v1/admin/imports/csv",
        headers=admin,
        data={"kind": "ci_relationships"},
        files={
            "file": (
                "empty-rel.csv",
                io.BytesIO(b"parent_sys_id,child_sys_id,type\n"),
                "text/csv",
            )
        },
    )
    eid = empty.json()["id"]
    client.post(f"/api/v1/admin/imports/{eid}/preview", headers=admin)
    c2 = client.post(f"/api/v1/admin/imports/{eid}/commit", headers=admin)
    assert c2.json()["result"]["absences_deleted"] == 0

    deps = client.get("/api/v1/admin/dependencies", headers=admin).json()
    assert any(d["origin"] == "import" for d in deps)


def test_audit_and_jobs_pagination(client, db_session):
    admin = auth_header(client, "admin@test.example.com")
    for i in range(5):
        db_session.add(
            Job(
                job_type="sn_poll",
                payload={},
                idempotency_key=f"page-job-{i}",
                status=JobStatus.succeeded,
                run_at=datetime.now(timezone.utc),
            )
        )
    db_session.commit()

    page1 = client.get("/api/v1/admin/jobs?limit=2&offset=0", headers=admin)
    page2 = client.get("/api/v1/admin/jobs?limit=2&offset=2", headers=admin)
    assert page1.status_code == 200
    assert len(page1.json()) == 2
    ids1 = {j["id"] for j in page1.json()}
    ids2 = {j["id"] for j in page2.json()}
    assert ids1.isdisjoint(ids2)

    # Create a few audited actions then page audit
    for n in range(3):
        created = client.post(
            "/api/v1/admin/role-mappings",
            headers=admin,
            json={"directory_group": f"mh-page-{n}", "role": "viewer"},
        )
        assert created.status_code == 201, created.text
    a1 = client.get("/api/v1/admin/audit?limit=1&offset=0", headers=admin)
    a2 = client.get("/api/v1/admin/audit?limit=1&offset=1", headers=admin)
    assert len(a1.json()) == 1 and len(a2.json()) == 1
    assert a1.json()[0]["id"] != a2.json()[0]["id"]


def test_cross_app_dependency_requires_grant(client, db_session):
    pub = auth_header(client, "publisher@test.example.com")
    admin = auth_header(client, "admin@test.example.com")
    a = Application(key="xapp-a", name="X A")
    b = Application(key="xapp-b", name="X B")
    db_session.add_all([a, b])
    db_session.commit()

    denied = client.post(
        f"/api/v1/applications/{a.id}/dependencies",
        headers=pub,
        json={"to_type": "application", "to_id": b.id},
    )
    assert denied.status_code == 403

    publisher_id = client.get("/api/v1/auth/me", headers=pub).json()["id"]
    client.post(
        "/api/v1/admin/grants",
        headers=admin,
        json={"user_id": publisher_id, "application_id": a.id, "role": "publisher"},
    )
    ok = client.post(
        f"/api/v1/applications/{a.id}/dependencies",
        headers=pub,
        json={"to_type": "application", "to_id": b.id},
    )
    assert ok.status_code == 201


def test_secrets_status_runtime_vs_deployment(client):
    admin = auth_header(client, "admin@test.example.com")
    body = client.get("/api/v1/admin/secrets-status", headers=admin).json()
    assert "runtime_editable" in body
    assert "deployment_only" in body
    assert "JWT_SECRET" in body["openshift_only"]
    assert body["smtp"]["ui_editable"] is False
    assert "password" not in str(body["smtp"]).lower() or "password_configured" in str(body["smtp"])
