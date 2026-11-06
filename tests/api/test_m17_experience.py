"""M17 experience profile capability registry."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from tests.conftest import auth_header


def test_settings_default_is_essentials(monkeypatch):
    monkeypatch.delenv("EXPERIENCE_PROFILE", raising=False)
    from maintenancehub_api.config import Settings, get_settings

    get_settings.cache_clear()
    assert Settings().experience_profile == "essentials"


def test_experience_endpoint_essentials_scenarios(client, monkeypatch):
    monkeypatch.setenv("EXPERIENCE_PROFILE", "essentials")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()
    r = client.get("/api/v1/experience")
    assert r.status_code == 200
    body = r.json()
    assert body["profile"] == "essentials"
    assert body["label"] == "Essentials"
    assert body["capabilities"]["overview"] is True
    assert body["capabilities"]["impact_analysis"] is False
    assert body["capabilities"]["admin_workspace"] is False
    assert body["capabilities"]["servicenow"] is False
    assert len(body["scenarios"]) == 3
    by_id = {s["id"]: s for s in body["scenarios"]}
    assert by_id["essentials-claims-int"]["available"] is True
    assert by_id["team-weekly-payments"]["available"] is False
    assert by_id["advanced-oracle-nonprod"]["available"] is False
    assert "cannot unlock" in body["note"].lower()


def test_unknown_profile_fails_closed():
    from maintenancehub_api.domain.experience import (
        UnknownExperienceProfileError,
        normalize_profile,
    )

    with pytest.raises(UnknownExperienceProfileError):
        normalize_profile("platinum")
    assert normalize_profile(None) == "essentials"
    assert normalize_profile("") == "essentials"


def test_settings_reject_unknown_profile(monkeypatch):
    monkeypatch.setenv("EXPERIENCE_PROFILE", "not-a-real-profile")
    from maintenancehub_api.config import Settings, get_settings

    get_settings.cache_clear()
    with pytest.raises((ValidationError, ValueError)):
        Settings()
    get_settings.cache_clear()


def test_essentials_blocks_impact_admin_and_recurrence(client, monkeypatch):
    monkeypatch.setenv("EXPERIENCE_PROFILE", "essentials")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()
    exp = client.get("/api/v1/experience").json()
    assert exp["profile"] == "essentials"
    assert exp["capabilities"]["recurrence_editor"] is False

    pub = auth_header(client, "publisher@test.example.com")
    r = client.post(
        "/api/v1/impact-analysis/preview",
        headers=pub,
        json={
            "seeds": [
                {
                    "target_type": "application",
                    "target_id": "00000000-0000-0000-0000-000000000001",
                    "environment_id": None,
                }
            ],
            "starts_at": "2030-01-01T00:00:00+00:00",
            "ends_at": "2030-01-01T01:00:00+00:00",
            "max_depth": 5,
        },
    )
    assert r.status_code == 403, r.text

    admin = auth_header(client, "admin@test.example.com")
    assert client.get("/api/v1/admin/overview", headers=admin).status_code == 403

    r3 = client.put(
        "/api/v1/events/00000000-0000-0000-0000-000000000099/recurrence",
        headers=pub,
        json={"freq": "WEEKLY", "interval": 1, "byweekday": ["MO"]},
    )
    assert r3.status_code == 403, r3.text


def test_team_unlocks_impact_not_admin(client, monkeypatch):
    monkeypatch.setenv("EXPERIENCE_PROFILE", "team")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()
    exp = client.get("/api/v1/experience").json()
    assert exp["profile"] == "team"
    assert exp["capabilities"]["impact_analysis"] is True
    assert exp["capabilities"]["recurrence_editor"] is True
    assert exp["capabilities"]["admin_workspace"] is False
    assert exp["capabilities"]["servicenow"] is False
    by_id = {s["id"]: s for s in exp["scenarios"]}
    assert by_id["team-weekly-payments"]["available"] is True
    assert by_id["advanced-oracle-nonprod"]["available"] is True

    admin = auth_header(client, "admin@test.example.com")
    assert client.get("/api/v1/admin/overview", headers=admin).status_code == 403


def test_enterprise_allows_admin_overview(client, monkeypatch):
    monkeypatch.setenv("EXPERIENCE_PROFILE", "enterprise")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()
    admin = auth_header(client, "admin@test.example.com")
    assert client.get("/api/v1/admin/overview", headers=admin).status_code == 200
    exp = client.get("/api/v1/experience").json()
    assert exp["capabilities"]["servicenow"] is True
    assert exp["capabilities"]["csv_import"] is True


def test_notification_capture_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MH_NOTIFICATION_CAPTURE_DIR", str(tmp_path))
    monkeypatch.setenv("SMTP_ENABLED", "false")
    from maintenancehub_api.config import get_settings
    from maintenancehub_api.adapters.smtp import SmtpAdapter

    get_settings.cache_clear()
    result = SmtpAdapter().send(to="a@example.com", subject="Hello", body="Body text")
    assert result.ok
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text())
    assert payload["to"] == "a@example.com"
    assert payload["subject"] == "Hello"
    assert payload["channel"] == "log"
