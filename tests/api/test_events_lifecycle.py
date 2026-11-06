from datetime import datetime, timedelta, timezone

from tests.conftest import auth_header


def _bootstrap_app(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    env = client.post(
        "/api/v1/environments",
        json={"key": "PROD", "name": "Production", "sort_order": 1},
        headers=admin,
    ).json()
    app = client.post(
        "/api/v1/applications",
        json={
            "key": "pay",
            "name": "Pay",
            "environments": [{"environment_id": env["id"], "display_name": "Pay-PROD"}],
        },
        headers=pub,
    ).json()
    return pub, app, env


def test_create_confirmed_maintenance_and_transition(client):
    pub, app, env = _bootstrap_app(client)
    now = datetime.now(timezone.utc)
    res = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Patch",
            "description": "desc",
            "expected_impact": "readonly",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=3)).isoformat(),
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
    assert res.status_code == 201, res.text
    event = res.json()
    assert event["status"] == "scheduled"
    assert event["approval_state"] == "confirmed_scheduled"
    assert len(event["impacts"]) == 1

    bad = client.post(
        f"/api/v1/events/{event['id']}/transition",
        json={"status": "completed"},
        headers=pub,
    )
    assert bad.status_code == 409

    ok = client.post(
        f"/api/v1/events/{event['id']}/transition",
        json={"status": "in_progress", "note": "go"},
        headers=pub,
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "in_progress"

    timeline = client.get(f"/api/v1/events/{event['id']}/timeline", headers=pub)
    assert timeline.status_code == 200
    types = [t["entry_type"] for t in timeline.json()]
    assert "status_change" in types


def test_extend_updates_ends_at_and_status(client):
    pub, app, env = _bootstrap_app(client)
    now = datetime.now(timezone.utc)
    event = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Extendable",
            "approval_state": "confirmed_scheduled",
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
        },
        headers=pub,
    ).json()
    client.post(
        f"/api/v1/events/{event['id']}/transition",
        json={"status": "in_progress"},
        headers=pub,
    )
    new_end = now + timedelta(hours=5)
    ext = client.post(
        f"/api/v1/events/{event['id']}/extend",
        json={"new_ends_at": new_end.isoformat(), "note": "+3h"},
        headers=pub,
    )
    assert ext.status_code == 200, ext.text
    body = ext.json()
    assert body["status"] == "extended"
    assert body["ends_at"].startswith(new_end.strftime("%Y-%m-%dT%H:%M"))


def test_viewer_cannot_create_event(client):
    pub, app, env = _bootstrap_app(client)
    viewer = auth_header(client, "viewer@test.example.com")
    now = datetime.now(timezone.utc)
    res = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Nope",
            "approval_state": "confirmed_scheduled",
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
        },
        headers=viewer,
    )
    assert res.status_code == 403


def test_filter_by_approval_state(client):
    pub, app, env = _bootstrap_app(client)
    now = datetime.now(timezone.utc)
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Approved only",
            "approval_state": "approved_window",
            "starts_at": (now + timedelta(days=1)).isoformat(),
            "ends_at": (now + timedelta(days=1, hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {"target_type": "application", "target_id": app["id"], "environment_id": env["id"]}
            ],
        },
        headers=pub,
    )
    listed = client.get(
        "/api/v1/events?approval_state=approved_window",
        headers=pub,
    )
    assert listed.status_code == 200
    assert any(e["approval_state"] == "approved_window" for e in listed.json())
