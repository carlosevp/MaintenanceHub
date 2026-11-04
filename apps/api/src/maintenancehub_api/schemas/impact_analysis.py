"""M14 impact analysis preview / confirm schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from maintenancehub_api.schemas.common import ensure_utc
from maintenancehub_api.schemas.events import ImpactIn


class ImpactPreviewRequest(BaseModel):
    seeds: list[ImpactIn] = Field(min_length=1)
    starts_at: datetime
    ends_at: datetime
    event_id: Optional[str] = None
    original_starts_at: Optional[datetime] = None
    exclusions: list[dict[str, Any]] = Field(default_factory=list)
    manual_additions: list[ImpactIn] = Field(default_factory=list)
    max_depth: int = Field(default=5, ge=0, le=20)

    @field_validator("starts_at", "ends_at", "original_starts_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return ensure_utc(v) if v else v


class ImpactConfirmRequest(BaseModel):
    revision_token: str = Field(min_length=8, max_length=128)
    seeds: list[ImpactIn] = Field(min_length=1)
    starts_at: datetime
    ends_at: datetime
    original_starts_at: Optional[datetime] = None
    exclusions: list[dict[str, Any]] = Field(default_factory=list)
    manual_additions: list[ImpactIn] = Field(default_factory=list)
    # Explicit accepted downstream suggestions (if omitted, server uses proposed minus exclusions)
    include_downstream: Optional[list[ImpactIn]] = None
    max_depth: int = Field(default=5, ge=0, le=20)
    publish: bool = True  # promote to confirmed_scheduled + outbox when true

    @field_validator("starts_at", "ends_at", "original_starts_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return ensure_utc(v) if v else v
