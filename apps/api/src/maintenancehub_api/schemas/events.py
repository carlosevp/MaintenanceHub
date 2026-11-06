from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from maintenancehub_api.schemas.common import ORMModel, ensure_utc


class ImpactIn(BaseModel):
    target_type: str  # application | service | infra_component
    target_id: str
    environment_id: Optional[str] = None


class ImpactOut(ORMModel):
    id: str
    target_type: str
    target_id: str
    environment_id: Optional[str] = None


class RecurrenceSpec(BaseModel):
    """Structured RRULE input. Use freq=CUSTOM with rrule= for free-form."""

    freq: str = "WEEKLY"  # DAILY|WEEKLY|MONTHLY|YEARLY|CUSTOM
    interval: int = 1
    byweekday: Optional[list[str]] = None
    bymonthday: Optional[int] = None
    until: Optional[datetime] = None
    count: Optional[int] = None
    rrule: Optional[str] = None  # raw RRULE body or RRULE:...

    @field_validator("until")
    @classmethod
    def _utc_until(cls, v: datetime | None) -> datetime | None:
        return ensure_utc(v) if v else v


class RecurrenceExceptionOut(BaseModel):
    id: str
    original_starts_at: datetime
    action: str
    new_starts_at: Optional[datetime] = None
    new_ends_at: Optional[datetime] = None


class RecurrenceOut(BaseModel):
    rrule: str
    until_at: Optional[datetime] = None
    summary: str
    exceptions: list[RecurrenceExceptionOut] = Field(default_factory=list)


class EventCreate(BaseModel):
    kind: str = "planned_maintenance"
    title: str = Field(min_length=1, max_length=300)
    description: Optional[str] = None
    expected_impact: Optional[str] = None
    approval_state: str = "confirmed_scheduled"
    starts_at: datetime
    ends_at: datetime
    timezone: str = "UTC"
    impacts: list[ImpactIn] = Field(default_factory=list)
    recurrence: Optional[RecurrenceSpec] = None

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return ensure_utc(v)


class EventUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    description: Optional[str] = None
    expected_impact: Optional[str] = None
    approval_state: Optional[str] = None


class EventOut(ORMModel):
    id: str
    kind: str
    title: str
    description: Optional[str] = None
    expected_impact: Optional[str] = None
    status: str
    approval_state: str
    starts_at: datetime
    ends_at: datetime
    timezone: str
    is_recurring: bool
    impacts: list[ImpactOut] = Field(default_factory=list)
    recurrence: Optional[RecurrenceOut] = None
    # When representing an expanded occurrence on dashboard
    occurrence_starts_at: Optional[datetime] = None
    is_occurrence: bool = False
    series_id: Optional[str] = None
    phase: str = "scheduled"
    """approved_window | scheduled | executing | completed | cancelled"""


class TransitionRequest(BaseModel):
    status: str
    note: Optional[str] = None
    ends_at: Optional[datetime] = None

    @field_validator("ends_at")
    @classmethod
    def _utc_optional(cls, v: datetime | None) -> datetime | None:
        return ensure_utc(v) if v else v


class ExtendRequest(BaseModel):
    new_ends_at: datetime
    note: Optional[str] = None

    @field_validator("new_ends_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return ensure_utc(v)


class RescheduleRequest(BaseModel):
    starts_at: datetime
    ends_at: datetime
    note: Optional[str] = None
    # Recurring: this | this_and_future | all (default all for master reschedule)
    scope: str = "all"
    original_starts_at: Optional[datetime] = None

    @field_validator("starts_at", "ends_at", "original_starts_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return ensure_utc(v) if v else v


class CancelRequest(BaseModel):
    note: Optional[str] = None
    scope: str = "all"  # this | all
    original_starts_at: Optional[datetime] = None

    @field_validator("original_starts_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return ensure_utc(v) if v else v


class OccurrenceExceptionRequest(BaseModel):
    original_starts_at: datetime
    action: str  # cancel | reschedule
    new_starts_at: Optional[datetime] = None
    new_ends_at: Optional[datetime] = None

    @field_validator("original_starts_at", "new_starts_at", "new_ends_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return ensure_utc(v) if v else v


class SeriesEditRequest(BaseModel):
    scope: str  # this | this_and_future | all
    original_starts_at: Optional[datetime] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    title: Optional[str] = None
    description: Optional[str] = None
    expected_impact: Optional[str] = None
    approval_state: Optional[str] = None
    recurrence: Optional[RecurrenceSpec] = None
    # Exception reconciliation when RRULE/DTSTART changes (scope=all)
    # keep_historical_require_future | drop_incompatible_future | fail_on_incompatible
    exception_reconcile: Optional[str] = None
    drop_exception_originals: list[datetime] = Field(default_factory=list)

    @field_validator("original_starts_at", "starts_at", "ends_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return ensure_utc(v) if v else v

    @field_validator("drop_exception_originals")
    @classmethod
    def _utc_list(cls, v: list[datetime]) -> list[datetime]:
        return [ensure_utc(x) for x in v]


class OccurrenceActionRequest(BaseModel):
    """Identify an occurrence by stable id or original start."""

    occurrence_id: Optional[str] = None
    original_starts_at: Optional[datetime] = None
    note: Optional[str] = None

    @field_validator("original_starts_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return ensure_utc(v) if v else v


class OccurrencePatchRequest(OccurrenceActionRequest):
    expected_starts_at: Optional[datetime] = None
    expected_ends_at: Optional[datetime] = None
    expected_impact: Optional[str] = None
    description: Optional[str] = None
    impacts: Optional[list[ImpactIn]] = None
    clear_impact_override: bool = False

    @field_validator("expected_starts_at", "expected_ends_at")
    @classmethod
    def _utc_times(cls, v: datetime | None) -> datetime | None:
        return ensure_utc(v) if v else v


class OccurrenceTransitionRequest(OccurrenceActionRequest):
    status: str
    ends_at: Optional[datetime] = None

    @field_validator("ends_at")
    @classmethod
    def _utc_ends(cls, v: datetime | None) -> datetime | None:
        return ensure_utc(v) if v else v


class OccurrenceExtendRequest(OccurrenceActionRequest):
    new_ends_at: datetime

    @field_validator("new_ends_at")
    @classmethod
    def _utc_new_end(cls, v: datetime) -> datetime:
        return ensure_utc(v)


class RecurrencePreviewRequest(BaseModel):
    starts_at: datetime
    ends_at: datetime
    timezone: str = "UTC"
    recurrence: RecurrenceSpec
    count: int = Field(default=10, ge=1, le=50)
    exceptions: list[OccurrenceExceptionRequest] = Field(default_factory=list)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return ensure_utc(v)


class TimelineEntryOut(ORMModel):
    id: str
    at: datetime
    actor_id: Optional[str] = None
    entry_type: str
    payload: dict[str, Any]


class TimelineNoteCreate(BaseModel):
    note: str = Field(min_length=1)
