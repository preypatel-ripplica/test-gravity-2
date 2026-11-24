"""Instagram reels stored in the shared videos collection."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import HTTPException, status

from backend.tg.database import (
    list_videos_for_platform,
    merge_preserved_video_fields,
    replace_channel_videos,
)

GRAPH = "https://graph.instagram.com"
MAX_REELS = 200


def _caption_title(caption: str | None) -> str:
    text = " ".join((caption or "").split())
    if not text:
        return "Instagram reel"
    return text[:140]


async def _insights_views(client: httpx.AsyncClient, media_id: str, token: str) -> int:
    try:
        response = await client.get(
            f"{GRAPH}/{media_id}/insights",
            params={"metric": "views", "access_token": token},
        )
        if response.status_code != 200:
            return 0
        data = response.json().get("data") or []
        for row in data:
            if row.get("name") == "views":
                values = row.get("values") or []
                if values:
                    return int(values[0].get("value") or 0)
                return int(row.get("value") or 0)
    except (httpx.HTTPError, TypeError, ValueError):
        return 0
    return 0


async def fetch_instagram_reels(client_id: str) -> tuple[str, list[dict]]:
    """Return (instagram user id, reel rows) using the client's project_secrets token."""
    from backend.tg.routes.social import (
        _refresh_instagram_token_if_needed,
        _require_instagram_connection,
    )

    connection = await _refresh_instagram_token_if_needed(
        client_id,
        _require_instagram_connection(client_id),
    )
    ig_user_id = connection["instagram_user_id"]
    token = connection["access_token"]
    rows: list[dict] = []
    after = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        while len(rows) < MAX_REELS:
            params = {
                "access_token": token,
                "limit": 50,
                "fields": (
                    "id,caption,media_type,media_product_type,thumbnail_url,"
                    "media_url,timestamp,like_count,comments_count,permalink"
                ),
            }
            if after:
                params["after"] = after
            response = await client.get(f"{GRAPH}/{ig_user_id}/media", params=params)
            if response.status_code != 200:
                text = response.text[:400]
                if "OAuthException" in text or '"code":190' in text or '"code": 190' in text:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Instagram token expired. Reconnect Instagram from Connections.",
                    )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed to fetch Instagram media: {text}",
                )
            payload = response.json()
            batch = payload.get("data") or []
            if not batch:
                break
            for item in batch:
                product = (item.get("media_product_type") or "").upper()
                media_type = (item.get("media_type") or "").upper()
                if product != "REELS" and media_type != "VIDEO":
                    continue
                rows.append(item)
                if len(rows) >= MAX_REELS:
                    break
            after = ((payload.get("paging") or {}).get("cursors") or {}).get("after")
            if not after:
                break

        views = await asyncio.gather(
            *[_insights_views(client, row.get("id") or "", token) for row in rows]
        )

    library: list[dict] = []
    for item, view_count in zip(rows, views):
        media_id = item.get("id")
        if not media_id:
            continue
        library.append(
            {
                "id": media_id,
                "title": _caption_title(item.get("caption")),
                "published_at": item.get("timestamp") or "",
                "thumbnail_url": item.get("thumbnail_url") or item.get("media_url") or "",
                "view_count": int(view_count or 0),
                "like_count": int(item.get("like_count") or 0),
                "comment_count": int(item.get("comments_count") or 0),
                "privacy_status": "public",
                "platform": "instagram",
                "permalink": item.get("permalink") or "",
            }
        )
    return ig_user_id, library


def save_instagram_reels(client_id: str, ig_user_id: str, reels: list[dict]) -> list[dict]:
    existing = {row["id"]: row for row in list_videos_for_platform(client_id, "instagram")}
    stored = []
    for reel in reels:
        stored.append(merge_preserved_video_fields(reel, existing.get(reel["id"])))
    replace_channel_videos(ig_user_id, client_id, stored, platform="instagram")
    return stored


def public_video_rows(rows: list[dict]) -> list[dict]:
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": row.get("id"),
                "title": row.get("title") or "",
                "published_at": row.get("published_at") or "",
                "thumbnail_url": row.get("thumbnail_url") or "",
                "view_count": int(row.get("view_count") or 0),
                "like_count": int(row.get("like_count") or 0),
                "comment_count": int(row.get("comment_count") or 0),
                "privacy_status": row.get("privacy_status") or "public",
                "notes": row.get("notes") or "",
                "metadata_fields": row.get("metadata_fields") or {},
                "platform": "instagram",
                "channel_id": row.get("channel_id") or "",
                "permalink": row.get("permalink") or "",
            }
        )
    return out
