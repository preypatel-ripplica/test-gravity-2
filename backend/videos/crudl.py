"""Videos domain CRUDL: channels, videos, yt_metadata, monthly reports."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from backend.main.access_guards import (
    filter_report_for_viewer,
    filter_yt_metadata_for_viewer,
    is_client,
    require_domain_access,
    require_internal,
)
from backend.main.auth import current_user
from backend.main.db import (
    channels_col,
    monthly_reports_col,
    videos_col,
    yt_metadata_col,
)
from backend.main.models import Domain, utc_now
from backend.main.project_scope import WithProjectId
from backend.videos.models import Channel, MonthlyReport, Video, YtMetadata

router = APIRouter()
DOMAIN = Domain.VIDEOS


def _clean(doc: dict | None) -> dict | None:
    if not doc:
        return None
    doc = {**doc}
    doc.pop("_id", None)
    return jsonable_encoder(doc)


# --- bodies ---


class ProjectBody(WithProjectId):
    pass


class ChannelGetBody(WithProjectId):
    channel_id: str


class ChannelUpsertBody(WithProjectId):
    channel_id: str
    title: str = ""
    description: str = ""
    custom_url: Optional[str] = None
    published_at: Optional[str] = None
    view_count: int = 0
    subscriber_count: int = 0
    video_count: int = 0
    language: Optional[str] = None
    secret_id: Optional[str] = None


class ChannelUpdateBody(WithProjectId):
    channel_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    language: Optional[str] = None
    secret_id: Optional[str] = None


class VideoListBody(WithProjectId):
    channel_id: Optional[str] = None


class VideoGetBody(WithProjectId):
    video_id: str


class VideoUpsertBody(WithProjectId):
    video_id: str
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
    topic_id: Optional[str] = None
    notes: str = ""
    metadata_fields: dict[str, Any] = Field(default_factory=dict)


class VideoUpdateBody(WithProjectId):
    video_id: str
    notes: Optional[str] = None
    topic_id: Optional[str] = None
    metadata_fields: Optional[dict[str, Any]] = None
    title: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    privacy_status: Optional[str] = None


class VideoAnalyticsBody(WithProjectId):
    channel_id: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class YtMetadataListBody(WithProjectId):
    topic_id: Optional[str] = None


class YtMetadataGetBody(WithProjectId):
    yt_metadata_id: Optional[str] = None
    # Legacy alias accepted by production.* wrappers
    production_id: Optional[str] = None


class YtMetadataUpsertBody(WithProjectId):
    yt_metadata_id: Optional[str] = None
    production_id: Optional[str] = None
    topic_id: Optional[str] = None
    plan_item_id: Optional[str] = None
    topic_text: str = ""
    locales: dict[str, Any] = Field(default_factory=dict)
    youtube_video_ids: list[str] = Field(default_factory=list)
    posted_urls: list[dict[str, Any]] = Field(default_factory=list)


class YtMetadataUpdateBody(WithProjectId):
    yt_metadata_id: Optional[str] = None
    production_id: Optional[str] = None
    topic_id: Optional[str] = None
    plan_item_id: Optional[str] = None
    topic_text: Optional[str] = None
    locales: Optional[dict[str, Any]] = None
    youtube_video_ids: Optional[list[str]] = None
    posted_urls: Optional[list[dict[str, Any]]] = None


def _yt_meta_id(body: BaseModel) -> str | None:
    return getattr(body, "yt_metadata_id", None) or getattr(body, "production_id", None)


class ReportListBody(WithProjectId):
    pass


class ReportGetBody(BaseModel):
    """project_id optional when report_id alone is enough to resolve the row."""

    project_id: Optional[str] = None
    client_id: Optional[str] = None
    report_id: Optional[str] = None
    report_month: Optional[str] = None


class ReportUpsertBody(WithProjectId):
    report_month: str
    status: str = "draft"
    narrative: Any = None
    html: Optional[str] = None
    pdf_path: Optional[str] = None


class ReportRefineBody(WithProjectId):
    report_id: str
    prompt: str = ""
    narrative: Any = None


# --- channels ---


@router.post("/channel.list")
def channel_list(body: ProjectBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    rows = list(channels_col().find({"project_id": body.project_id}, {"_id": 0}))
    return {"channels": jsonable_encoder(rows)}


@router.post("/channel.get")
def channel_get(body: ChannelGetBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    doc = channels_col().find_one(
        {"id": body.channel_id, "project_id": body.project_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Channel not found")
    return _clean(doc)


@router.post("/channel.upsert")
def channel_upsert(body: ChannelUpsertBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    existing = channels_col().find_one(
        {"id": body.channel_id, "project_id": body.project_id}, {"_id": 0}
    )
    if existing:
        patch = body.model_dump(exclude={"project_id", "client_id", "channel_id"})
        patch["updated_at"] = utc_now()
        channels_col().update_one(
            {"id": body.channel_id, "project_id": body.project_id}, {"$set": patch}
        )
    else:
        doc = Channel(
            id=body.channel_id,
            project_id=body.project_id,
            **body.model_dump(exclude={"project_id", "client_id", "channel_id"}),
        ).model_dump(mode="json")
        channels_col().insert_one(doc)
    return _clean(
        channels_col().find_one(
            {"id": body.channel_id, "project_id": body.project_id}, {"_id": 0}
        )
    )


@router.post("/channel.update")
def channel_update(body: ChannelUpdateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    if not channels_col().find_one(
        {"id": body.channel_id, "project_id": body.project_id}
    ):
        raise HTTPException(404, "Channel not found")
    patch = {"updated_at": utc_now()}
    for key in ("title", "description", "language", "secret_id"):
        val = getattr(body, key)
        if val is not None:
            patch[key] = val
    if len(patch) == 1:
        raise HTTPException(400, "No fields to update")
    channels_col().update_one(
        {"id": body.channel_id, "project_id": body.project_id}, {"$set": patch}
    )
    return _clean(
        channels_col().find_one(
            {"id": body.channel_id, "project_id": body.project_id}, {"_id": 0}
        )
    )


@router.post("/channel.disconnect")
def channel_disconnect(body: ChannelGetBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    result = channels_col().update_one(
        {"id": body.channel_id, "project_id": body.project_id},
        {"$set": {"secret_id": None, "updated_at": utc_now()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Channel not found")
    return _clean(
        channels_col().find_one(
            {"id": body.channel_id, "project_id": body.project_id}, {"_id": 0}
        )
    )


@router.post("/channel.delete")
def channel_delete(body: ChannelGetBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    result = channels_col().delete_one(
        {"id": body.channel_id, "project_id": body.project_id}
    )
    if result.deleted_count == 0:
        raise HTTPException(404, "Channel not found")
    return {"deleted": True, "channel_id": body.channel_id}


# --- videos ---


@router.post("/video.list")
def video_list(body: VideoListBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    query: dict[str, Any] = {"project_id": body.project_id}
    if body.channel_id:
        query["channel_id"] = body.channel_id
    rows = list(videos_col().find(query, {"_id": 0}).sort("published_at", -1))
    return {"videos": jsonable_encoder(rows)}


@router.post("/video.get")
def video_get(body: VideoGetBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    doc = videos_col().find_one(
        {"id": body.video_id, "project_id": body.project_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Video not found")
    return _clean(doc)


@router.post("/video.upsert")
def video_upsert(body: VideoUpsertBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    existing = videos_col().find_one(
        {"id": body.video_id, "project_id": body.project_id}, {"_id": 0}
    )
    payload = body.model_dump(exclude={"project_id", "client_id", "video_id"})
    if existing:
        payload["updated_at"] = utc_now()
        videos_col().update_one(
            {"id": body.video_id, "project_id": body.project_id}, {"$set": payload}
        )
    else:
        doc = Video(
            id=body.video_id,
            project_id=body.project_id,
            **payload,
        ).model_dump(mode="json")
        videos_col().insert_one(doc)
    return _clean(
        videos_col().find_one(
            {"id": body.video_id, "project_id": body.project_id}, {"_id": 0}
        )
    )


@router.post("/video.update")
def video_update(body: VideoUpdateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    if not videos_col().find_one({"id": body.video_id, "project_id": body.project_id}):
        raise HTTPException(404, "Video not found")
    patch = {"updated_at": utc_now()}
    data = body.model_dump(exclude={"project_id", "client_id", "video_id"}, exclude_none=True)
    patch.update(data)
    if len(patch) == 1:
        raise HTTPException(400, "No fields to update")
    videos_col().update_one(
        {"id": body.video_id, "project_id": body.project_id}, {"$set": patch}
    )
    return _clean(
        videos_col().find_one(
            {"id": body.video_id, "project_id": body.project_id}, {"_id": 0}
        )
    )


@router.post("/video.delete")
def video_delete(body: VideoGetBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    result = videos_col().delete_one(
        {"id": body.video_id, "project_id": body.project_id}
    )
    if result.deleted_count == 0:
        raise HTTPException(404, "Video not found")
    return {"deleted": True, "video_id": body.video_id}


@router.post("/video.analytics")
def video_analytics(body: VideoAnalyticsBody, auth: dict = Depends(current_user)):
    """Aggregate from stored video docs (live YouTube Analytics can plug in later)."""
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    query: dict[str, Any] = {"project_id": body.project_id}
    if body.channel_id:
        query["channel_id"] = body.channel_id
    rows = list(videos_col().find(query, {"_id": 0}))
    totals = {
        "video_count": len(rows),
        "view_count": sum(int(v.get("view_count") or 0) for v in rows),
        "like_count": sum(int(v.get("like_count") or 0) for v in rows),
        "comment_count": sum(int(v.get("comment_count") or 0) for v in rows),
    }
    return {
        "project_id": body.project_id,
        "channel_id": body.channel_id,
        "start_date": body.start_date,
        "end_date": body.end_date,
        "totals": totals,
        "videos": jsonable_encoder(rows),
    }


# --- yt_metadata (legacy routes: production.*) ---


@router.post("/yt_metadata.list")
@router.post("/production.list")
def yt_metadata_list(body: YtMetadataListBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    if is_client(auth):
        return {"yt_metadata": [], "productions": []}
    query: dict[str, Any] = {"project_id": body.project_id}
    if body.topic_id:
        query["topic_id"] = body.topic_id
    rows = list(yt_metadata_col().find(query, {"_id": 0}).sort("updated_at", -1))
    encoded = jsonable_encoder(rows)
    return {"yt_metadata": encoded, "productions": encoded}


@router.post("/yt_metadata.get")
@router.post("/production.get")
def yt_metadata_get(body: YtMetadataGetBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    mid = _yt_meta_id(body)
    if not mid:
        raise HTTPException(400, "yt_metadata_id is required")
    doc = yt_metadata_col().find_one(
        {"id": mid, "project_id": body.project_id}, {"_id": 0}
    )
    if not doc or filter_yt_metadata_for_viewer(doc, auth) is None:
        raise HTTPException(404, "yt_metadata not found")
    return _clean(doc)


@router.post("/yt_metadata.upsert")
@router.post("/production.upsert")
def yt_metadata_upsert(body: YtMetadataUpsertBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    mid = _yt_meta_id(body)
    exclude = {"project_id", "client_id", "production_id", "yt_metadata_id"}
    if mid:
        existing = yt_metadata_col().find_one(
            {"id": mid, "project_id": body.project_id}, {"_id": 0}
        )
        if not existing:
            raise HTTPException(404, "yt_metadata not found")
        patch = body.model_dump(exclude=exclude, exclude_none=True)
        patch["updated_at"] = utc_now()
        yt_metadata_col().update_one(
            {"id": mid, "project_id": body.project_id}, {"$set": patch}
        )
        pid = mid
    else:
        doc = YtMetadata(
            project_id=body.project_id,
            topic_id=body.topic_id,
            plan_item_id=body.plan_item_id,
            topic_text=body.topic_text,
            locales=body.locales,
            youtube_video_ids=body.youtube_video_ids,
            posted_urls=body.posted_urls,
        ).model_dump(mode="json")
        yt_metadata_col().insert_one(doc)
        pid = doc["id"]
    return _clean(
        yt_metadata_col().find_one({"id": pid, "project_id": body.project_id}, {"_id": 0})
    )


@router.post("/yt_metadata.update")
@router.post("/production.update")
def yt_metadata_update(body: YtMetadataUpdateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    mid = _yt_meta_id(body)
    if not mid:
        raise HTTPException(400, "yt_metadata_id is required")
    if not yt_metadata_col().find_one({"id": mid, "project_id": body.project_id}):
        raise HTTPException(404, "yt_metadata not found")
    patch = body.model_dump(
        exclude={"project_id", "client_id", "production_id", "yt_metadata_id"},
        exclude_none=True,
    )
    patch["updated_at"] = utc_now()
    if len(patch) == 1:
        raise HTTPException(400, "No fields to update")
    yt_metadata_col().update_one(
        {"id": mid, "project_id": body.project_id}, {"$set": patch}
    )
    return _clean(
        yt_metadata_col().find_one({"id": mid, "project_id": body.project_id}, {"_id": 0})
    )


@router.post("/yt_metadata.delete")
@router.post("/production.delete")
def yt_metadata_delete(body: YtMetadataGetBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    mid = _yt_meta_id(body)
    if not mid:
        raise HTTPException(400, "yt_metadata_id is required")
    result = yt_metadata_col().delete_one({"id": mid, "project_id": body.project_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "yt_metadata not found")
    return {"deleted": True, "yt_metadata_id": mid, "production_id": mid}


# --- monthly reports ---


@router.post("/report.list")
def report_list(body: ReportListBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    rows = list(
        monthly_reports_col()
        .find({"project_id": body.project_id}, {"_id": 0})
        .sort("report_month", -1)
    )
    return {
        "reports": [
            jsonable_encoder(filter_report_for_viewer(r, auth)) for r in rows
        ]
    }


@router.post("/report.get")
def report_get(body: ReportGetBody, auth: dict = Depends(current_user)):
    project_id = body.project_id or body.client_id
    if body.report_id and not project_id:
        doc = monthly_reports_col().find_one({"id": body.report_id}, {"_id": 0})
        if not doc:
            raise HTTPException(404, "Report not found")
        require_domain_access(auth["user_id"], doc["project_id"], DOMAIN)
        return jsonable_encoder(filter_report_for_viewer(doc, auth))

    if not project_id:
        raise HTTPException(400, "project_id is required")
    require_domain_access(auth["user_id"], project_id, DOMAIN)
    query: dict[str, Any] = {"project_id": project_id}
    if body.report_id:
        query["id"] = body.report_id
    elif body.report_month:
        query["report_month"] = body.report_month
    else:
        raise HTTPException(400, "report_id or report_month required")
    doc = monthly_reports_col().find_one(query, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Report not found")
    return jsonable_encoder(filter_report_for_viewer(doc, auth))


@router.post("/report.generate")
def report_generate(body: ReportUpsertBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    existing = monthly_reports_col().find_one(
        {"project_id": body.project_id, "report_month": body.report_month},
        {"_id": 0},
    )
    if existing:
        patch = {
            "status": body.status,
            "narrative": body.narrative,
            "html": body.html,
            "pdf_path": body.pdf_path,
            "updated_at": utc_now(),
        }
        monthly_reports_col().update_one({"id": existing["id"]}, {"$set": patch})
        doc = monthly_reports_col().find_one({"id": existing["id"]}, {"_id": 0})
    else:
        doc = MonthlyReport(
            project_id=body.project_id,
            report_month=body.report_month,
            status=body.status,
            narrative=body.narrative,
            html=body.html,
            pdf_path=body.pdf_path,
        ).model_dump(mode="json")
        monthly_reports_col().insert_one(doc)
        doc.pop("_id", None)
    return jsonable_encoder(filter_report_for_viewer(doc, auth))


@router.post("/report.refine")
def report_refine(body: ReportRefineBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    doc = monthly_reports_col().find_one(
        {"id": body.report_id, "project_id": body.project_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Report not found")
    history = list(doc.get("refine_history") or [])
    history.append(
        {
            "prompt": body.prompt,
            "created_at": utc_now().isoformat(),
        }
    )
    patch = {
        "refine_history": history,
        "updated_at": utc_now(),
    }
    if body.narrative is not None:
        patch["narrative"] = body.narrative
    monthly_reports_col().update_one({"id": body.report_id}, {"$set": patch})
    updated = monthly_reports_col().find_one({"id": body.report_id}, {"_id": 0})
    return jsonable_encoder(filter_report_for_viewer(updated, auth))


@router.post("/report.delete")
def report_delete(body: ReportGetBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    if not body.report_id:
        raise HTTPException(400, "report_id required")
    result = monthly_reports_col().delete_one(
        {"id": body.report_id, "project_id": body.project_id}
    )
    if result.deleted_count == 0:
        raise HTTPException(404, "Report not found")
    return {"deleted": True, "report_id": body.report_id}
