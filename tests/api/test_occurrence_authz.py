"""Two publishers, non-overlapping grants — occurrence authz boundaries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from maintenancehub_api.auth.security import hash_password
from maintenancehub_api.models import Role, RoleName, User, UserRole
from tests.conftest import auth_header


def _publisher2(db_session) -> User:
    role = db_session.query(Role).filter(Role.name == RoleName.publisher).one()
    u = User(
        email="publisher-b@test.example.com",
        display_name="Publisher B",
        password_hash=hash_password("password123"),
        is_active=True,
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(UserRole(user_id=u.id, role_id=role.id))
    db_session.commit()
    return u


def test_two_publishers_non_overlapping_occurrence_authz(client, db_session):
    admin = auth_header(client, "admin@test.example.com")
    pub_a = auth_header(client, "publisher@test.example.com")
    _publisher2(db_session)
    pub_b = auth_header(client, "publisher-b@test.example.com")

    env = client.post(
        "/api/v1/environments",
        json={"key": "PROD", "name": "Production", "sort_order": 1},
        headers=admin,
    ).json()
    claims = client.post(
        "/api/v1/applications",
        json={
            "key": "claims-a",
            "name": "Claims A",
            "environments": [{"environment_id": env["id"], "display_name": "Claims-PROD"}],
        },
        headers=pub_a,
    ).json()
    billing = client.post(
        "/api/v1/applications",
        json={
            "key": "billing-b",
            "name": "Billing B",
            "environments": [{"environment_id": env["id"], "display_name": "Billing-PROD"}],
        },
        headers=pub_b,
    ).json()

    starts = datetime(2031, 2, 3, 10, 0, tzinfo=timezone.utc)
    # Pub A owns Claims series
    series = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Claims maintenance",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": claims["id"],
                    "environment_id": env["id"],
                }
            ],
            "recurrence": {"freq": "WEEKLY", "count": 4},
        },
        headers=pub_a,
    )
    assert series.status_code == 201, series.text
    eid = series.json()["id"]
    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        params={"from": starts.isoformat(), "to": (starts + timedelta(days=21)).isoformat()},
        headers=pub_a,
    ).json()
    orig = occs[0]["original_starts_at"]

    # Pub B cannot lifecycle unowned Claims occurrence
    denied = client.post(
        f"/api/v1/events/{eid}/occurrences/transition",
        json={"original_starts_at": orig, "status": "in_progress"},
        headers=pub_b,
    )
    assert denied.status_code == 403

    # Pub A can lifecycle own occurrence
    assert (
        client.post(
            f"/api/v1/events/{eid}/occurrences/transition",
            json={"original_starts_at": orig, "status": "in_progress"},
            headers=pub_a,
        ).status_code
        == 200
    )

    # Pub A may propose Billing as downstream impact (retains Claims)
    propose = client.patch(
        f"/api/v1/events/{eid}/occurrences",
        json={
            "original_starts_at": orig,
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": claims["id"],
                    "environment_id": env["id"],
                },
                {
                    "target_type": "application",
                    "target_id": billing["id"],
                    "environment_id": env["id"],
                },
            ],
        },
        headers=pub_a,
    )
    assert propose.status_code == 200, propose.text

    # Pub A cannot reassign solely to Billing (modifying another app's state)
    reassign = client.patch(
        f"/api/v1/events/{eid}/occurrences",
        json={
            "original_starts_at": orig,
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": billing["id"],
                    "environment_id": env["id"],
                }
            ],
        },
        headers=pub_a,
    )
    assert reassign.status_code == 403

    # Pub B still cannot lifecycle — effective impacts include Claims (needs all apps)
    # After propose, effective has Claims+Billing — Pub A has Claims but not Billing,
    # so lifecycle now requires both grants under ensure_lifecycle_access.
    # Reset to Claims-only via admin to keep Pub A able to finish; Pub B remains denied.
    assert (
        client.patch(
            f"/api/v1/events/{eid}/occurrences",
            json={
                "original_starts_at": orig,
                "impacts": [
                    {
                        "target_type": "application",
                        "target_id": claims["id"],
                        "environment_id": env["id"],
                    }
                ],
            },
            headers=admin,
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/events/{eid}/occurrences/transition",
            json={"original_starts_at": orig, "status": "verifying"},
            headers=pub_b,
        ).status_code
        == 403
    )

    # Billing-only series owned by Pub B — Pub A cannot touch
    other = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Billing only",
            "approval_state": "confirmed_scheduled",
            "starts_at": (starts + timedelta(days=1)).isoformat(),
            "ends_at": (starts + timedelta(days=1, hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": billing["id"],
                    "environment_id": env["id"],
                }
            ],
        },
        headers=pub_b,
    )
    assert other.status_code == 201
    oid = other.json()["id"]
    assert (
        client.post(
            f"/api/v1/events/{oid}/transition",
            json={"status": "in_progress"},
            headers=pub_a,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/events/{oid}/transition",
            json={"status": "in_progress"},
            headers=pub_b,
        ).status_code
        == 200
    )
