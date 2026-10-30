"""Tracker document shapes. Weekly and custom are intentionally different."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.main.models import new_id, utc_now

COL_WEEKLY_TRACKERS = "weekly_trackers"
COL_CUSTOM_TRACKERS = "custom_trackers"


class WeeklyTracker(BaseModel):
    """One week board: cards for long/short/static/blog."""

    id: str  # weekly:{project}:{y}:{m}:{w}
    project_id: str
    year: int
    month: int
    week: int
    cards: list[dict[str, Any]] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    updated_by: str = ""
    updated_at: datetime = Field(default_factory=utc_now)


class CustomTracker(BaseModel):
    """Client-wide todo list — not week-scoped, not card-based."""

    id: str  # custom:{project}
    project_id: str
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    updated_by: str = ""
    updated_at: datetime = Field(default_factory=utc_now)


def weekly_doc_id(project_id: str, year: int, month: int, week: int) -> str:
    return f"weekly:{project_id}:{int(year)}:{int(month)}:{int(week)}"


def custom_doc_id(project_id: str) -> str:
    return f"custom:{project_id}"
