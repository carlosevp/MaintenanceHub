from datetime import datetime, timedelta, timezone

from tests.conftest import auth_header


def _create_env(client, headers):
    res = client.post(
        "/api/v1/environments",
        json={"key": "DEV", "name": "Development", "sort_order": 1},
        headers=headers,
    )
    # admin/publisher may create; if already exists from parallel, ok
    if res.status_code == 201:
        return res.json()
    # try list
    envs = client.get("/api/v1/environments", headers=headers).json()
    return envs[0]


def test_viewer_cannot_create_application(client):
    headers = auth_header(client, "viewer@test.example.com")
    res = client.post(
        "/api/v1/applications",
        json={"key": "x", "name": "X", "environments": []},
        headers=headers,
    )
    assert res.status_code == 403


def test_publisher_can_create_app_with_two_envs(client):
    pub = auth_header(client, "publisher@test.example.com")
    admin = auth_header(client, "admin@test.example.com")

    e1 = client.post(
        "/api/v1/environments",
        json={"key": "QA", "name": "QA", "sort_order": 2},
        headers=admin,
    ).json()
    e2 = client.post(
        "/api/v1/environments",
        json={"key": "PROD", "name": "Production", "sort_order": 3},
        headers=admin,
    ).json()

    res = client.post(
        "/api/v1/applications",
        json={
            "key": "billing",
            "name": "Billing",
            "environments": [
                {"environment_id": e1["id"], "display_name": "Billing-QA"},
                {"environment_id": e2["id"], "display_name": "Billing-Live"},
            ],
        },
        headers=pub,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert len(body["environments"]) == 2
    names = {ae["display_name"] for ae in body["environments"]}
    assert names == {"Billing-QA", "Billing-Live"}


def test_manual_dependency_origin_preserved(client):
    pub = auth_header(client, "publisher@test.example.com")
    admin = auth_header(client, "admin@test.example.com")
    app_a = client.post(
        "/api/v1/applications",
        json={"key": "a", "name": "A", "environments": []},
        headers=pub,
    ).json()
    app_b = client.post(
        "/api/v1/applications",
        json={"key": "b", "name": "B", "environments": []},
        headers=pub,
    ).json()
    dep = client.post(
        f"/api/v1/applications/{app_a['id']}/dependencies",
        json={"to_type": "application", "to_id": app_b["id"], "dependency_kind": "depends_on"},
        headers=pub,
    )
    assert dep.status_code == 201, dep.text
    assert dep.json()["origin"] == "manual"

    # re-list (no-op re-save path) — origin still manual
    listed = client.get(
        f"/api/v1/applications/{app_a['id']}/dependencies",
        headers=auth_header(client, "viewer@test.example.com"),
    )
    assert listed.status_code == 200
    assert listed.json()[0]["origin"] == "manual"
    assert admin  # silence unused in some runners


def test_unauthenticated_denied(client):
    assert client.get("/api/v1/applications").status_code == 401
