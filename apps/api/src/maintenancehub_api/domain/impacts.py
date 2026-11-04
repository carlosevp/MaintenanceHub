"""Effective impact resolution for series defaults vs occurrence overrides.

Occurrence impacts replace series defaults only when ``impacts_overridden`` is set.
An explicit empty override is valid (no impacted apps/envs for that occurrence).
Application+environment are matched as pairs — never as independent ID sets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from maintenancehub_api.models import (
    EventImpact,
    ImpactTargetType,
    MaintenanceEvent,
    OccurrenceImpact,
    OccurrenceRecord,
)


@dataclass(frozen=True)
class ImpactRef:
    target_type: str
    target_id: str
    environment_id: str | None = None

    @property
    def is_application(self) -> bool:
        return self.target_type == ImpactTargetType.application.value or self.target_type == "application"

    @property
    def app_env_pair(self) -> tuple[str, str | None] | None:
        if not self.is_application:
            return None
        return (self.target_id, self.environment_id)


def _as_ref(row: EventImpact | OccurrenceImpact | dict[str, Any]) -> ImpactRef:
    if isinstance(row, dict):
        tt = row["target_type"]
        tt_s = tt.value if hasattr(tt, "value") else str(tt)
        return ImpactRef(
            target_type=tt_s,
            target_id=row["target_id"],
            environment_id=row.get("environment_id"),
        )
    tt = row.target_type
    tt_s = tt.value if hasattr(tt, "value") else str(tt)
    return ImpactRef(
        target_type=tt_s,
        target_id=row.target_id,
        environment_id=row.environment_id,
    )


def series_impacts(event: MaintenanceEvent) -> list[ImpactRef]:
    return [_as_ref(i) for i in (event.impacts or [])]


def occurrence_override_impacts(record: OccurrenceRecord) -> list[ImpactRef]:
    """Impacts from an overridden record — may be empty on purpose."""
    return [_as_ref(i) for i in (record.impacts or [])]


def effective_impacts(
    event: MaintenanceEvent,
    record: OccurrenceRecord | None = None,
) -> list[ImpactRef]:
    """Resolve impacts for notification targeting / authz.

    - If ``record.impacts_overridden``: use occurrence impacts (including empty).
    - Else: series ``event_impacts`` defaults.
    """
    if record is not None and record.impacts_overridden:
        return occurrence_override_impacts(record)
    return series_impacts(event)


def application_ids(impacts: Sequence[ImpactRef]) -> set[str]:
    return {i.target_id for i in impacts if i.is_application}


def environment_ids(impacts: Sequence[ImpactRef]) -> set[str]:
    return {i.environment_id for i in impacts if i.environment_id}


def app_env_pairs(impacts: Sequence[ImpactRef]) -> set[tuple[str, str | None]]:
    """Exact (application_id, environment_id) pairs from application impacts."""
    out: set[tuple[str, str | None]] = set()
    for i in impacts:
        pair = i.app_env_pair
        if pair is not None:
            out.add(pair)
    return out


def impacts_from_dicts(rows: Iterable[dict[str, Any]] | None) -> list[ImpactRef]:
    return [_as_ref(r) for r in (rows or [])]
