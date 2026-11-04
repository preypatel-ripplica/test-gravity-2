"""Content Plan APIs — rebuild TG-shaped responses from Beacon collections.

Frontend still calls /client.content-plan.* ; we serve from:
  projects.content_plan  (TG suggestions blob)
  plan_items             (normalized rows)
  yt_metadata            (yt locales / posted urls)
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.main.access_guards import require_domain_access, require_internal
from backend.main.auth import current_user
from backend.main.compat import _clients_payload
from backend.main.db import plan_items_col, projects_col, weekly_trackers_col, yt_metadata_col
from backend.main.main_crudl import find_project, project_list
from backend.main.models import Domain, utc_now

router = APIRouter(tags=["content-plan"])


class ClientIdBody(BaseModel):
    client_id: str


class MapBody(BaseModel):
    client_id: str
    force: bool = True


class GenerateBody(BaseModel):
    client_id: str
    count: int = 5
    force_remap: bool = False


class RegenerateBody(BaseModel):
    client_id: str
    count: Optional[int] = None
    user_prompt: Optional[str] = None
    force_remap: bool = False


class UpdateScriptBody(BaseModel):
    client_id: str
    item_id: str
    script: str = ""


class RefineScriptBody(BaseModel):
    client_id: str
    item_id: str
    user_prompt: str = ""


def _project_id(body: Any) -> str:
    return getattr(body, "client_id", None) or getattr(body, "project_id", None)


def _productions_by_topic(project_id: str) -> dict[str, dict]:
    out = {}
    for row in yt_metadata_col().find({"project_id": project_id}, {"_id": 0}):
        tid = row.get("topic_id")
        if tid:
            out[str(tid)] = row
    return out


def _hydrate_item(item: dict, packages: dict[str, dict]) -> dict:
    row = dict(item)
    topic_id = str(row.get("topic_id") or "")
    pkg = packages.get(topic_id) if topic_id else None
    if pkg:
        locales = dict(pkg.get("locales") or pkg.get("yt_locales") or {})
        row["yt_locales"] = locales
        # mirror default locale fields for older UI bits
        preferred = locales.get("hinglish") or locales.get("en") or next(
            iter(locales.values()), None
        )
        if isinstance(preferred, dict):
            row.setdefault("yt_title", preferred.get("yt_title"))
            row.setdefault("yt_description", preferred.get("yt_description"))
            row.setdefault("yt_tags", preferred.get("yt_tags"))
            row.setdefault("yt_thumbnail_url", preferred.get("yt_thumbnail_url"))
            row.setdefault("yt_thumbnail_prompt", preferred.get("yt_thumbnail_prompt"))
    title_en = (row.get("title_en") or "").strip()
    title_hi = (row.get("title_hinglish") or "").strip()
    legacy = (row.get("working_title") or "").strip()
    if not title_en:
        title_en = legacy or title_hi or row.get("topic_text") or row.get("title") or ""
    if not title_hi:
        title_hi = legacy or title_en
    row["title_en"] = title_en
    row["title_hinglish"] = title_hi
    row["working_title"] = legacy or title_hi or title_en
    row.setdefault("tracker_placements", [])
    return row


def _tracker_placements(project_id: str) -> dict[str, list]:
    by_item: dict[str, list] = {}
    for doc in weekly_trackers_col().find({"project_id": project_id}, {"_id": 0}):
        for card in doc.get("cards") or []:
            item_id = card.get("content_plan_item_id")
            if not item_id:
                continue
            by_item.setdefault(item_id, []).append(
                {
                    "item_id": item_id,
                    "year": doc.get("year"),
                    "month": doc.get("month"),
                    "week": doc.get("week"),
                    "card_id": card.get("id"),
                    "card_title": card.get("title"),
                }
            )
    return by_item


def _rebuild_suggestions(project: dict) -> dict:
    """Prefer stored content_plan blob; always hydrate scripts from plan_items."""
    from backend.tg.database import (
        CONTENT_PLAN_SCRIPT_FIELDS,
        hydrate_scripts_from_plan_items,
    )

    suggestions = dict(project.get("content_plan") or {})
    items = [dict(i) for i in (suggestions.get("items") or []) if isinstance(i, dict)]

    # If blob missing items, rebuild from latest plan_items only (history stays for trackers)
    if not items:
        latest = list(
            plan_items_col()
            .find({"project_id": project["id"], "is_latest": True}, {"_id": 0})
            .sort("sort_order", 1)
        )
        if not latest:
            # Legacy rows before is_latest existed
            latest = list(
                plan_items_col()
                .find(
                    {
                        "project_id": project["id"],
                        "$or": [
                            {"is_latest": {"$exists": False}},
                            {"is_latest": None},
                        ],
                    },
                    {"_id": 0},
                )
                .sort("sort_order", 1)
            )
        for row in latest:
            items.append(
                {
                    "id": row["id"],
                    "topic_id": row.get("topic_id") or "",
                    "topic_text": row.get("title") or "",
                    "format": row.get("format") or "long",
                    "video_type": row.get("format") or "long",
                    "title_en": row.get("title") or "",
                    "title_hinglish": row.get("title") or "",
                    "working_title": row.get("title") or "",
                    "reasoning": "",
                    "recommendation_score": 0,
                    "is_latest": True if row.get("is_latest") is None else bool(row.get("is_latest")),
                }
            )
        suggestions["items"] = items
        suggestions["count"] = len(items)

    suggestions = hydrate_scripts_from_plan_items(project["id"], suggestions)
    items = [dict(i) for i in (suggestions.get("items") or []) if isinstance(i, dict)]

    packages = _productions_by_topic(project["id"])
    placements = _tracker_placements(project["id"])
    hydrated = []
    for item in items:
        row = _hydrate_item(item, packages)
        row["tracker_placements"] = placements.get(row.get("id") or "", [])
        # Ensure script attrs stay present after production hydrate
        for key in CONTENT_PLAN_SCRIPT_FIELDS:
            if key in item:
                row[key] = item.get(key)
        hydrated.append(row)
    suggestions["items"] = hydrated
    suggestions.setdefault("keyword_analysis", suggestions.get("keyword_analysis") or [])
    suggestions.setdefault("recent_video_types", suggestions.get("recent_video_types") or [])
    if suggestions.get("coverage") is None:
        suggestions["coverage"] = None
    return suggestions


def _response(auth: dict, project_id: str) -> dict:
    require_domain_access(auth["user_id"], project_id, Domain.VIDEOS)
    project = find_project(project_id)
    listed = _clients_payload(auth)
    suggestions = _rebuild_suggestions(project)
    return {
        "clients": listed["clients"],
        "active_client_id": listed.get("active_client_id"),
        "active_channel_id": listed.get("active_channel_id"),
        "suggestions": suggestions,
    }


@router.post("/client.content-plan.get")
def content_plan_get(body: ClientIdBody, auth: dict = Depends(current_user)):
    return _response(auth, body.client_id)


@router.post("/client.content-plan.map")
def content_plan_map(body: MapBody, auth: dict = Depends(current_user)):
    """AI remap not ported yet — return persisted TG keyword_analysis if present."""
    require_internal(auth)
    data = _response(auth, body.client_id)
    analysis = (data.get("suggestions") or {}).get("keyword_analysis") or []
    if not analysis:
        raise HTTPException(
            501,
            "Keyword map AI is not wired in Beacon yet. Migrated analysis was empty for this client.",
        )
    return data


@router.post("/client.content-plan.generate")
def content_plan_generate(body: GenerateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    data = _response(auth, body.client_id)
    items = (data.get("suggestions") or {}).get("items") or []
    if not items:
        raise HTTPException(
            501,
            "Title generate AI is not wired in Beacon yet. No migrated plan items for this client.",
        )
    return data


@router.post("/client.content-plan.regenerate")
def content_plan_regenerate(body: RegenerateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    raise HTTPException(
        501,
        "Regenerate AI is not wired in Beacon yet. Use existing migrated titles/scripts.",
    )


@router.post("/client.content-plan.generate-scripts")
def content_plan_generate_scripts(body: dict, auth: dict = Depends(current_user)):
    require_internal(auth)
    client_id = (body or {}).get("client_id")
    data = _response(auth, client_id)
    items = (data.get("suggestions") or {}).get("items") or []
    if not any(i.get("script") for i in items):
        raise HTTPException(
            501,
            "Script generate AI is not wired in Beacon yet. No migrated scripts found.",
        )
    return data


@router.post("/client.content-plan.update-script")
def content_plan_update_script(
    body: UpdateScriptBody, auth: dict = Depends(current_user)
):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.client_id, Domain.VIDEOS)
    project = find_project(body.client_id)
    plan = dict(project.get("content_plan") or {})
    items = [dict(i) for i in (plan.get("items") or []) if isinstance(i, dict)]
    found = any(item.get("id") == body.item_id for item in items)
    if not found:
        raise HTTPException(404, "Plan item not found")
    # Scripts live on plan_items only
    plan_items_col().update_one(
        {"id": body.item_id, "project_id": body.client_id},
        {
            "$set": {
                "script": body.script,
                "origin": "manual",
                "status": "scripted" if (body.script or "").strip() else "planned",
                "updated_at": utc_now(),
            }
        },
        upsert=True,
    )
    # Ensure content_plan items do not keep a duplicated script blob
    from backend.tg.database import strip_script_fields_from_suggestions

    strip_script_fields_from_suggestions(plan)
    projects_col().update_one(
        {"id": body.client_id},
        {"$set": {"content_plan": plan, "updated_at": utc_now()}},
    )
    return _response(auth, body.client_id)


@router.post("/client.content-plan.refine-script")
def content_plan_refine_script(
    body: RefineScriptBody, auth: dict = Depends(current_user)
):
    require_internal(auth)
    raise HTTPException(501, "Refine-script AI is not wired in Beacon yet.")
