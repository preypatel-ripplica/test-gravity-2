"""Shared / project-wide document shapes (main)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, EmailStr, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}:{uuid4()}"


class UserType(str, Enum):
    INTERNAL = "internal"
    CLIENT = "client"


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class Domain(str, Enum):
    VIDEOS = "videos"
    SOCIALMEDIA = "socialmedia"
    WEBSITE = "website"
    WHATSAPPBOT = "whatsappbot"


class TopicWeight(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TopicSource(str, Enum):
    MANUAL = "manual"
    AUTO = "auto"


class SecretKind(str, Enum):
    MANUAL = "manual"
    OAUTH = "oauth"
    APP_CONFIG = "app_config"


class TaskKind(str, Enum):
    WEEKLY = "weekly"
    CUSTOM = "custom"


class ProfileField(BaseModel):
    id: str = Field(default_factory=lambda: new_id("field"))
    label: str = ""
    value: str = ""


class ProfileSection(BaseModel):
    id: str = Field(default_factory=lambda: new_id("section"))
    title: str
    fields: list[ProfileField] = Field(default_factory=list)


class Topic(BaseModel):
    id: str = Field(default_factory=lambda: new_id("topic"))
    text: str
    weight: TopicWeight = TopicWeight.MEDIUM
    source: TopicSource = TopicSource.MANUAL
    trend_score: Optional[float] = None
    recommendation_score: Optional[float] = None
    trend_confidence: Optional[str] = None
    web_interest: Optional[float] = None
    youtube_interest: Optional[float] = None
    momentum: Optional[float] = None
    rising_flag: Optional[int] = None
    trend_fetched_at: Optional[str] = None
    recommendation_saved_at: Optional[str] = None


class User(BaseModel):
    id: str = Field(default_factory=lambda: new_id("user"))
    email: EmailStr
    name: str
    password_hash: Optional[str] = None
    type: UserType
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Project(BaseModel):
    """Client account: profile + topics list. No member list."""

    id: str = Field(default_factory=lambda: new_id("project"))
    name: str
    status: ProjectStatus = ProjectStatus.ACTIVE
    website_url: Optional[str] = None
    specialty: Optional[str] = None
    designation: Optional[str] = None
    description: Optional[str] = None
    reference_youtube_channel: Optional[str] = None
    ai_videos_started_from: Optional[str] = None
    # Soft-delete timestamp; inactive uses status=archived
    deleted_at: Optional[datetime] = None
    # Tracker deliverables (additive TG parity fields)
    tracker_deliverables: list[dict[str, Any]] = Field(default_factory=list)
    tracker_deliverables_period: str = ""
    tracker_deliverable_history: list[dict[str, Any]] = Field(default_factory=list)
    tracker_week_slot_plan: dict[str, Any] = Field(default_factory=dict)
    tracker_start_year: Optional[int] = None
    tracker_start_month: Optional[int] = None
    tracker_start_week: Optional[int] = None
    onboarding_date: Optional[str] = None
    profile_sections: list[ProfileSection] = Field(default_factory=list)
    topics: list[Topic] = Field(default_factory=list)
    # TG content_suggestions blob (items + keyword_analysis + coverage summary).
    # AI video→keyword map lives on videos docs (topic_id / out_of_keyword / video_type).
    content_plan: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Access(BaseModel):
    id: str = Field(default_factory=lambda: new_id("access"))
    user_id: str
    project_id: str
    domain: Domain
    created_at: datetime = Field(default_factory=utc_now)


class ProjectSecret(BaseModel):
    """Manual passwords, OAuth grants, and app configs."""

    id: str = Field(default_factory=lambda: new_id("secret"))
    project_id: str
    kind: SecretKind
    provider: str
    label: str = ""
    status: str = "active"
    username: Optional[str] = None
    secret_encrypted: Optional[str] = None
    scopes: list[str] = Field(default_factory=list)
    refresh_token_encrypted: Optional[str] = None
    access_token_encrypted: Optional[str] = None
    expires_at: Optional[datetime] = None
    external_account_id: Optional[str] = None
    external_account_name: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PlanItem(BaseModel):
    """One planned deliverable — script body + script attrs live here (not on projects.content_plan)."""

    id: str = Field(default_factory=lambda: new_id("plan"))
    project_id: str
    topic_id: Optional[str] = None
    title: str
    format: str = "long"
    status: str = "planned"
    script: str = ""
    script_target_duration: str = ""
    script_hook_used: str = ""
    script_cta: str = ""
    script_checklist_passed: Optional[bool] = None
    script_checklist_notes: str = ""
    # How the script body was created: AI generate/refine vs user paste.
    origin: str = "generated"  # "generated" | "manual"
    sort_order: int = 0
    yt_metadata_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TaskNote(BaseModel):
    id: str = Field(default_factory=lambda: new_id("note"))
    text: str = ""
    visibility: str = "internal"
    created_by: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class TaskSubtask(BaseModel):
    id: str = Field(default_factory=lambda: new_id("subtask"))
    title: str = ""
    done: bool = False
    due_at: Optional[datetime] = None


class Task(BaseModel):
    """Weekly card or custom issue — one collection, kind discriminator."""

    id: str = Field(default_factory=lambda: new_id("task"))
    project_id: str
    kind: TaskKind
    title: str = ""
    status: str = "planned"
    sort_order: int = 0
    year: Optional[int] = None
    month: Optional[int] = None
    week: Optional[int] = None
    topic_id: Optional[str] = None
    plan_item_id: Optional[str] = None
    assets: dict[str, Any] = Field(default_factory=dict)
    destinations: list[dict[str, Any]] = Field(default_factory=list)
    priority: Optional[str] = None
    due_at: Optional[datetime] = None
    subtasks: list[TaskSubtask] = Field(default_factory=list)
    notes: list[TaskNote] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


COL_USERS = "users"
COL_PROJECTS = "projects"
COL_ACCESS = "access"
COL_PROJECT_SECRETS = "project_secrets"
COL_PLAN_ITEMS = "plan_items"
# Deprecated unified tasks — weekly/custom live in trackers collections
COL_TASKS = "tasks"
COL_WEEKLY_TRACKERS = "weekly_trackers"
COL_CUSTOM_TRACKERS = "custom_trackers"
