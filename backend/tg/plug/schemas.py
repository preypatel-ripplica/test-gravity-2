from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class PlugRegister(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class PlugToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PlugProfileUpdate(BaseModel):
    name: Optional[str] = None
    website: Optional[str] = None
    instagram: Optional[str] = None
    niche: Optional[str] = None
    niche_details: Optional[str] = None
    example_topics: Optional[list[str]] = None
    example_scripts: Optional[list[str]] = None
    reference_videos: Optional[list[str]] = None
    language: Optional[str] = None


class PlugInstagramConfigSave(BaseModel):
    app_id: str = Field(min_length=1)
    app_secret: str = Field(min_length=1)


class PlugInstagramConfigOut(BaseModel):
    app_id: str
    app_secret: str
    redirect_uri: Optional[str] = None


class PlugInstagramConnectUrlResponse(BaseModel):
    authorization_url: str
    state: str


class PlugInstagramConnect(BaseModel):
    connected: bool = True


class PlugTopicSearch(BaseModel):
    language: str = Field(default="english", description="Spoken language as a free string")
    prompt: str = Field(default="", description="Optional extra instruction for this search")


class PlugScriptRedo(BaseModel):
    topic_id: str
    prompt: str = Field(min_length=1)
    language: Optional[str] = None


class PlugScriptRate(BaseModel):
    topic_id: str
    rating: Optional[str] = Field(
        default=None,
        description="like, dislike, or null to clear",
    )


class PlugTopicOut(BaseModel):
    id: str
    title: str
    score: int
    angle: str = ""
    script: str = ""
    hook_used: str = ""
    cta_line: str = ""
    rating: Optional[str] = None


class PlugTodoCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class PlugTodoUpdate(BaseModel):
    id: str
    text: Optional[str] = None
    done: Optional[bool] = None


class PlugTodoDelete(BaseModel):
    id: str


class PlugTodoReorder(BaseModel):
    open_ids: list[str] = Field(default_factory=list)
    done_ids: list[str] = Field(default_factory=list)


class PlugCreatorOut(BaseModel):
    username: str
    is_active: bool = True
    name: str = ""
    website: str = ""
    instagram: str = ""
    niche: str = ""
    niche_details: str = ""
    example_topics: list[str] = Field(default_factory=list)
    example_scripts: list[str] = Field(default_factory=list)
    reference_videos: list[str] = Field(default_factory=list)
    language: str = "english"
    instagram_connected: bool = False
    latest_run_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
