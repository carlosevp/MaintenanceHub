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
    recurrence: Optional[dict[str, Any]] = None  # M3b stub — accepted but marked incomplete

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

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return ensure_utc(v)


class CancelRequest(BaseModel):
    note: Optional[str] = None


class TimelineEntryOut(ORMModel):
    id: str
    at: datetime
    actor_id: Optional[str] = None
    entry_type: str
    payload: dict[str, Any]


class TimelineNoteCreate(BaseModel):
    note: str = Field(min_length=1)
