"""Pure TG document → Beacon document transforms."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi.encoders import jsonable_encoder

from backend.main.models import (
    Access,
    Domain,
    PlanItem,
    ProfileField,
    ProfileSection,
    Project,
    ProjectSecret,
    ProjectStatus,
    SecretKind,
    Task,
    TaskKind,
    TaskNote,
    TaskSubtask,
    Topic,
    TopicSource,
    TopicWeight,
    User,
    UserType,
    new_id,
    utc_now,
)
from backend.socialmedia.models import SocialPost, SocialSchedule
from backend.videos.models import Channel, MonthlyReport, Video, YtMetadata


def _sid(value: Any) -> str:
    return str(value) if value is not None else ""


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    return utc_now()


def _dump(model) -> dict[str, Any]:
    return jsonable_encoder(model.model_dump(mode="json"))


def make_superuser(*, email: str, name: str, password_hash: str) -> dict[str, Any]:
    return _dump(
        User(
            email=email,
            name=name,
            password_hash=password_hash,
            type=UserType.INTERNAL,
            is_active=True,
        )
    )


def transform_topic(doc: dict[str, Any]) -> dict[str, Any]:
    weight = str(doc.get("weight") or "medium").lower()
    if weight not in ("high", "medium", "low"):
        weight = "medium"
    source = str(doc.get("source") or "manual").lower()
    if source not in ("manual", "auto"):
        source = "manual"
    topic = Topic(
        id=_sid(doc.get("id") or doc.get("_id")) or new_id("topic"),
        text=str(doc.get("text") or "").strip() or "Untitled",
        weight=TopicWeight(weight),
        source=TopicSource(source),
        trend_score=doc.get("trend_score"),
        recommendation_score=doc.get("recommendation_score"),
        trend_confidence=doc.get("trend_confidence"),
        web_interest=doc.get("web_interest"),
        youtube_interest=doc.get("youtube_interest"),
        momentum=doc.get("momentum"),
        rising_flag=doc.get("rising_flag"),
        trend_fetched_at=doc.get("trend_fetched_at"),
        recommendation_saved_at=doc.get("recommendation_saved_at"),
    )
    return _dump(topic)


def transform_profile_sections(doctor_ref: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not doctor_ref:
        return []
    sections = []
    for sec in doctor_ref.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        fields = []
        for field in sec.get("fields") or []:
            if not isinstance(field, dict):
                continue
            fields.append(
                ProfileField(
                    id=_sid(field.get("id")) or new_id("field"),
                    label=str(field.get("label") or ""),
                    value=str(field.get("value") or ""),
                )
            )
        sections.append(
            ProfileSection(
                id=_sid(sec.get("id")) or new_id("section"),
                title=str(sec.get("title") or "Section"),
                fields=fields,
            )
        )
    return [_dump(s) for s in sections]


def extract_content_plan(plan_doc: dict[str, Any] | None) -> dict[str, Any]:
    """Keep the full TG content_suggestions payload for Content Plan UI."""
    if not plan_doc:
        return {}
    suggestions = dict(plan_doc.get("content_suggestions") or {})
    coverage = suggestions.get("coverage") or plan_doc.get("content_topic_coverage")
    if coverage and not suggestions.get("coverage"):
        suggestions["coverage"] = coverage
    # Prefer top-level keyword_analysis if nested empty
    if not suggestions.get("keyword_analysis") and plan_doc.get("keyword_analysis"):
        suggestions["keyword_analysis"] = plan_doc.get("keyword_analysis")
    return suggestions


def transform_project(
    client: dict[str, Any],
    topics: list[dict[str, Any]],
    doctor_ref: dict[str, Any] | None = None,
    content_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_id = _sid(client.get("id") or client.get("_id"))
    if not project_id:
        raise ValueError("client missing id")
    topic_rows = [transform_topic(t) for t in topics]
    project = Project(
        id=project_id,
        name=str(client.get("name") or "Untitled").strip() or "Untitled",
        status=ProjectStatus.ACTIVE,
        website_url=client.get("website_url"),
        specialty=client.get("specialty"),
        designation=client.get("designation"),
        description=client.get("description"),
        reference_youtube_channel=client.get("reference_youtube_channel"),
        ai_videos_started_from=client.get("ai_videos_started_from"),
        profile_sections=[
            ProfileSection.model_validate(s)
            for s in transform_profile_sections(doctor_ref)
        ],
        topics=[Topic.model_validate(t) for t in topic_rows],
        content_plan=dict(content_plan or {}),
        created_at=_parse_dt(client.get("created_at")),
        updated_at=_parse_dt(client.get("updated_at")),
    )
    return _dump(project)


def make_access(user_id: str, project_id: str, domain: Domain) -> dict[str, Any]:
    return _dump(Access(user_id=user_id, project_id=project_id, domain=domain))


def transform_channel(
    doc: dict[str, Any], *, project_id: str, secret_id: Optional[str] = None
) -> dict[str, Any]:
    channel_id = _sid(doc.get("id") or doc.get("_id"))
    return _dump(
        Channel(
            id=channel_id,
            project_id=project_id,
            title=str(doc.get("title") or ""),
            description=str(doc.get("description") or ""),
            custom_url=doc.get("custom_url"),
            published_at=doc.get("published_at"),
            view_count=int(doc.get("view_count") or 0),
            subscriber_count=int(doc.get("subscriber_count") or 0),
            video_count=int(doc.get("video_count") or 0),
            language=doc.get("language"),
            secret_id=secret_id,
            created_at=_parse_dt(doc.get("created_at")),
            updated_at=_parse_dt(doc.get("updated_at")),
        )
    )


def transform_youtube_secret(
    channel: dict[str, Any], *, project_id: str
) -> dict[str, Any] | None:
    creds = channel.get("google_credentials")
    if not isinstance(creds, dict) or not creds:
        return None
    channel_id = _sid(channel.get("id") or channel.get("_id"))
    return _dump(
        ProjectSecret(
            project_id=project_id,
            kind=SecretKind.OAUTH,
            provider="youtube",
            label=str(channel.get("title") or channel_id or "YouTube"),
            status="active",
            scopes=list(creds.get("scopes") or []),
            refresh_token_encrypted=creds.get("refresh_token"),
            access_token_encrypted=creds.get("token") or creds.get("access_token"),
            external_account_id=channel_id,
            external_account_name=channel.get("title"),
            metadata={
                "token_uri": creds.get("token_uri"),
                "client_id": creds.get("client_id"),
                "client_secret": creds.get("client_secret"),
                "expiry": creds.get("expiry"),
            },
        )
    )


def transform_manual_credentials(
    creds_doc: dict[str, Any], *, project_id: str
) -> list[dict[str, Any]]:
    out = []
    for row in creds_doc.get("credentials") or []:
        if not isinstance(row, dict):
            continue
        out.append(
            _dump(
                ProjectSecret(
                    id=_sid(row.get("id")) or new_id("secret"),
                    project_id=project_id,
                    kind=SecretKind.MANUAL,
                    provider=str(row.get("service") or "portal"),
                    label=str(row.get("service") or "Credential"),
                    status="active",
                    username=row.get("username"),
                    secret_encrypted=row.get("password"),
                    metadata={"notes": row.get("notes") or ""},
                )
            )
        )
    return out


def transform_app_config(
    doc: dict[str, Any], *, project_id: str, provider: str
) -> dict[str, Any] | None:
    if not doc:
        return None
    app_id = doc.get("app_id")
    app_secret = doc.get("app_secret")
    if not app_id and not app_secret:
        return None
    return _dump(
        ProjectSecret(
            project_id=project_id,
            kind=SecretKind.APP_CONFIG,
            provider=provider,
            label=f"{provider} app",
            status="active",
            username=str(app_id) if app_id else None,
            secret_encrypted=app_secret,
            metadata={"app_id": app_id},
        )
    )


def transform_ig_connection(
    doc: dict[str, Any], *, project_id: str
) -> dict[str, Any] | None:
    if not doc or not (doc.get("access_token") or doc.get("instagram_user_id")):
        return None
    return _dump(
        ProjectSecret(
            project_id=project_id,
            kind=SecretKind.OAUTH,
            provider="instagram",
            label=str(doc.get("instagram_username") or "Instagram"),
            status="active",
            access_token_encrypted=doc.get("access_token"),
            external_account_id=doc.get("instagram_user_id"),
            external_account_name=doc.get("instagram_username"),
            metadata={
                "permissions": doc.get("permissions"),
                "token_type": doc.get("token_type"),
                "expires_in": doc.get("expires_in"),
            },
        )
    )


def transform_fb_connection(
    doc: dict[str, Any], *, project_id: str
) -> dict[str, Any] | None:
    if not doc or not (
        doc.get("access_token")
        or doc.get("page_access_token")
        or doc.get("facebook_user_id")
    ):
        return None
    return _dump(
        ProjectSecret(
            project_id=project_id,
            kind=SecretKind.OAUTH,
            provider="facebook",
            label=str(doc.get("selected_page_name") or "Facebook"),
            status="active",
            access_token_encrypted=doc.get("page_access_token")
            or doc.get("access_token"),
            external_account_id=doc.get("selected_page_id")
            or doc.get("facebook_user_id"),
            external_account_name=doc.get("selected_page_name"),
            metadata={
                "facebook_user_id": doc.get("facebook_user_id"),
                "user_access_token": doc.get("access_token"),
                "page_access_token": doc.get("page_access_token"),
                "selected_page_id": doc.get("selected_page_id"),
                "selected_page_name": doc.get("selected_page_name"),
            },
        )
    )


def transform_video(doc: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    duration = doc.get("duration_seconds")
    if duration is None and doc.get("duration") is not None:
        try:
            duration = int(doc.get("duration"))
        except (TypeError, ValueError):
            duration = None
    return _dump(
        Video(
            id=_sid(doc.get("id") or doc.get("_id")),
            project_id=project_id,
            channel_id=_sid(doc.get("channel_id")),
            title=str(doc.get("title") or ""),
            published_at=str(doc.get("published_at") or ""),
            thumbnail_url=doc.get("thumbnail_url"),
            view_count=int(doc.get("view_count") or 0),
            like_count=int(doc.get("like_count") or 0),
            comment_count=int(doc.get("comment_count") or 0),
            duration_seconds=duration,
            is_short=bool(doc.get("is_short")),
            privacy_status=str(doc.get("privacy_status") or "public"),
            topic_id=doc.get("topic_id"),
            notes=str(doc.get("notes") or ""),
            metadata_fields=dict(doc.get("metadata_fields") or {}),
            created_at=_parse_dt(doc.get("created_at")),
            updated_at=_parse_dt(doc.get("updated_at")),
        )
    )


def transform_plan_items(
    plan_doc: dict[str, Any], *, project_id: str
) -> list[dict[str, Any]]:
    suggestions = plan_doc.get("content_suggestions") or {}
    items = suggestions.get("items") or []
    out = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        title = (
            item.get("title_en")
            or item.get("title_hinglish")
            or item.get("topic_text")
            or item.get("title")
            or "Untitled"
        )
        status = "scripted" if item.get("script") else "planned"
        out.append(
            _dump(
                PlanItem(
                    id=_sid(item.get("id")) or new_id("plan"),
                    project_id=project_id,
                    topic_id=item.get("topic_id"),
                    title=str(title),
                    format=str(item.get("format") or item.get("video_type") or "long"),
                    status=status,
                    script=str(item.get("script") or ""),
                    sort_order=idx,
                    created_at=_parse_dt(item.get("created_at") or plan_doc.get("updated_at")),
                    updated_at=_parse_dt(item.get("updated_at") or plan_doc.get("updated_at")),
                )
            )
        )
    return out


def transform_production(doc: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    posted_urls: list[dict[str, Any]] = []
    youtube_ids: list[str] = []
    for platform, key in (
        ("youtube", "youtube_urls"),
        ("instagram", "instagram_urls"),
        ("facebook", "facebook_urls"),
    ):
        for entry in doc.get(key) or []:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url") or ""
            posted_urls.append(
                {
                    "platform": platform,
                    "url": url,
                    "language": entry.get("language"),
                    "posted_at": entry.get("posted_at"),
                }
            )
            if platform == "youtube":
                vid = entry.get("video_id") or entry.get("youtube_video_id")
                if vid:
                    youtube_ids.append(str(vid))
    for entry in doc.get("source_urls") or []:
        if isinstance(entry, dict) and entry.get("url"):
            posted_urls.append(
                {
                    "platform": entry.get("kind") or "source",
                    "url": entry.get("url"),
                    "language": entry.get("language"),
                    "posted_at": entry.get("posted_at"),
                }
            )
    prod_id = _sid(doc.get("id") or doc.get("_id")) or new_id("yt_metadata")
    return _dump(
        YtMetadata(
            id=prod_id,
            project_id=project_id,
            topic_id=doc.get("topic_id"),
            plan_item_id=doc.get("content_plan_item_id") or doc.get("plan_item_id"),
            topic_text=str(doc.get("topic_text") or ""),
            locales=dict(doc.get("yt_locales") or doc.get("locales") or {}),
            youtube_video_ids=youtube_ids,
            posted_urls=posted_urls,
            created_at=_parse_dt(doc.get("created_at")),
            updated_at=_parse_dt(doc.get("updated_at")),
        )
    )


def transform_report(doc: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    return _dump(
        MonthlyReport(
            id=_sid(doc.get("id") or doc.get("_id")) or new_id("report"),
            project_id=project_id,
            report_month=str(doc.get("report_month") or ""),
            status=str(doc.get("status") or "draft"),
            narrative=doc.get("narrative"),
            html=doc.get("html") or doc.get("html_url"),
            pdf_path=doc.get("pdf_path") or doc.get("pdf_url"),
            refine_history=list(doc.get("refine_history") or []),
            created_at=_parse_dt(doc.get("created_at")),
            updated_at=_parse_dt(doc.get("updated_at")),
        )
    )


def _map_social_status(doc: dict[str, Any]) -> str:
    status = str(doc.get("status") or "").lower()
    publish = str(doc.get("publish_status") or "").lower()
    if publish == "published" or status == "published":
        return "published"
    if publish == "scheduled" or status in ("queued", "scheduled"):
        if doc.get("queue_order") is not None or status == "queued":
            return "queued"
        return "queued"
    if doc.get("queue_order") is not None and publish != "draft":
        return "queued"
    return "draft"


def transform_social_post(doc: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    external: dict[str, Any] = dict(doc.get("external_ids") or {})
    if doc.get("instagram_post_id"):
        external["instagram_post_id"] = doc["instagram_post_id"]
    if doc.get("facebook_post_id"):
        external["facebook_post_id"] = doc["facebook_post_id"]
    if doc.get("instagram_permalink"):
        external["instagram_permalink"] = doc["instagram_permalink"]
    if doc.get("facebook_permalink"):
        external["facebook_permalink"] = doc["facebook_permalink"]
    targets = doc.get("publish_targets")
    if not targets:
        platform = doc.get("platform")
        targets = [platform] if platform else ["instagram"]
    return _dump(
        SocialPost(
            id=_sid(doc.get("id") or doc.get("_id")) or new_id("spost"),
            project_id=project_id,
            source_type=str(doc.get("source_type") or "keyword"),
            topic_id=doc.get("topic_id"),
            plan_item_id=doc.get("content_plan_item_id") or doc.get("plan_item_id"),
            brief=dict(doc.get("brief") or {}),
            image_url=doc.get("image_url"),
            status=_map_social_status(doc),
            publish_targets=list(targets),
            queue_order=doc.get("queue_order"),
            external_ids=external,
            created_at=_parse_dt(doc.get("created_at")),
            updated_at=_parse_dt(doc.get("updated_at")),
        )
    )


def transform_social_schedule(
    doc: dict[str, Any], *, project_id: str
) -> dict[str, Any]:
    return _dump(
        SocialSchedule(
            id=_sid(doc.get("id")) or new_id("ssched"),
            project_id=project_id,
            frequency=str(doc.get("frequency") or "off"),
            selected_days=list(doc.get("selected_days") or []),
            posts_per_day=int(doc.get("posts_per_day") or 1),
            auto_fallback=bool(doc.get("auto_fallback")),
            facebook_auto_publish=bool(doc.get("facebook_auto_publish")),
            festive_auto_publish=bool(doc.get("festive_auto_publish")),
            festive_facebook_auto_publish=bool(
                doc.get("festive_facebook_auto_publish")
            ),
            updated_at=_parse_dt(doc.get("updated_at")),
        )
    )


def _note_list(rows: list | None, *, visibility: str) -> list[TaskNote]:
    notes = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        text = row.get("text") or ""
        if row.get("attachments"):
            text = (text + "\n" + str(row.get("attachments"))).strip()
        notes.append(
            TaskNote(
                id=_sid(row.get("id")) or new_id("note"),
                text=str(text),
                visibility=visibility,
                created_by=str(row.get("created_by") or ""),
                created_at=_parse_dt(row.get("created_at")),
            )
        )
    return notes


def transform_weekly_tracker(doc: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    """Keep TG week document shape — do not flatten cards into tasks."""
    year = int(doc.get("year") or 0)
    month = int(doc.get("month") or 0)
    week = int(doc.get("week") or 0)
    doc_id = _sid(doc.get("id")) or f"weekly:{project_id}:{year}:{month}:{week}"
    return {
        "id": doc_id,
        "project_id": project_id,
        "client_id": project_id,
        "year": year,
        "month": month,
        "week": week,
        "cards": list(doc.get("cards") or []),
        "languages": list(doc.get("languages") or []),
        "updated_at": doc.get("updated_at") or utc_now().isoformat(),
        "updated_by": doc.get("updated_by") or "",
    }


def transform_custom_tracker(doc: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    """Keep TG custom todo list shape — separate from weekly boards."""
    tasks = []
    for row in doc.get("tasks") or []:
        if not isinstance(row, dict):
            continue
        tasks.append(
            {
                "id": _sid(row.get("id")) or new_id("tsk").replace("tsk:", "tsk-"),
                "title": str(row.get("title") or "").strip(),
                "done": bool(row.get("done")),
                "due_date": str(row.get("due_date") or "")[:10],
                "comment": str(row.get("comment") or "").strip(),
            }
        )
    return {
        "id": _sid(doc.get("id")) or f"custom:{project_id}",
        "project_id": project_id,
        "client_id": project_id,
        "tasks": tasks,
        "updated_at": doc.get("updated_at") or utc_now().isoformat(),
        "updated_by": doc.get("updated_by") or "",
    }
