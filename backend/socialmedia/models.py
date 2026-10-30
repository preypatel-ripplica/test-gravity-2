"""Social-media-domain document shapes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.main.models import new_id, utc_now


class SocialPost(BaseModel):
    id: str = Field(default_factory=lambda: new_id("spost"))
    project_id: str
    source_type: str = "keyword"
    topic_id: Optional[str] = None
    plan_item_id: Optional[str] = None
    brief: dict[str, Any] = Field(default_factory=dict)
    image_url: Optional[str] = None
    status: str = "draft"
    publish_targets: list[str] = Field(default_factory=lambda: ["instagram"])
    queue_order: Optional[float] = None
    external_ids: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SocialSchedule(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ssched"))
    project_id: str
    frequency: str = "off"
    selected_days: list[str] = Field(default_factory=list)
    posts_per_day: int = 1
    auto_fallback: bool = False
    facebook_auto_publish: bool = False
    festive_auto_publish: bool = False
    festive_facebook_auto_publish: bool = False
    updated_at: datetime = Field(default_factory=utc_now)


COL_SOCIAL_POSTS = "social_posts"
COL_SOCIAL_SCHEDULES = "social_schedules"
