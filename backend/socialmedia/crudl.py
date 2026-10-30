"""Social media domain CRUDL: posts and schedules."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from backend.main.access_guards import is_client, require_domain_access, require_internal
from backend.main.auth import current_user
from backend.main.db import social_posts_col, social_schedules_col
from backend.main.models import Domain, utc_now
from backend.main.project_scope import WithProjectId
from backend.socialmedia.models import SocialPost, SocialSchedule

router = APIRouter()
DOMAIN = Domain.SOCIALMEDIA


def _clean(doc: dict | None) -> dict | None:
    if not doc:
        return None
    doc = {**doc}
    doc.pop("_id", None)
    return jsonable_encoder(doc)


def _post_for_viewer(doc: dict, auth: dict) -> dict | None:
    """Clients only see published posts."""
    if is_client(auth) and doc.get("status") != "published":
        return None
    return _clean(doc)


class ProjectBody(WithProjectId):
    pass


class PostListBody(WithProjectId):
    status: Optional[str] = None
    source_type: Optional[str] = None


class PostGetBody(WithProjectId):
    post_id: str


class PostGenerateBody(WithProjectId):
    source_type: str = "keyword"
    topic_id: Optional[str] = None
    plan_item_id: Optional[str] = None
    brief: dict[str, Any] = Field(default_factory=dict)
    image_url: Optional[str] = None
    publish_targets: list[str] = Field(default_factory=lambda: ["instagram"])


class PostUpdateBody(WithProjectId):
    post_id: str
    brief: Optional[dict[str, Any]] = None
    image_url: Optional[str] = None
    status: Optional[str] = None
    publish_targets: Optional[list[str]] = None
    queue_order: Optional[float] = None
    external_ids: Optional[dict[str, Any]] = None
    topic_id: Optional[str] = None
    plan_item_id: Optional[str] = None
    source_type: Optional[str] = None


class PostPublishBody(WithProjectId):
    post_id: str
    external_ids: dict[str, Any] = Field(default_factory=dict)


class QueueReorderBody(WithProjectId):
    ordered_post_ids: list[str]


class ScheduleUpdateBody(WithProjectId):
    frequency: Optional[str] = None
    selected_days: Optional[list[str]] = None
    posts_per_day: Optional[int] = None
    auto_fallback: Optional[bool] = None
    facebook_auto_publish: Optional[bool] = None
    festive_auto_publish: Optional[bool] = None
    festive_facebook_auto_publish: Optional[bool] = None


# --- posts ---


@router.post("/social.post.list")
def social_post_list(body: PostListBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    query: dict[str, Any] = {"project_id": body.project_id}
    if body.status:
        query["status"] = body.status
    elif is_client(auth):
        query["status"] = "published"
    if body.source_type:
        query["source_type"] = body.source_type
    rows = list(social_posts_col().find(query, {"_id": 0}).sort("created_at", -1))
    posts = [p for p in (_post_for_viewer(r, auth) for r in rows) if p]
    return {"posts": posts}


@router.post("/social.post.get")
def social_post_get(body: PostGetBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    doc = social_posts_col().find_one(
        {"id": body.post_id, "project_id": body.project_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Post not found")
    viewed = _post_for_viewer(doc, auth)
    if not viewed:
        raise HTTPException(404, "Post not found")
    return viewed


@router.post("/social.post.generate")
def social_post_generate(body: PostGenerateBody, auth: dict = Depends(current_user)):
    """Create a draft post (AI generation can fill brief later)."""
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    doc = SocialPost(
        project_id=body.project_id,
        source_type=body.source_type,
        topic_id=body.topic_id,
        plan_item_id=body.plan_item_id,
        brief=body.brief,
        image_url=body.image_url,
        status="draft",
        publish_targets=body.publish_targets,
    ).model_dump(mode="json")
    social_posts_col().insert_one(doc)
    return {"post": _clean(doc)}


@router.post("/social.post.update")
def social_post_update(body: PostUpdateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    if not social_posts_col().find_one(
        {"id": body.post_id, "project_id": body.project_id}
    ):
        raise HTTPException(404, "Post not found")
    patch = body.model_dump(exclude={"project_id", "client_id", "post_id"}, exclude_none=True)
    patch["updated_at"] = utc_now()
    if len(patch) == 1:
        raise HTTPException(400, "No fields to update")
    social_posts_col().update_one(
        {"id": body.post_id, "project_id": body.project_id}, {"$set": patch}
    )
    return {
        "post": _clean(
            social_posts_col().find_one(
                {"id": body.post_id, "project_id": body.project_id}, {"_id": 0}
            )
        )
    }


@router.post("/social.post.delete")
def social_post_delete(body: PostGetBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    result = social_posts_col().delete_one(
        {"id": body.post_id, "project_id": body.project_id}
    )
    if result.deleted_count == 0:
        raise HTTPException(404, "Post not found")
    return {"deleted": True, "post_id": body.post_id}


@router.post("/social.post.publish")
def social_post_publish(body: PostPublishBody, auth: dict = Depends(current_user)):
    """Mark published and store external ids (actual network publish plugs in later)."""
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    doc = social_posts_col().find_one(
        {"id": body.post_id, "project_id": body.project_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Post not found")
    external = {**(doc.get("external_ids") or {}), **body.external_ids}
    social_posts_col().update_one(
        {"id": body.post_id, "project_id": body.project_id},
        {
            "$set": {
                "status": "published",
                "external_ids": external,
                "updated_at": utc_now(),
            }
        },
    )
    return {
        "post": _clean(
            social_posts_col().find_one(
                {"id": body.post_id, "project_id": body.project_id}, {"_id": 0}
            )
        )
    }


@router.post("/social.post.queue.add")
def social_post_queue_add(body: PostGetBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    doc = social_posts_col().find_one(
        {"id": body.post_id, "project_id": body.project_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Post not found")
    # append to end of queue
    last = social_posts_col().find_one(
        {"project_id": body.project_id, "status": "queued"},
        sort=[("queue_order", -1)],
    )
    order = float((last or {}).get("queue_order") or 0) + 1
    social_posts_col().update_one(
        {"id": body.post_id},
        {"$set": {"status": "queued", "queue_order": order, "updated_at": utc_now()}},
    )
    return {
        "post": _clean(
            social_posts_col().find_one({"id": body.post_id}, {"_id": 0})
        )
    }


@router.post("/social.post.queue.remove")
def social_post_queue_remove(body: PostGetBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    result = social_posts_col().update_one(
        {"id": body.post_id, "project_id": body.project_id},
        {
            "$set": {
                "status": "draft",
                "queue_order": None,
                "updated_at": utc_now(),
            }
        },
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Post not found")
    return {
        "post": _clean(
            social_posts_col().find_one({"id": body.post_id}, {"_id": 0})
        )
    }


@router.post("/social.post.queue.reorder")
def social_post_queue_reorder(body: QueueReorderBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    for index, post_id in enumerate(body.ordered_post_ids):
        social_posts_col().update_one(
            {"id": post_id, "project_id": body.project_id},
            {"$set": {"queue_order": float(index + 1), "updated_at": utc_now()}},
        )
    rows = list(
        social_posts_col()
        .find({"project_id": body.project_id, "status": "queued"}, {"_id": 0})
        .sort("queue_order", 1)
    )
    return {"posts": jsonable_encoder(rows)}


@router.post("/social.post.queue.list")
def social_post_queue_list(body: ProjectBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    if is_client(auth):
        return {"posts": []}
    rows = list(
        social_posts_col()
        .find({"project_id": body.project_id, "status": "queued"}, {"_id": 0})
        .sort("queue_order", 1)
    )
    return {"posts": jsonable_encoder(rows)}


# --- schedule ---


@router.post("/social.schedule.get")
def social_schedule_get(body: ProjectBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    doc = social_schedules_col().find_one({"project_id": body.project_id}, {"_id": 0})
    if not doc:
        doc = SocialSchedule(project_id=body.project_id).model_dump(mode="json")
    if is_client(auth):
        # clients don't manage schedule policy
        raise HTTPException(403, "Internal users only")
    return _clean(doc)


@router.post("/social.schedule.update")
def social_schedule_update(body: ScheduleUpdateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    existing = social_schedules_col().find_one(
        {"project_id": body.project_id}, {"_id": 0}
    )
    patch = body.model_dump(
        exclude={"project_id", "client_id"}, exclude_none=True
    )
    patch["updated_at"] = utc_now()
    if existing:
        social_schedules_col().update_one(
            {"project_id": body.project_id}, {"$set": patch}
        )
        doc = social_schedules_col().find_one({"project_id": body.project_id}, {"_id": 0})
    else:
        base = SocialSchedule(project_id=body.project_id).model_dump(mode="json")
        base.update(patch)
        social_schedules_col().insert_one(base)
        doc = {k: v for k, v in base.items() if k != "_id"}
    return _clean(doc)
