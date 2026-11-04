"""Shared Pydantic schemas and problem details."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    errors: Optional[list[Any]] = None


class Message(BaseModel):
    message: str


class PaginatedMeta(BaseModel):
    total: int
    limit: int
    offset: int


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        from datetime import timezone

        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(__import__("datetime").timezone.utc)
