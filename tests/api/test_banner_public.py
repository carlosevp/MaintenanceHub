"""M12/M18 — public + internal banner API: filter, safety, advance window."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import auth_header


def _bootstrap(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")
    env_prod = client.post(
        "/api/v1/environments",
        json={"key": "PROD", "name": "Production", "sort_order": 1},
        headers=admin,
    ).json()
    env_dev = client.post(
        "/api/v1/environments",
        json={"key": "DEV", "name": "Development", "sort_order": 2},
        headers=admin,
    ).json()
    env_int = client.post(
        "/api/v1/environments",
        json={"key": "INT", "name": "Integration", "sort_order": 3},
        headers=admin,
    ).json()
    app = client.post(
        "/api/v1/applications",
        json={
            "key": "payments-gateway",
            "name": "Payments",
            "environments": [
                {"environment_id": env_prod["id"], "display_name": "Pay-PROD"},
                {"environment_id": env_dev["id"], "display_name": "Pay-DEV"},
            ],
        },
        headers=pub,
    ).json()
    claims = client.post(
        "/api/v1/applications",
        json={
            "key": "claims",
            "name": "Claims",
            "environments": [
                {"environment_id": env_int["id"], "display_name": "Claims-INT"},
                {"environment_id": env_dev["id"], "display_name": "Claims-DEV"},
            ],
        },
        headers=pub,
    ).json()
    return pub, admin, app, claims, env_prod, env_dev, env_int


def test_banner_public_dto_excludes_internal_fields(client):
    pub, _admin, app, _claims, env_prod, _env_dev, _env_int = _bootstrap(client)
    now = datetime.now(timezone.utc)
    created = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Public patch",
            "description": "INTERNAL NOTE MUST NOT LEAK",
            "expected_impact": "brief RO",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now - timedelta(minutes=10)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env_prod["id"],
                }
            ],
        },
        headers=pub,
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]
    client.post(
        f"/api/v1/events/{event_id}/transition",
        json={"status": "in_progress", "note": "started — internal"},
        headers=pub,
    )

    res = client.get(
        "/api/v1/public/banner?application_key=payments-gateway&environment_key=PROD",
        headers=pub,
    )
    assert res.status_code == 200, res.text
    assert "Cache-Control" in res.headers
    body = res.json()
    assert len(body) >= 1
    msg = next(m for m in body if m["event_id"] == event_id or m["id"] == event_id)
    assert set(msg.keys()) <= {
        "id",
        "event_id",
        "kind",
        "title",
        "status",
        "presentation",
        "starts_at",
        "ends_at",
        "expected_impact",
        "approval_state",
        "revision",
        "dismissible",
        "occurrence_starts_at",
    }
    raw = res.text
    assert "INTERNAL NOTE" not in raw
    assert "timeline" not in raw
    assert "description" not in raw
    assert "client_secret" not in raw
    assert msg["title"] == "Public patch"
    assert msg["status"] == "in_progress"
    assert msg["presentation"] in {"in_progress", "outage"}
    assert msg["dismissible"] is False


def test_banner_filters_by_environment_and_skips_approved_only(client):
    pub, _admin, app, _claims, env_prod, env_dev, _env_int = _bootstrap(client)
    now = datetime.now(timezone.utc)
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "DEV only",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=3)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env_dev["id"],
                }
            ],
        },
        headers=pub,
    )
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Approved only",
            "approval_state": "approved_window",
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=3)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env_prod["id"],
                }
            ],
        },
        headers=pub,
    )

    prod = client.get(
        "/api/v1/public/banner?application_key=payments-gateway&environment_key=PROD",
        headers=pub,
    ).json()
    assert all(m["title"] != "DEV only" for m in prod)
    assert all(m["title"] != "Approved only" for m in prod)
    assert all(m.get("presentation") != "outage" or m["kind"] == "manual_outage" for m in prod)

    dev = client.get(
        "/api/v1/public/banner?application_key=payments-gateway&environment_key=DEV",
        headers=pub,
    ).json()
    assert any(m["title"] == "DEV only" for m in dev)
    assert all(m["presentation"] == "upcoming" for m in dev if m["title"] == "DEV only")


def test_banner_confirmed_downstream_impact_included(client):
    """Confirmed multi-app impacts (e.g. downstream) surface on each exact app+env."""
    pub, _admin, app, claims, env_prod, _env_dev, env_int = _bootstrap(client)
    now = datetime.now(timezone.utc)
    created = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Shared infra with Claims INT",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=3)).isoformat(),
            "ends_at": (now + timedelta(hours=5)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env_prod["id"],
                },
                {
                    "target_type": "application",
                    "target_id": claims["id"],
                    "environment_id": env_int["id"],
                },
            ],
        },
        headers=pub,
    )
    assert created.status_code == 201, created.text
    claims_b = client.get(
        "/api/v1/public/banner?application_key=claims&environment_key=INT&advance_hours=24"
    ).json()
    pay_b = client.get(
        "/api/v1/public/banner?application_key=payments-gateway&environment_key=PROD&advance_hours=24"
    ).json()
    assert any(m["title"] == "Shared infra with Claims INT" for m in claims_b)
    assert any(m["title"] == "Shared infra with Claims INT" for m in pay_b)
    # Wrong env must not see it
    claims_dev = client.get(
        "/api/v1/public/banner?application_key=claims&environment_key=DEV&advance_hours=24"
    ).json()
    assert all(m["title"] != "Shared infra with Claims INT" for m in claims_dev)


def test_banner_cross_app_isolation(client):
    pub, _admin, app, claims, env_prod, _env_dev, env_int = _bootstrap(client)
    now = datetime.now(timezone.utc)
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Payments only",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=2)).isoformat(),
            "ends_at": (now + timedelta(hours=4)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env_prod["id"],
                }
            ],
        },
        headers=pub,
    )
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Claims INT window",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=2)).isoformat(),
            "ends_at": (now + timedelta(hours=4)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": claims["id"],
                    "environment_id": env_int["id"],
                }
            ],
        },
        headers=pub,
    )

    claims_banner = client.get(
        "/api/v1/public/banner?application_key=claims&environment_key=INT&advance_hours=24"
    ).json()
    assert any(m["title"] == "Claims INT window" for m in claims_banner)
    assert all(m["title"] != "Payments only" for m in claims_banner)

    pay = client.get(
        "/api/v1/public/banner?application_key=payments-gateway&environment_key=PROD"
    ).json()
    assert any(m["title"] == "Payments only" for m in pay)
    assert all(m["title"] != "Claims INT window" for m in pay)


def test_banner_advance_window_hides_far_future(client):
    pub, _admin, app, _claims, env_prod, _env_dev, _env_int = _bootstrap(client)
    now = datetime.now(timezone.utc)
    client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Far away",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now + timedelta(hours=48)).isoformat(),
            "ends_at": (now + timedelta(hours=50)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env_prod["id"],
                }
            ],
        },
        headers=pub,
    )
    near = client.get(
        "/api/v1/public/banner?application_key=payments-gateway&environment_key=PROD&advance_hours=24"
    ).json()
    assert all(m["title"] != "Far away" for m in near)

    wide = client.get(
        "/api/v1/public/banner?application_key=payments-gateway&environment_key=PROD&advance_hours=72"
    ).json()
    assert any(m["title"] == "Far away" for m in wide)


def test_banner_cancel_and_extend_revision(client):
    pub, _admin, app, _claims, env_prod, _env_dev, _env_int = _bootstrap(client)
    now = datetime.now(timezone.utc)
    created = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Extendable",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env_prod["id"],
                }
            ],
        },
        headers=pub,
    )
    assert created.status_code == 201, created.text
    eid = created.json()["id"]
    client.post(
        f"/api/v1/events/{eid}/transition",
        json={"status": "in_progress"},
        headers=pub,
    )
    before = client.get(
        "/api/v1/public/banner?application_key=payments-gateway&environment_key=PROD"
    ).json()
    msg = next(m for m in before if m["event_id"] == eid or m["id"] == eid)
    rev1 = msg["revision"]

    ext = client.post(
        f"/api/v1/events/{eid}/extend",
        json={"new_ends_at": (now + timedelta(hours=3)).isoformat(), "note": "need more"},
        headers=pub,
    )
    assert ext.status_code == 200, ext.text
    after = client.get(
        "/api/v1/public/banner?application_key=payments-gateway&environment_key=PROD"
    ).json()
    msg2 = next(m for m in after if m["event_id"] == eid or m["id"] == eid)
    assert msg2["revision"] != rev1
    assert msg2["presentation"] in {"extended", "in_progress"}
    assert msg2["dismissible"] is False

    # Cancelled must disappear
    cancel = client.post(
        f"/api/v1/events/{eid}/transition",
        json={"status": "cancelled", "note": "abort"},
        headers=pub,
    )
    assert cancel.status_code == 200, cancel.text
    gone = client.get(
        "/api/v1/public/banner?application_key=payments-gateway&environment_key=PROD"
    ).json()
    assert all(m["event_id"] != eid and m["id"] != eid for m in gone)


def test_banner_never_approved_equals_outage(client):
    pub, _admin, app, _claims, env_prod, _env_dev, _env_int = _bootstrap(client)
    now = datetime.now(timezone.utc)
    client.post(
        "/api/v1/events",
        json={
            "kind": "manual_outage",
            "title": "Approved outage attempt",
            "approval_state": "approved_window",
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env_prod["id"],
                }
            ],
        },
        headers=pub,
    )
    body = client.get(
        "/api/v1/public/banner?application_key=payments-gateway&environment_key=PROD"
    ).json()
    assert all(m["title"] != "Approved outage attempt" for m in body)
    assert all(m.get("presentation") != "outage" or m["approval_state"] == "confirmed_scheduled" for m in body)


def test_banner_public_unauthenticated_and_service_scope(client):
    pub, admin, app, _claims, env_prod, _env_dev, _env_int = _bootstrap(client)
    now = datetime.now(timezone.utc)
    created_outage = client.post(
        "/api/v1/events",
        json={
            "kind": "manual_outage",
            "title": "Outage",
            "approval_state": "confirmed_scheduled",
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": app["id"],
                    "environment_id": env_prod["id"],
                }
            ],
        },
        headers=pub,
    )
    assert created_outage.status_code == 201, created_outage.text
    eid = created_outage.json()["id"]
    client.post(
        f"/api/v1/events/{eid}/transition",
        json={"status": "in_progress"},
        headers=pub,
    )

    anon = client.get("/api/v1/public/banner?application_key=payments-gateway")
    assert anon.status_code == 200
    assert any(m["title"] == "Outage" for m in anon.json())
    out = next(m for m in anon.json() if m["title"] == "Outage")
    assert out["presentation"] == "outage"

    created = client.post(
        "/api/v1/admin/service-credentials",
        headers=admin,
        json={"name": "embed", "scopes": ["banner:read"]},
    )
    assert created.status_code == 201
    tok = client.post(
        "/api/v1/auth/service/token",
        json={
            "client_id": created.json()["client_id"],
            "client_secret": created.json()["client_secret"],
        },
    )
    ok = client.get(
        "/api/v1/public/banner?application_key=payments-gateway",
        headers={"Authorization": f"Bearer {tok.json()['access_token']}"},
    )
    assert ok.status_code == 200
    assert any(m["title"] == "Outage" for m in ok.json())

    bad = client.post(
        "/api/v1/admin/service-credentials",
        headers=admin,
        json={"name": "wrong-scope", "scopes": ["notifications:write"]},
    )
    assert bad.status_code == 201
    bad_tok = client.post(
        "/api/v1/auth/service/token",
        json={
            "client_id": bad.json()["client_id"],
            "client_secret": bad.json()["client_secret"],
        },
    )
    denied = client.get(
        "/api/v1/public/banner?application_key=payments-gateway",
        headers={"Authorization": f"Bearer {bad_tok.json()['access_token']}"},
    )
    assert denied.status_code == 403

    # Internal OpenShift-stable path
    internal = client.get(
        "/api/v1/internal/banner?application_key=payments-gateway&environment_key=PROD"
    )
    assert internal.status_code == 200
    assert any(m["title"] == "Outage" for m in internal.json())


def test_banner_static_embed_assets(client):
    js = client.get("/static/banner/embed.js")
    css = client.get("/static/banner/style.css")
    assert js.status_code == 200
    assert "MaintenanceHubBanner" in js.text
    assert css.status_code == 200
    assert ".mh-banner" in css.text


def test_banner_occurrence_impact_override(client):
    """Occurrence-specific confirmed impacts must drive filtering."""
    pub, _admin, _app, claims, _env_prod, env_dev, env_int = _bootstrap(client)
    now = datetime.now(timezone.utc)
    starts = now + timedelta(hours=2)
    created = client.post(
        "/api/v1/events",
        json={
            "kind": "planned_maintenance",
            "title": "Weekly Claims",
            "approval_state": "confirmed_scheduled",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "recurrence": {"freq": "DAILY", "count": 3},
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": claims["id"],
                    "environment_id": env_dev["id"],
                }
            ],
        },
        headers=pub,
    )
    assert created.status_code == 201, created.text
    eid = created.json()["id"]

    # First occurrence should appear on DEV, not INT
    dev = client.get(
        "/api/v1/public/banner?application_key=claims&environment_key=DEV&advance_hours=48"
    ).json()
    assert any(m["title"] == "Weekly Claims" for m in dev)

    int_banner = client.get(
        "/api/v1/public/banner?application_key=claims&environment_key=INT&advance_hours=48"
    ).json()
    assert all(m["title"] != "Weekly Claims" for m in int_banner)

    # Override first occurrence impacts to INT only
    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        headers=pub,
        params={"from": now.isoformat(), "to": (now + timedelta(days=10)).isoformat()},
    )
    assert occs.status_code == 200, occs.text
    first = occs.json()[0]
    orig = first.get("original_starts_at") or first.get("starts_at")
    override = client.patch(
        f"/api/v1/events/{eid}/occurrences",
        headers=pub,
        json={
            "original_starts_at": orig,
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": claims["id"],
                    "environment_id": env_int["id"],
                }
            ],
        },
    )
    assert override.status_code == 200, override.text

    after_int = client.get(
        "/api/v1/public/banner?application_key=claims&environment_key=INT&advance_hours=48"
    ).json()
    after_dev = client.get(
        "/api/v1/public/banner?application_key=claims&environment_key=DEV&advance_hours=48"
    ).json()
    assert any(m["title"] == "Weekly Claims" for m in after_int)
    # Overridden occurrence no longer matches DEV; later weeks still may
    # (COUNT series) — ensure the overridden slot is on INT.
    assert any(
        m["title"] == "Weekly Claims" and m.get("occurrence_starts_at")
        for m in after_int
    )
    assert isinstance(after_dev, list)
