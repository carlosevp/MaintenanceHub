"""Application-scoped grants enforced on event mutations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import auth_header


def test_publisher_cannot_mutate_ungranted_app(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    other = auth_header(client, "viewer@test.example.com")
    # Promote a second publisher via admin-created app as admin, then try with first publisher
    env = client.post(
        "/api/v1/environments",
        json={"key": "PROD", "name": "Production", "sort_order": 1},
        headers=admin,
    ).json()
    app = client.post(
        "/api/v1/applications",
        json={
            "key": "secrets-vault",
            "name": "Secrets",
            "environments": [{"environment_id": env["id"], "display_name": "Vault-PROD"}],
        },
        headers=admin,
    ).json()
    # Admin-created app: publisher has no grant
    now = datetime.now(timezone.utc)
    denied = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Should fail",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env["id"],
                }
            ],
        },
        headers=pub,
    )
    assert denied.status_code == 403, denied.text
    assert "grant" in denied.json()["detail"].lower()
    # viewer still cannot create
    assert (
        client.post(
            "/api/v1/events",
            json={
                "kind": "planned_maintenance",
                "title": "Nope",
                "approval_state": "confirmed_scheduled",
                "starts_at": (now + timedelta(hours=1)).isoformat(),
                "ends_at": (now + timedelta(hours=2)).isoformat(),
                "timezone": "UTC",
                "impacts": [],
            },
            headers=other,
        ).status_code
        == 403
    )


def test_creator_grant_allows_event_lifecycle(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    env = client.post(
        "/api/v1/environments",
        json={"key": "QA", "name": "QA", "sort_order": 1},
        headers=admin,
    ).json()
    app = client.post(
        "/api/v1/applications",
        json={
            "key": "billing",
            "name": "Billing",
            "environments": [{"environment_id": env["id"], "display_name": "Bill-QA"}],
        },
        headers=pub,
    ).json()
    now = datetime.now(timezone.utc)
    created = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Billing patch",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env["id"],
                }
            ],
        },
        headers=pub,
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]
    ok = client.post(
        f"/api/v1/events/{event_id}/transition",
        json={"status": "in_progress"},
        headers=pub,
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "in_progress"
