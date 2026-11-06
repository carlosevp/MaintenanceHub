"""M16 — consumer homepage/calendar/status + subscription targets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import auth_header

from maintenancehub_api.models import (
    Application,
    ApprovalState,
    CatalogStatus,
    Environment,
    EventImpact,
    EventKind,
    EventStatus,
    Favorite,
    ImpactTargetType,
    MaintenanceEvent,
)


def _seed_app_event(db_session, *, status=EventStatus.scheduled, approval=ApprovalState.confirmed_scheduled):
    env = Environment(key="PROD", name="Production", sort_order=1)
    app = Application(key="claims", name="Claims", status=CatalogStatus.active)
    db_session.add_all([env, app])
    db_session.flush()
    now = datetime.now(timezone.utc)
    ev = MaintenanceEvent(
        kind=EventKind.planned_maintenance,
        title="Claims PROD window",
        status=status,
        approval_state=approval,
        starts_at=now + timedelta(hours=2),
        ends_at=now + timedelta(hours=4),
        timezone="America/Chicago",
        expected_impact="Brief read-only",
        created_by=db_session.publisher.id,
    )
    db_session.add(ev)
    db_session.flush()
    db_session.add(
        EventImpact(
            event_id=ev.id,
            target_type=ImpactTargetType.application,
            target_id=app.id,
            environment_id=env.id,
        )
    )
    db_session.add(Favorite(user_id=db_session.viewer.id, application_id=app.id))
    db_session.commit()
    return app, env, ev


def test_dashboard_extended_cancelled_search_and_note(client, db_session):
    app, env, _ev = _seed_app_event(db_session)
    now = datetime.now(timezone.utc)
    cancelled = MaintenanceEvent(
        kind=EventKind.planned_maintenance,
        title="Cancelled Claims work",
        status=EventStatus.cancelled,
        approval_state=ApprovalState.confirmed_scheduled,
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, hours=2),
        timezone="UTC",
        created_by=db_session.publisher.id,
    )
    db_session.add(cancelled)
    db_session.flush()
    db_session.add(
        EventImpact(
            event_id=cancelled.id,
            target_type=ImpactTargetType.application,
            target_id=app.id,
            environment_id=env.id,
        )
    )
    extended = MaintenanceEvent(
        kind=EventKind.manual_outage,
        title="Claims extended outage",
        status=EventStatus.extended,
        approval_state=ApprovalState.confirmed_scheduled,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=1),
        timezone="UTC",
        created_by=db_session.publisher.id,
    )
    db_session.add(extended)
    db_session.flush()
    db_session.add(
        EventImpact(
            event_id=extended.id,
            target_type=ImpactTargetType.application,
            target_id=app.id,
            environment_id=env.id,
        )
    )
    db_session.commit()

    headers = auth_header(client, "viewer@test.example.com")
    r = client.get(
        "/api/v1/dashboard/summary?favorites_only=true&q=Claims",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "note" in body
    assert body["cancelled"]["count"] >= 1
    assert body["extended"]["count"] >= 1
    titles = [i["title"] for i in body["upcoming"]["items"]] + [
        i["title"] for i in body["cancelled"]["items"]
    ]
    assert any("Claims" in t for t in titles)


def test_calendar_agenda_and_favorites_filter(client, db_session):
    _seed_app_event(db_session)
    headers = auth_header(client, "viewer@test.example.com")
    now = datetime.now(timezone.utc)
    r = client.get(
        "/api/v1/calendar/events",
        params={
            "view": "agenda",
            "from": (now - timedelta(days=1)).isoformat(),
            "to": (now + timedelta(days=14)).isoformat(),
            "favorites_only": "true",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert any(e["title"] == "Claims PROD window" for e in r.json())


def test_status_application_and_event_and_scheduled(client, db_session):
    app, env, ev = _seed_app_event(db_session)
    headers = auth_header(client, "viewer@test.example.com")

    r = client.get(
        f"/api/v1/status/applications/{app.key}",
        params={"environment_key": env.key},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["application"]["key"] == "claims"
    assert body["environment"]["key"] == "PROD"
    assert "active" in body and "upcoming_confirmed" in body
    assert "approved_window_not_confirmed" in body
    assert "never" in body["note"].lower()

    r2 = client.get(f"/api/v1/status/events/{ev.id}", headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == ev.id

    r3 = client.get(f"/api/v1/status/scheduled/{ev.id}", headers=headers)
    assert r3.status_code == 200, r3.text
    assert r3.json()["view"] == "scheduled"
    assert r3.json()["share_path"].endswith(f"/status/scheduled/{ev.id}")


def test_status_requires_auth(client, db_session):
    app, _, ev = _seed_app_event(db_session)
    assert client.get(f"/api/v1/status/applications/{app.key}").status_code == 401
    assert client.get(f"/api/v1/status/events/{ev.id}").status_code == 401


def test_subscription_app_environment_multi_reminder(client, db_session):
    app, env, _ = _seed_app_event(db_session)
    headers = auth_header(client, "viewer@test.example.com")
    r = client.post(
        "/api/v1/subscriptions",
        headers=headers,
        json={
            "destination_type": "email_address",
            "destination": "viewer@test.example.com",
            "targets": [
                {"target_type": "app_environment", "target_id": f"{app.id}:{env.id}"},
            ],
            "reminders": [
                {"offset_minutes": -1440},
                {"offset_minutes": -60},
                {"offset_minutes": -15},
            ],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["reminders"]) == 3
    assert body["targets"][0]["target_type"] == "app_environment"


def test_templates_include_detail_and_approval_label():
    from maintenancehub_api.domain.templates import DEFAULT_TEMPLATES, approval_label

    created = DEFAULT_TEMPLATES["event.created"]
    assert "{detail_url}" in created["body"]
    assert "{approval_label}" in created["subject"] or "{approval_label}" in created["body"]
    assert approval_label("confirmed_scheduled") != approval_label("approved_window")
