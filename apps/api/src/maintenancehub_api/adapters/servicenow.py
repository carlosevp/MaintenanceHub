"""ServiceNow change source adapters (ADR-007).

Poll first; push adapter interface stubbed for future. No monitoring probes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from maintenancehub_api.config import get_settings

logger = logging.getLogger("maintenancehub.servicenow")

SOURCE_SYSTEM = "servicenow"


@dataclass
class ChangeRecord:
    external_id: str  # sys_id
    number: str
    short_description: str
    description: str
    state: str
    start: str | None
    end: str | None
    sys_updated_on: str | None
    raw: dict[str, Any] = field(default_factory=dict)

    def content_hash(self) -> str:
        blob = json.dumps(
            {
                "number": self.number,
                "short_description": self.short_description,
                "description": self.description,
                "state": self.state,
                "start": self.start,
                "end": self.end,
                "sys_updated_on": self.sys_updated_on,
            },
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode()).hexdigest()


class ChangeSourceAdapter(Protocol):
    """Poll-based change source. Future push adapter will implement ingest() separately."""

    def poll(self) -> list[ChangeRecord]: ...

    def connection_test(self) -> dict[str, Any]: ...


class PushChangeAdapter(Protocol):
    """Future push/webhook interface — not wired in v1 (ADR-007)."""

    def ingest(self, payload: dict[str, Any]) -> ChangeRecord: ...


class NullChangeAdapter:
    """Used when SERVICENOW_ENABLED=false — no outbound calls."""

    def poll(self) -> list[ChangeRecord]:
        logger.info("ServiceNow null adapter: poll skipped (SERVICENOW_ENABLED=false)")
        return []

    def connection_test(self) -> dict[str, Any]:
        return {
            "ok": True,
            "enabled": False,
            "adapter": "null",
            "note": "SERVICENOW_ENABLED=false — no HTTP calls made",
        }


class FixtureChangeAdapter:
    """Local-dev / test fixture loader (JSON list of change dicts)."""

    def __init__(self, path: str | Path | None = None, records: list[dict[str, Any]] | None = None):
        self.path = Path(path) if path else None
        self._records = records

    def poll(self) -> list[ChangeRecord]:
        raw_list = self._records
        if raw_list is None:
            if not self.path or not self.path.exists():
                logger.warning("SN fixture missing at %s", self.path)
                return []
            raw_list = json.loads(self.path.read_text(encoding="utf-8"))
        return [_map_raw(item) for item in raw_list]

    def connection_test(self) -> dict[str, Any]:
        exists = bool(self.path and self.path.exists()) or self._records is not None
        return {
            "ok": exists,
            "enabled": True,
            "adapter": "fixture",
            "path": str(self.path) if self.path else None,
            "note": "Fixture adapter — no live ServiceNow calls",
        }


class HttpPollChangeAdapter:
    """Read-only Table API poll. Auth via basic (username/password from env/secrets)."""

    def poll(self) -> list[ChangeRecord]:
        settings = get_settings()
        if not settings.servicenow_instance_url:
            raise ValueError("SERVICENOW_INSTANCE_URL not configured")
        url = settings.servicenow_instance_url.rstrip("/") + settings.servicenow_api_path
        params = {"sysparm_query": settings.servicenow_query, "sysparm_limit": "100"}
        with httpx.Client(timeout=30.0) as client:
            res = client.get(
                url,
                params=params,
                auth=(settings.servicenow_username, settings.servicenow_password),
                headers={"Accept": "application/json"},
            )
            res.raise_for_status()
            data = res.json()
        results = data.get("result") or data.get("records") or []
        return [_map_raw(item) for item in results]

    def connection_test(self) -> dict[str, Any]:
        settings = get_settings()
        return {
            "ok": bool(settings.servicenow_instance_url),
            "enabled": True,
            "adapter": "http_poll",
            "instance": settings.servicenow_instance_url or None,
            "note": "Live poll adapter — credentials from env/OpenShift Secrets only",
        }


class StubPushChangeAdapter:
    """Push interface stub — not registered in v1 routes."""

    def ingest(self, payload: dict[str, Any]) -> ChangeRecord:
        raise NotImplementedError("ServiceNow push/webhooks deferred (ADR-007)")


def _map_raw(item: dict[str, Any]) -> ChangeRecord:
    # Configurable-ish field mapping with SN defaults
    return ChangeRecord(
        external_id=str(item.get("sys_id") or item.get("external_id") or ""),
        number=str(item.get("number") or ""),
        short_description=str(item.get("short_description") or item.get("title") or ""),
        description=str(item.get("description") or ""),
        state=str(item.get("state") or item.get("u_state") or ""),
        start=item.get("start_date") or item.get("planned_start_date") or item.get("starts_at"),
        end=item.get("end_date") or item.get("planned_end_date") or item.get("ends_at"),
        sys_updated_on=item.get("sys_updated_on"),
        raw=item,
    )


def get_change_adapter(
    *,
    fixture_records: list[dict[str, Any]] | None = None,
) -> ChangeSourceAdapter:
    settings = get_settings()
    if not settings.servicenow_enabled:
        return NullChangeAdapter()
    if fixture_records is not None:
        return FixtureChangeAdapter(records=fixture_records)
    if settings.servicenow_use_fixture or not settings.servicenow_instance_url:
        path = Path(settings.servicenow_fixture_path)
        if not path.is_absolute():
            # repo-relative from CWD
            path = Path.cwd() / path
        return FixtureChangeAdapter(path=path)
    return HttpPollChangeAdapter()
