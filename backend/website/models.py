"""Website/CMS document shapes — CMS_NEW patterns, scoped to Beacon projects."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.main.models import new_id, utc_now

COL_CMS_COLLECTIONS = "cms_collections"
COL_CMS_ENTRIES = "cms_entries"
COL_CMS_MEDIA = "cms_media"
COL_CMS_API_KEYS = "cms_api_keys"


class EntryStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class CmsCollection(BaseModel):
    """Content type definition. `schema` is the entry template (CMS_NEW name)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: new_id("cmscol"))
    project_id: str
    name: str
    slug: str
    # Stored as `schema` in Mongo (CMS_NEW). Also accepted as entry_schema on write.
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    ai_context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CmsEntry(BaseModel):
    id: str = Field(default_factory=lambda: new_id("cmsent"))
    project_id: str
    collection_id: str
    # CMS_NEW field name is `entry` (payload). Legacy Beacon used `data`.
    entry: dict[str, Any] = Field(default_factory=dict)
    status: EntryStatus = EntryStatus.DRAFT
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    published_at: Optional[datetime] = None


class CmsMedia(BaseModel):
    id: str = Field(default_factory=lambda: new_id("cmsmedia"))
    project_id: str
    url: str
    filename: str = ""
    alt_text: str = ""
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CmsApiKey(BaseModel):
    """Public content API token for a project's website (CMS_NEW api_keys)."""

    id: str = Field(default_factory=lambda: new_id("cmskey"))
    project_id: str
    name: str
    key_prefix: str
    key_hash: str
    scopes: list[str] = Field(default_factory=lambda: ["content:read", "media:read"])
    allowed_collections: list[str] = Field(default_factory=list)
    allowed_origins: list[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
