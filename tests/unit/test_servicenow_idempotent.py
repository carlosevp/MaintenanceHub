"""M9 — SN poll upsert idempotency and cancel mapping."""

from __future__ import annotations

from maintenancehub_api.adapters.servicenow import ChangeRecord, NullChangeAdapter
from maintenancehub_api.domain.servicenow_sync import run_poll
from maintenancehub_api.models import MaintenanceEvent, SnUnmatchedRecord


FIXTURE = [
    {
        "sys_id": "abc-111",
        "number": "CHG100",
        "short_description": "Patch window",
        "description": "desc",
        "state": "1",
        "start_date": "2026-12-01T02:00:00Z",
        "end_date": "2026-12-01T04:00:00Z",
        "sys_updated_on": "2026-11-01T00:00:00Z",
    }
]


def test_null_adapter_no_records():
    assert NullChangeAdapter().poll() == []
    assert NullChangeAdapter().connection_test()["enabled"] is False


def test_re_poll_no_duplicate_events(db_session, monkeypatch):
    monkeypatch.setenv("SERVICENOW_ENABLED", "true")
    monkeypatch.setenv("SERVICENOW_USE_FIXTURE", "true")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()

    s1 = run_poll(db_session, fixture_records=FIXTURE)
    assert s1["created"] == 1
    s2 = run_poll(db_session, fixture_records=FIXTURE)
    assert s2["unchanged"] == 1
    assert s2["created"] == 0
    count = (
        db_session.query(MaintenanceEvent)
        .filter(MaintenanceEvent.external_id == "abc-111")
        .count()
    )
    assert count == 1


def test_field_change_updates_event(db_session, monkeypatch):
    monkeypatch.setenv("SERVICENOW_ENABLED", "true")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()

    run_poll(db_session, fixture_records=FIXTURE)
    updated = [{**FIXTURE[0], "short_description": "Patch window UPDATED", "sys_updated_on": "2026-11-02"}]
    stats = run_poll(db_session, fixture_records=updated)
    assert stats["updated"] == 1
    event = (
        db_session.query(MaintenanceEvent)
        .filter(MaintenanceEvent.external_id == "abc-111")
        .one()
    )
    assert "UPDATED" in event.title


def test_cancel_maps_to_cancelled(db_session, monkeypatch):
    monkeypatch.setenv("SERVICENOW_ENABLED", "true")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()

    run_poll(db_session, fixture_records=FIXTURE)
    cancelled = [{**FIXTURE[0], "state": "cancelled", "sys_updated_on": "2026-11-03"}]
    stats = run_poll(db_session, fixture_records=cancelled)
    assert stats["cancelled"] == 1
    event = (
        db_session.query(MaintenanceEvent)
        .filter(MaintenanceEvent.external_id == "abc-111")
        .one()
    )
    assert event.status.value == "cancelled"


def test_unmatched_orphan_cancel(db_session, monkeypatch):
    monkeypatch.setenv("SERVICENOW_ENABLED", "true")
    from maintenancehub_api.config import get_settings

    get_settings.cache_clear()

    orphan = [
        {
            "sys_id": "orphan-1",
            "number": "CHG999",
            "short_description": "Never created",
            "description": "",
            "state": "cancelled",
            "start_date": "2026-12-01T02:00:00Z",
            "end_date": "2026-12-01T03:00:00Z",
            "sys_updated_on": "2026-11-01",
        }
    ]
    stats = run_poll(db_session, fixture_records=orphan)
    assert stats["unmatched"] == 1
    assert (
        db_session.query(SnUnmatchedRecord)
        .filter(SnUnmatchedRecord.external_id == "orphan-1", SnUnmatchedRecord.status == "open")
        .count()
        == 1
    )


def test_change_record_hash_stable():
    a = ChangeRecord(
        external_id="1",
        number="N",
        short_description="t",
        description="d",
        state="1",
        start="x",
        end="y",
        sys_updated_on="z",
    )
    b = ChangeRecord(
        external_id="1",
        number="N",
        short_description="t",
        description="d",
        state="1",
        start="x",
        end="y",
        sys_updated_on="z",
    )
    assert a.content_hash() == b.content_hash()
