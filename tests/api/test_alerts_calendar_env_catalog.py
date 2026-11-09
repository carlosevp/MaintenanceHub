"""My Alerts enrichment, ICS download, environment catalog, dependency summaries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import auth_header


def _env(client, headers, key="PROD", name="Production", sort_order=1):
    res = client.post(
        "/api/v1/environments",
        json={"key": key, "name": name, "sort_order": sort_order, "description": f"{name} tier"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def _app(client, headers, env_id, key="alerts-app", name="Alerts App"):
    res = client.post(
        "/api/v1/applications",
        json={
            "key": key,
            "name": name,
            "environments": [{"environment_id": env_id, "display_name": f"{name}-{key}"}],
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_subscription_lists_friendly_names_not_raw_ids(client):
    pub = auth_header(client, "publisher@test.example.com")
    env = _env(client, pub, key="INT", name="Integration", sort_order=2)
    app = _app(client, pub, env["id"], key="claims", name="Claims Portal")

    created = client.post(
        "/api/v1/subscriptions",
        json={
            "destination_type": "email_address",
            "destination": "watcher@example.com",
            "targets": [
                {"target_type": "app_environment", "target_id": f"{app['id']}:{env['id']}"}
            ],
            "reminders": [{"offset_minutes": -1440}, {"offset_minutes": -30}],
            "notify_events": ["start", "cancellation"],
        },
        headers=pub,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["channel_label"] == "Email"
    assert "Start" in body["notify_event_labels"]
    assert "Cancellation" in body["notify_event_labels"]
    assert len(body["targets"]) == 1
    target = body["targets"][0]
    assert target["application_name"] == "Claims Portal"
    assert target["environment_name"] == "Integration"
    assert target["environment_key"] == "INT"
    assert "Claims Portal" in target["label"]
    assert "Integration" in target["label"]
    assert app["id"] not in target["label"]
    assert env["id"] not in target["label"]
    assert body["reminders"][0]["label"]

    listed = client.get("/api/v1/subscriptions", headers=pub)
    assert listed.status_code == 200
    assert listed.json()[0]["targets"][0]["application_name"] == "Claims Portal"


def test_subscription_missing_catalog_refs_graceful(client, db_session):
    pub = auth_header(client, "publisher@test.example.com")
    from maintenancehub_api.models import ReminderOffset, Subscription, SubscriptionTarget

    user = db_session.publisher  # type: ignore[attr-defined]
    sub = Subscription(
        user_id=user.id,
        destination_type="email_address",
        destination="ghost@example.com",
        notify_events=["start"],
    )
    db_session.add(sub)
    db_session.flush()
    db_session.add(
        SubscriptionTarget(
            subscription_id=sub.id,
            target_type="app_environment",
            target_id="missing-app:missing-env",
        )
    )
    db_session.add(ReminderOffset(subscription_id=sub.id, offset_minutes=-60))
    db_session.commit()

    listed = client.get("/api/v1/subscriptions", headers=pub).json()
    row = next(s for s in listed if s["id"] == sub.id)
    assert row["targets"][0]["missing"] is True
    assert "Unknown" in row["targets"][0]["label"]


def test_subscription_edit_and_delete(client):
    pub = auth_header(client, "publisher@test.example.com")
    env = _env(client, pub)
    app = _app(client, pub, env["id"])
    created = client.post(
        "/api/v1/subscriptions",
        json={
            "destination_type": "email_address",
            "destination": "a@example.com",
            "targets": [{"target_type": "application", "target_id": app["id"]}],
            "reminders": [{"offset_minutes": -240}],
            "notify_events": ["start", "extension", "cancellation", "completion"],
        },
        headers=pub,
    ).json()

    patched = client.patch(
        f"/api/v1/subscriptions/{created['id']}",
        json={
            "notify_events": ["completion"],
            "reminders": [{"offset_minutes": -30}],
            "targets": [
                {"target_type": "app_environment", "target_id": f"{app['id']}:{env['id']}"}
            ],
        },
        headers=pub,
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["notify_events"] == ["completion"]
    assert body["reminders"][0]["offset_minutes"] == -30
    assert body["targets"][0]["target_type"] == "app_environment"

    deleted = client.delete(f"/api/v1/subscriptions/{created['id']}", headers=pub)
    assert deleted.status_code == 204


def test_multi_env_subscription(client):
    pub = auth_header(client, "publisher@test.example.com")
    e1 = _env(client, pub, key="DEV", name="Development", sort_order=1)
    e2 = _env(client, pub, key="QA", name="QA", sort_order=2)
    app = client.post(
        "/api/v1/applications",
        json={
            "key": "multi",
            "name": "Multi Env App",
            "environments": [
                {"environment_id": e1["id"], "display_name": "Multi-DEV"},
                {"environment_id": e2["id"], "display_name": "Multi-QA"},
            ],
        },
        headers=pub,
    ).json()
    created = client.post(
        "/api/v1/subscriptions",
        json={
            "destination_type": "email_address",
            "destination": "multi@example.com",
            "targets": [
                {"target_type": "app_environment", "target_id": f"{app['id']}:{e1['id']}"},
                {"target_type": "app_environment", "target_id": f"{app['id']}:{e2['id']}"},
            ],
            "reminders": [{"offset_minutes": -1440}],
        },
        headers=pub,
    )
    assert created.status_code == 201, created.text
    assert len(created.json()["targets"]) == 2


def test_ics_download_authenticated_and_scoped(client):
    pub = auth_header(client, "publisher@test.example.com")
    env = _env(client, pub)
    app = _app(client, pub, env["id"], key="ics-dl", name="ICS Download App")
    client.put("/api/v1/me/favorites", json={"application_ids": [app["id"]]}, headers=pub)
    now = datetime.now(timezone.utc)
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Downloadable Window",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=2)).isoformat(),
            "ends_at": (now + timedelta(hours=3)).isoformat(),
            "timezone": "America/Chicago",
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

    forbidden = client.get("/api/v1/calendar/download.ics")
    assert forbidden.status_code == 401

    feed = client.get("/api/v1/calendar/download.ics", headers=pub)
    assert feed.status_code == 200
    assert "BEGIN:VCALENDAR" in feed.text
    assert "Downloadable Window" in feed.text
    assert feed.headers["content-disposition"].endswith('filename="maintenancehub-calendar.ics"')


def test_calendar_reachability_localhost_not_microsoft_cloud(client, monkeypatch):
    pub = auth_header(client, "publisher@test.example.com")
    from maintenancehub_api.config import get_settings

    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    get_settings.cache_clear()
    res = client.get("/api/v1/calendar/reachability", headers=pub)
    assert res.status_code == 200
    body = res.json()
    assert body["microsoft_cloud_reachable"] is False
    assert body["subscription_supported"] is False
    assert "Microsoft cloud" in body["message"] or "localhost" in body["message"].lower()
    get_settings.cache_clear()


def test_calendar_reachability_https_ok(client, monkeypatch):
    pub = auth_header(client, "publisher@test.example.com")
    from maintenancehub_api.config import get_settings

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://maintenancehub.example.com")
    get_settings.cache_clear()
    body = client.get("/api/v1/calendar/reachability", headers=pub).json()
    assert body["microsoft_cloud_reachable"] is True
    assert body["subscription_supported"] is True
    get_settings.cache_clear()


def test_ics_token_still_works_with_app_environment_scope(client):
    pub = auth_header(client, "publisher@test.example.com")
    env = _env(client, pub, key="UAT", name="UAT", sort_order=4)
    app = _app(client, pub, env["id"], key="scoped-ics", name="Scoped ICS")
    client.post(
        "/api/v1/subscriptions",
        json={
            "destination_type": "email_address",
            "destination": "scoped@example.com",
            "targets": [
                {"target_type": "app_environment", "target_id": f"{app['id']}:{env['id']}"}
            ],
            "reminders": [{"offset_minutes": -60}],
        },
        headers=pub,
    )
    now = datetime.now(timezone.utc)
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Scoped Feed Event",
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
    token = client.post(
        "/api/v1/calendar-tokens",
        json={"scopes": ["subscriptions"], "label": "test"},
        headers=pub,
    ).json()
    assert token["reachability"]["code"]
    feed = client.get(f"/api/v1/public/ics/{token['token']}")
    assert feed.status_code == 200
    assert "Scoped Feed Event" in feed.text


def test_environment_catalog_create_edit_deactivate(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    created = client.post(
        "/api/v1/environments",
        json={
            "key": "perf",
            "name": "Performance",
            "description": "Load testing",
            "sort_order": 60,
        },
        headers=admin,
    )
    assert created.status_code == 201, created.text
    env = created.json()
    assert env["key"] == "PERF"
    assert env["is_active"] is True
    assert env["description"] == "Load testing"

    patched = client.patch(
        f"/api/v1/environments/{env['id']}",
        json={"name": "Perf Lab", "sort_order": 65},
        headers=admin,
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Perf Lab"

    # Publisher cannot deactivate
    denied = client.post(f"/api/v1/environments/{env['id']}/deactivate", headers=pub)
    assert denied.status_code == 403

    deactivated = client.post(f"/api/v1/environments/{env['id']}/deactivate", headers=admin)
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    active_only = client.get("/api/v1/environments", headers=admin).json()
    assert all(e["id"] != env["id"] for e in active_only)

    with_inactive = client.get(
        "/api/v1/environments?include_inactive=true", headers=admin
    ).json()
    assert any(e["id"] == env["id"] and e["is_active"] is False for e in with_inactive)


def test_dependency_summary_cross_env_friendly(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    env_dev = _env(client, pub, key="DEV", name="Development", sort_order=1)
    env_int = _env(client, pub, key="INT2", name="Integration", sort_order=2)
    consumer = _app(client, pub, env_dev["id"], key="claims-x", name="Claims")
    provider = _app(client, pub, env_int["id"], key="member-x", name="Member API")

    created = client.post(
        "/api/v1/admin/dependencies",
        json={
            "from_type": "application",
            "from_id": consumer["id"],
            "to_type": "application",
            "to_id": provider["id"],
            "from_environment_id": env_dev["id"],
            "to_environment_id": env_int["id"],
            "dependency_kind": "depends_on",
        },
        headers=admin,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert "Claims" in body["summary"]
    assert "Member API" in body["summary"]
    assert "depends on" in body["summary"]
    assert body["cross_environment"] is True
    assert "provider is affected" in body["description"].lower()

    listed = client.get("/api/v1/admin/dependencies", headers=admin).json()
    match = next(d for d in listed if d["id"] == body["id"])
    assert "→ depends on →" in match["summary"]
