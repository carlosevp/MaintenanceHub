from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from maintenancehub_api.schemas.events import EventOut


class DashboardSlice(BaseModel):
    count: int
    items: list[EventOut] = Field(default_factory=list)


class DashboardSummary(BaseModel):
    current: DashboardSlice
    upcoming: DashboardSlice
    recent: DashboardSlice
    outages: DashboardSlice
    as_of: datetime


class CalendarEventOut(BaseModel):
    id: str
    title: str
    kind: str
    status: str
    approval_state: str
    starts_at: datetime
    ends_at: datetime
    timezone: str
    is_occurrence: bool = False
    occurrence_starts_at: Optional[datetime] = None


class FavoritesPut(BaseModel):
    application_ids: list[str]


class FavoriteOut(BaseModel):
    application_ids: list[str]
