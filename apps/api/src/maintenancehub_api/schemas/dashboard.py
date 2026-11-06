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
    extended: DashboardSlice = Field(default_factory=lambda: DashboardSlice(count=0, items=[]))
    cancelled: DashboardSlice = Field(default_factory=lambda: DashboardSlice(count=0, items=[]))
    as_of: datetime
    note: str = (
        "Active/current items require confirmed communication and human-published "
        "executing status — never inferred from the calendar window alone."
    )


class CalendarEventOut(BaseModel):
    id: str
    """Stable occurrence id: `{event_id}@{original_starts_at}` for recurring; event id otherwise."""
    title: str
    kind: str
    status: str
    approval_state: str
    starts_at: datetime
    ends_at: datetime
    timezone: str
    is_occurrence: bool = False
    occurrence_starts_at: Optional[datetime] = None
    series_id: Optional[str] = None
    """Master event id when this row is an expanded occurrence."""
    phase: str = "scheduled"
    """approved_window | scheduled | executing | completed | cancelled — human-published only."""


class FavoritesPut(BaseModel):
    application_ids: list[str]


class FavoriteOut(BaseModel):
    application_ids: list[str]
