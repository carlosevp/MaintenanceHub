"""M14 impact analysis preview / confirm / authz / conflicts / no side-effects."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from maintenancehub_api.models import (
    ApplicationGrant,
    Dependency,
    InfraComponent,
    Job,
    NotificationDelivery,
    OutboxEvent,
    RoleName,
    Subscription,
    SubscriptionTarget,
)
from tests.conftest import auth_header


def _catalog(client, admin, *, with_oracle=True):
    envs = {}
    for key, order in (("DEV", 1), ("INT", 2), ("QA", 3), ("NON-PROD", 4), ("PROD", 5)):
        envs[key] = client.post(
            "/api/v1/environments",
            json={"key": key, "name": key, "sort_order": order},
            headers=admin,
        ).json()

    apps = {}
    for key, env_keys in (
        ("claims", ["INT", "DEV"]),
        ("billing", ["DEV"]),
        ("member-api", ["QA"]),
        ("portal-bff", ["QA"]),
        ("lonely", ["PROD"]),
    ):
        apps[key] = client.post(
            "/api/v1/applications",
            json={
                "key": key,
                "name": key.title(),
                "environments": [
                    {"environment_id": envs[e]["id"], "display_name": f"{key}-{e}"}
                    for e in env_keys
                ],
            },
            headers=admin,
        ).json()

    oracle = None
    if with_oracle:
        db: Session = client.db
        oracle = InfraComponent(
            key="oracle-shared-nonprod",
            name="Oracle NON-PROD",
            kind="database",
        )
        db.add(oracle)
        db.flush()
        # Consumers → Oracle + transitive portal → member
        for frm, fenv, origin in (
            ("claims", "INT", "import"),
            ("billing", "DEV", "import"),
            ("member-api", "QA", "manual"),
        ):
            db.add(
                Dependency(
                    from_type="application",
                    from_id=apps[frm]["id"],
                    to_type="infra_component",
                    to_id=oracle.id,
                    from_environment_id=envs[fenv]["id"],
                    to_environment_id=envs["NON-PROD"]["id"],
                    dependency_kind="depends_on",
                    origin=origin,
                )
            )
        db.add(
            Dependency(
                from_type="application",
                from_id=apps["portal-bff"]["id"],
                to_type="application",
                to_id=apps["member-api"]["id"],
                from_environment_id=envs["QA"]["id"],
                to_environment_id=envs["QA"]["id"],
                dependency_kind="depends_on",
                origin="manual",
            )
        )
        db.commit()
        db.refresh(oracle)
    return apps, envs, oracle


def _grant_publisher(client, app_id: str):
    db: Session = client.db
    pub = db.publisher
    existing = (
        db.query(ApplicationGrant)
        .filter(
            ApplicationGrant.user_id == pub.id,
            ApplicationGrant.application_id == app_id,
        )
        .first()
    )
    if not existing:
        db.add(
            ApplicationGrant(
                user_id=pub.id,
                application_id=app_id,
                role=RoleName.publisher.value,
            )
        )
        db.commit()


def _window(hours=2, offset_h=24):
    now = datetime.now(timezone.utc)
    starts = (now + timedelta(hours=offset_h)).replace(minute=0, second=0, microsecond=0)
    return starts, starts + timedelta(hours=hours)


def test_preview_direct_transitive_audience_and_read_only(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    apps, envs, oracle = _catalog(client, admin)
    starts, ends = _window()

    # Subscriptions with app+env pairs
    db: Session = client.db
    for email, app_key, env_key in (
        ("claims@x.com", "claims", "INT"),
        ("billing@x.com", "billing", "DEV"),
        ("member@x.com", "member-api", "QA"),
        ("dup@x.com", "claims", "INT"),
    ):
        sub = Subscription(
            user_id=db.publisher.id,
            destination_type="email_address",
            destination=email,
            is_active=True,
        )
        db.add(sub)
        db.flush()
        db.add(
            SubscriptionTarget(
                subscription_id=sub.id,
                target_type="app_environment",
                target_id=f"{apps[app_key]['id']}:{envs[env_key]['id']}",
            )
        )
    # Wrong pair should not match Claims INT impact
    sub_wrong = Subscription(
        user_id=db.publisher.id,
        destination_type="email_address",
        destination="claims-dev-wrong-pair@x.com",
        is_active=True,
    )
    db.add(sub_wrong)
    db.flush()
    db.add(
        SubscriptionTarget(
            subscription_id=sub_wrong.id,
            target_type="app_environment",
            target_id=f"{apps['claims']['id']}:{envs['DEV']['id']}",
        )
    )
    db.commit()

    jobs_before = db.query(Job).count()
    outbox_before = db.query(OutboxEvent).count()
    deliveries_before = db.query(NotificationDelivery).count()

    res = client.post(
        "/api/v1/impact-analysis/preview",
        json={
            "seeds": [
                {
                    "target_type": "infra_component",
                    "target_id": oracle.id,
                    "environment_id": envs["NON-PROD"]["id"],
                }
            ],
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "max_depth": 5,
        },
        headers=pub,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["read_only"] is True
    assert body["notifications_sent"] is False
    assert body["revision_token"]
    down_ids = {s["target_id"] for s in body["suggested_downstream"]}
    assert apps["claims"]["id"] in down_ids
    assert apps["billing"]["id"] in down_ids
    assert apps["member-api"]["id"] in down_ids
    assert apps["portal-bff"]["id"] in down_ids  # transitive
    emails = set(body["audience"]["email_destinations"])
    assert "claims@x.com" in emails
    assert "claims-dev-wrong-pair@x.com" not in emails
    assert body["audience"]["unique_recipients"] >= 3

    assert db.query(Job).count() == jobs_before
    assert db.query(OutboxEvent).count() == outbox_before
    assert db.query(NotificationDelivery).count() == deliveries_before


def test_preview_exclusion_and_manual_addition(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    apps, envs, oracle = _catalog(client, admin)
    starts, ends = _window()
    res = client.post(
        "/api/v1/impact-analysis/preview",
        json={
            "seeds": [
                {
                    "target_type": "infra_component",
                    "target_id": oracle.id,
                    "environment_id": envs["NON-PROD"]["id"],
                }
            ],
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "exclusions": [
                {
                    "target_type": "application",
                    "target_id": apps["billing"]["id"],
                    "environment_id": envs["DEV"]["id"],
                    "reason": "Billing on different DB",
                }
            ],
            "manual_additions": [
                {
                    "target_type": "application",
                    "target_id": apps["lonely"]["id"],
                    "environment_id": envs["PROD"]["id"],
                }
            ],
        },
        headers=pub,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    billing = next(
        s
        for s in body["suggested_downstream"]
        if s["target_id"] == apps["billing"]["id"]
    )
    assert billing["selection"] == "excluded"
    eff_ids = {x["target_id"] for x in body["proposed_effective_impacts"]}
    assert apps["billing"]["id"] not in eff_ids
    assert apps["lonely"]["id"] in eff_ids


def test_confirm_publish_persists_decisions_and_outbox(client):
    admin = auth_header(client, "admin@test.example.com")
    apps, envs, oracle = _catalog(client, admin)
    starts, ends = _window()

    created = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Oracle patch",
            "approval_state": "approved_window",
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "infra_component",
                    "target_id": oracle.id,
                    "environment_id": envs["NON-PROD"]["id"],
                }
            ],
        },
        headers=admin,
    )
    assert created.status_code == 201, created.text
    event = created.json()

    preview = client.post(
        "/api/v1/impact-analysis/preview",
        json={
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "event_id": event["id"],
            "exclusions": [
                {
                    "target_type": "application",
                    "target_id": apps["billing"]["id"],
                    "environment_id": envs["DEV"]["id"],
                    "reason": "N/A",
                }
            ],
        },
        headers=admin,
    ).json()

    include = [
        {
            "target_type": s["target_type"],
            "target_id": s["target_id"],
            "environment_id": s.get("environment_id"),
        }
        for s in preview["suggested_downstream"]
        if s["target_id"] != apps["billing"]["id"]
    ]
    confirm = client.post(
        f"/api/v1/impact-analysis/events/{event['id']}/confirm",
        json={
            "revision_token": preview["revision_token"],
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "exclusions": [
                {
                    "target_type": "application",
                    "target_id": apps["billing"]["id"],
                    "environment_id": envs["DEV"]["id"],
                    "reason": "N/A",
                }
            ],
            "include_downstream": include,
            "publish": True,
        },
        headers=admin,
    )
    assert confirm.status_code == 200, confirm.text
    out = confirm.json()
    assert out["approval_state"] == "confirmed_scheduled"
    impact_ids = {i["target_id"] for i in out["impacts"]}
    assert oracle.id in impact_ids
    assert apps["claims"]["id"] in impact_ids
    assert apps["billing"]["id"] not in impact_ids

    db: Session = client.db
    assert db.query(OutboxEvent).filter(OutboxEvent.aggregate_id == event["id"]).count() >= 1
    from maintenancehub_api.models import ImpactDecision

    decisions = db.query(ImpactDecision).filter(ImpactDecision.event_id == event["id"]).all()
    assert any(d.decision == "excluded" for d in decisions)
    assert any(d.decision in ("included", "manual") for d in decisions)


def test_stale_revision_token_rejected(client):
    admin = auth_header(client, "admin@test.example.com")
    apps, envs, oracle = _catalog(client, admin)
    starts, ends = _window()
    event = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Stale token",
            "approval_state": "approved_window",
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "infra_component",
                    "target_id": oracle.id,
                    "environment_id": envs["NON-PROD"]["id"],
                }
            ],
        },
        headers=admin,
    ).json()
    preview = client.post(
        "/api/v1/impact-analysis/preview",
        json={
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "event_id": event["id"],
        },
        headers=admin,
    ).json()
    # Mutate dependency graph after preview
    db: Session = client.db
    db.add(
        Dependency(
            from_type="application",
            from_id=apps["lonely"]["id"],
            to_type="infra_component",
            to_id=oracle.id,
            from_environment_id=envs["PROD"]["id"],
            to_environment_id=envs["NON-PROD"]["id"],
            origin="manual",
        )
    )
    db.commit()
    bad = client.post(
        f"/api/v1/impact-analysis/events/{event['id']}/confirm",
        json={
            "revision_token": preview["revision_token"],
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "include_downstream": [],
            "publish": True,
        },
        headers=admin,
    )
    assert bad.status_code == 409, bad.text


def test_confirm_authz_seed_apps_required(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    apps, envs, _ = _catalog(client, admin, with_oracle=False)
    starts, ends = _window()
    # Admin creates event on claims — publisher has no grant
    event = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Claims only",
            "approval_state": "approved_window",
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": apps["claims"]["id"],
                    "environment_id": envs["INT"]["id"],
                }
            ],
        },
        headers=admin,
    ).json()
    preview = client.post(
        "/api/v1/impact-analysis/preview",
        json={
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "event_id": event["id"],
        },
        headers=pub,
    ).json()
    denied = client.post(
        f"/api/v1/impact-analysis/events/{event['id']}/confirm",
        json={
            "revision_token": preview["revision_token"],
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "include_downstream": [],
            "publish": True,
        },
        headers=pub,
    )
    assert denied.status_code == 403, denied.text

    _grant_publisher(client, apps["claims"]["id"])
    # Re-preview after grant (token still valid if graph unchanged)
    preview2 = client.post(
        "/api/v1/impact-analysis/preview",
        json={
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "event_id": event["id"],
        },
        headers=pub,
    ).json()
    ok = client.post(
        f"/api/v1/impact-analysis/events/{event['id']}/confirm",
        json={
            "revision_token": preview2["revision_token"],
            "seeds": event["impacts"],
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "include_downstream": [
                {
                    "target_type": "application",
                    "target_id": apps["billing"]["id"],
                    "environment_id": envs["DEV"]["id"],
                }
            ],
            "publish": True,
        },
        headers=pub,
    )
    # Downstream billing without grant is OK while retaining owned claims
    assert ok.status_code == 200, ok.text


def test_scheduling_conflict_advisory(client):
    admin = auth_header(client, "admin@test.example.com")
    apps, envs, oracle = _catalog(client, admin)
    starts, ends = _window(hours=3, offset_h=10)
    # Overlapping confirmed Claims maintenance
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Claims batch",
            "approval_state": "confirmed_scheduled",
            "starts_at": (starts + timedelta(minutes=30)).isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": apps["claims"]["id"],
                    "environment_id": envs["INT"]["id"],
                }
            ],
        },
        headers=admin,
    )
    preview = client.post(
        "/api/v1/impact-analysis/preview",
        json={
            "seeds": [
                {
                    "target_type": "infra_component",
                    "target_id": oracle.id,
                    "environment_id": envs["NON-PROD"]["id"],
                }
            ],
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
        },
        headers=admin,
    ).json()
    assert preview["conflicts"], preview
    assert any(c["classification"] in ("direct_overlap", "dependency_overlap") for c in preview["conflicts"])


def test_occurrence_override_preview_and_explicit_empty(client):
    admin = auth_header(client, "admin@test.example.com")
    apps, envs, oracle = _catalog(client, admin)
    starts, ends = _window(offset_h=48)
    event = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Recurring oracle",
            "approval_state": "approved_window",
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "infra_component",
                    "target_id": oracle.id,
                    "environment_id": envs["NON-PROD"]["id"],
                }
            ],
            "recurrence": {"freq": "WEEKLY", "interval": 1, "count": 3},
        },
        headers=admin,
    ).json()
    from_ = (starts - timedelta(hours=1)).isoformat()
    to = (starts + timedelta(days=28)).isoformat()
    occ_res = client.get(
        f"/api/v1/events/{event['id']}/occurrences",
        params={"from": from_, "to": to},
        headers=admin,
    )
    assert occ_res.status_code == 200, occ_res.text
    occs = occ_res.json()
    assert isinstance(occs, list), occs
    assert len(occs) >= 2, occs
    second = occs[1]
    # Occurrence-specific impacts: Claims INT only
    patched = client.patch(
        f"/api/v1/events/{event['id']}/occurrences",
        json={
            "original_starts_at": second["original_starts_at"],
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": apps["claims"]["id"],
                    "environment_id": envs["INT"]["id"],
                }
            ],
        },
        headers=admin,
    )
    assert patched.status_code == 200, patched.text

    preview = client.post(
        "/api/v1/impact-analysis/preview",
        json={
            "seeds": [
                {
                    "target_type": "application",
                    "target_id": apps["claims"]["id"],
                    "environment_id": envs["INT"]["id"],
                }
            ],
            "starts_at": second["starts_at"],
            "ends_at": second["ends_at"],
            "event_id": event["id"],
            "original_starts_at": second["original_starts_at"],
        },
        headers=admin,
    ).json()
    assert preview["direct_targets"][0]["target_id"] == apps["claims"]["id"]

    # Explicit empty occurrence impacts
    empty = client.patch(
        f"/api/v1/events/{event['id']}/occurrences",
        json={"original_starts_at": second["original_starts_at"], "impacts": []},
        headers=admin,
    )
    assert empty.status_code == 200, empty.text
    detail = empty.json()
    assert detail.get("impacts_overridden") is True or "impacts" in detail


def test_infra_list_endpoint(client):
    admin = auth_header(client, "admin@test.example.com")
    _catalog(client, admin)
    res = client.get("/api/v1/infra-components", headers=admin)
    assert res.status_code == 200
    keys = {r["key"] for r in res.json()}
    assert "oracle-shared-nonprod" in keys
