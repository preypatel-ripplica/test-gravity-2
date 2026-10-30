"""Videos-domain document shapes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.main.models import new_id, utc_now


class Channel(BaseModel):
    id: str  # YouTube channel id
    project_id: str
    title: str = ""
    description: str = ""
    custom_url: Optional[str] = None
    published_at: Optional[str] = None
    view_count: int = 0
    subscriber_count: int = 0
    video_count: int = 0
    language: Optional[str] = None
    secret_id: Optional[str] = None  # → project_secrets oauth row
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Video(BaseModel):
    id: str  # YouTube video id
    project_id: str
    channel_id: str
    title: str = ""
    published_at: str = ""
    thumbnail_url: Optional[str] = None
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    duration_seconds: Optional[int] = None
    is_short: bool = False
    privacy_status: str = "public"
    # AI content-plan map (formerly projects.content_topic_coverage.videos)
    topic_id: Optional[str] = None
    out_of_keyword: Optional[bool] = None
    video_type: Optional[str] = None
    topic_mapped_at: Optional[str] = None
    notes: str = ""
    metadata_fields: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class YtMetadata(BaseModel):
    """YouTube title/description/tags/locales package for a topic (was Production)."""

    id: str = Field(default_factory=lambda: new_id("yt_metadata"))
    project_id: str
    topic_id: Optional[str] = None
    plan_item_id: Optional[str] = None
    topic_text: str = ""
    locales: dict[str, Any] = Field(default_factory=dict)
    youtube_video_ids: list[str] = Field(default_factory=list)
    posted_urls: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


# Legacy alias — prefer YtMetadata
Production = YtMetadata


class MonthlyReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("report"))
    project_id: str
    report_month: str  # YYYY-MM
    status: str = "draft"
    narrative: Any = None
    html: Optional[str] = None
    pdf_path: Optional[str] = None
    refine_history: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


COL_CHANNELS = "channels"
COL_VIDEOS = "videos"
COL_YT_METADATA = "yt_metadata"
COL_PRODUCTIONS = COL_YT_METADATA  # legacy name
COL_MONTHLY_REPORTS = "monthly_reports"
