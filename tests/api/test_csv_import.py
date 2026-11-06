"""M10 — CSV preview/commit and manual dependency preservation."""

from __future__ import annotations

import io

from tests.conftest import auth_header


CI_CSV = """sys_id,name,short_description,description
ci-100,payments-ci,Payments CI,Imported CI
ci-200,hr-ci,HR CI,Another CI
"""

REL_CSV = """parent_sys_id,child_sys_id,type
ci-100,ci-200,depends_on
"""


def test_csv_preview_and_commit_idempotent(client):
    admin = auth_header(client, "admin@test.example.com")
    up = client.post(
        "/api/v1/admin/imports/csv",
        headers=admin,
        data={"kind": "cmdb_ci"},
        files={"file": ("cis.csv", io.BytesIO(CI_CSV.encode()), "text/csv")},
    )
    assert up.status_code == 200, up.text
    job_id = up.json()["id"]

    preview = client.post(f"/api/v1/admin/imports/{job_id}/preview", headers=admin)
    assert preview.status_code == 200
    body = preview.json()
    assert body["valid_rows"] == 2
    assert body["error_count"] == 0

    commit = client.post(f"/api/v1/admin/imports/{job_id}/commit", headers=admin)
    assert commit.status_code == 200, commit.text
    assert commit.json()["result"]["created"] >= 1

    # Second import same external ids → update, not duplicate apps by link
    up2 = client.post(
        "/api/v1/admin/imports/csv",
        headers=admin,
        data={"kind": "cmdb_ci"},
        files={"file": ("cis.csv", io.BytesIO(CI_CSV.encode()), "text/csv")},
    )
    job2 = up2.json()["id"]
    client.post(f"/api/v1/admin/imports/{job2}/preview", headers=admin)
    c2 = client.post(f"/api/v1/admin/imports/{job2}/commit", headers=admin)
    assert c2.status_code == 200
    assert c2.json()["result"]["created"] == 0
    assert c2.json()["result"]["updated"] >= 1


def test_manual_dependency_preserved(client):
    admin = auth_header(client, "admin@test.example.com")
    pub = auth_header(client, "publisher@test.example.com")

    # Seed CIs via CSV
    up = client.post(
        "/api/v1/admin/imports/csv",
        headers=admin,
        data={"kind": "cmdb_ci"},
        files={"file": ("cis.csv", io.BytesIO(CI_CSV.encode()), "text/csv")},
    )
    job_id = up.json()["id"]
    client.post(f"/api/v1/admin/imports/{job_id}/preview", headers=admin)
    client.post(f"/api/v1/admin/imports/{job_id}/commit", headers=admin)

    apps = client.get("/api/v1/applications", headers=pub).json()
    # keys are slugged from names
    a = next(a for a in apps if "payments" in a["key"] or a["name"].startswith("Payments"))
    b = next(a for a in apps if "hr" in a["key"] or a["name"].startswith("HR"))

    # Publisher needs an application grant for cross-app dependency writes
    publisher_id = client.get("/api/v1/auth/me", headers=pub).json()["id"]
    grant = client.post(
        "/api/v1/admin/grants",
        headers=admin,
        json={"user_id": publisher_id, "application_id": a["id"], "role": "publisher"},
    )
    assert grant.status_code == 201, grant.text

    dep = client.post(
        f"/api/v1/applications/{a['id']}/dependencies",
        headers=pub,
        json={"to_type": "application", "to_id": b["id"], "dependency_kind": "depends_on"},
    )
    assert dep.status_code == 201
    assert dep.json()["origin"] == "manual"

    # Relationship CSV without overwrite flag should skip manual
    rel = client.post(
        "/api/v1/admin/imports/csv",
        headers=admin,
        data={"kind": "ci_relationships", "overwrite_manual_dependencies": "false"},
        files={"file": ("rel.csv", io.BytesIO(REL_CSV.encode()), "text/csv")},
    )
    rid = rel.json()["id"]
    client.post(f"/api/v1/admin/imports/{rid}/preview", headers=admin)
    committed = client.post(f"/api/v1/admin/imports/{rid}/commit", headers=admin)
    assert committed.status_code == 200
    # manual edge still present
    listed = client.get(f"/api/v1/applications/{a['id']}/dependencies", headers=pub)
    assert listed.json()[0]["origin"] == "manual"


def test_preview_shows_row_errors(client):
    admin = auth_header(client, "admin@test.example.com")
    bad = "sys_id,name,short_description\n,missing-id,no sys id\n"
    up = client.post(
        "/api/v1/admin/imports/csv",
        headers=admin,
        data={"kind": "cmdb_ci"},
        files={"file": ("bad.csv", io.BytesIO(bad.encode()), "text/csv")},
    )
    job_id = up.json()["id"]
    preview = client.post(f"/api/v1/admin/imports/{job_id}/preview", headers=admin)
    assert preview.json()["error_count"] >= 1
