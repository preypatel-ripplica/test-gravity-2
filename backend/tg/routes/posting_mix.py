"""Save and read the client posting mix. Does not touch tracker destination URLs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.tg.auth import get_current_user
from backend.tg.database import (
    fetch_client_doc,
    get_facebook_connection,
    get_instagram_connection,
    update_client_fields,
)
from backend.tg.posting_mix import language_key, language_label, normalize_youtube_languages
from backend.tg.routes.client import _client_list_response

router = APIRouter(tags=["client"])


class PostingMixInclude(BaseModel):
    youtube: bool = False
    instagram: bool = False
    facebook: bool = False


class PostingMixExtra(BaseModel):
    key: str = ""
    label: str = ""


class PostingMixSaveRequest(BaseModel):
    client_id: str
    include: PostingMixInclude = Field(default_factory=PostingMixInclude)
    extra_platforms: list[PostingMixExtra] = []


class PostingMixGetRequest(BaseModel):
    client_id: str


def _connected_flags(client_id: str) -> dict:
    ig = get_instagram_connection(client_id) or {}
    fb = get_facebook_connection(client_id) or {}
    return {
        "instagram_connected": bool(ig.get("access_token") and ig.get("instagram_user_id")),
        "facebook_connected": bool(fb.get("page_access_token") or fb.get("selected_page_id") or fb.get("access_token")),
    }


@router.post("/client.posting-mix.get")
def posting_mix_get(body: PostingMixGetRequest, current_user: dict = Depends(get_current_user)):
    client = fetch_client_doc(body.client_id, username=current_user["username"])
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    flags = _connected_flags(body.client_id)
    languages = normalize_youtube_languages(client.get("youtube_languages"))
    return {
        "youtube_languages": languages,
        "posting_mix": client.get("posting_mix") if isinstance(client.get("posting_mix"), dict) else None,
        "youtube_ready": bool(languages),
        **flags,
    }


@router.post("/client.posting-mix.save")
def posting_mix_save(body: PostingMixSaveRequest, current_user: dict = Depends(get_current_user)):
    username = current_user["username"]
    client = fetch_client_doc(body.client_id, username=username)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    flags = _connected_flags(body.client_id)
    languages = normalize_youtube_languages(client.get("youtube_languages"))
    include = body.include
    if include.youtube and not languages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add YouTube languages and channels before including YouTube.",
        )
    if include.instagram and not flags["instagram_connected"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect Instagram before including it.",
        )
    if include.facebook and not flags["facebook_connected"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect Facebook before including it.",
        )
    extras = []
    seen = {"youtube", "instagram", "facebook"}
    for item in body.extra_platforms:
        key = language_key(item.key, label=item.label)
        if not key or key in seen:
            continue
        seen.add(key)
        extras.append({"key": key, "label": language_label(key, item.label)})
    mix = {
        "saved": True,
        "include": {
            "youtube": bool(include.youtube),
            "instagram": bool(include.instagram),
            "facebook": bool(include.facebook),
        },
        "extra_platforms": extras,
    }
    update_client_fields(body.client_id, username, {"posting_mix": mix})
    listed = _client_list_response(username)
    return {
        "posting_mix": mix,
        "clients": [c.model_dump() for c in listed.clients],
        "active_client_id": listed.active_client_id,
        "active_channel_id": listed.active_channel_id,
    }
