"""TG frontend path aliases. client_id maps to project_id via domain CRUDL bodies."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.socialmedia import crudl as social

from .auth import current_user
from .main_crudl import (
    ProjectCreateBody,
    ProjectIdBody,
    ProjectUpdateBody,
    project_create,
    project_delete,
    project_get,
    project_list,
    project_update,
)
from .models import Domain

router = APIRouter(tags=["tg-compat"])


class ClientIdBody(BaseModel):
    client_id: str


class ClientUpdateCompat(BaseModel):
    client_id: str
    name: Optional[str] = None
    website_url: Optional[str] = None
    specialty: Optional[str] = None
    designation: Optional[str] = None
    description: Optional[str] = None
    reference_youtube_channel: Optional[str] = None
    ai_videos_started_from: Optional[str] = None
    topics: Optional[list] = None
    is_active: Optional[bool] = None
    onboarding_date: Optional[str] = None
    tracker_start_year: Optional[int] = None
    tracker_start_month: Optional[int] = None
    tracker_start_week: Optional[int] = None
    tracker_deliverables: Optional[list] = None


def _client_row(p: dict, channel_count: int) -> dict:
    from backend.trackers.tracker_settings import stored_monthly_slots
    from .models import ProjectStatus

    status = str(p.get("status") or ProjectStatus.ACTIVE.value)
    is_active = status != ProjectStatus.ARCHIVED.value
    return {
        "id": p["id"],
        "name": p["name"],
        "channel_count": channel_count,
        "website_url": p.get("website_url"),
        "specialty": p.get("specialty"),
        "designation": p.get("designation"),
        "description": p.get("description"),
        "reference_youtube_channel": p.get("reference_youtube_channel"),
        "ai_videos_started_from": p.get("ai_videos_started_from"),
        "topics": p.get("topics") or [],
        "domains": p.get("domains") or [],
        "owner_user_id": p.get("owner_user_id"),
        "is_owner": bool(p.get("is_owner")),
        "is_active": is_active,
        "status": status,
        "onboarding_date": p.get("onboarding_date"),
        "tracker_start_year": p.get("tracker_start_year"),
        "tracker_start_month": p.get("tracker_start_month"),
        "tracker_start_week": p.get("tracker_start_week"),
        "tracker_deliverables": stored_monthly_slots(p),
        "tracker_deliverables_period": p.get("tracker_deliverables_period") or "",
    }


def _clients_payload(auth: dict) -> dict:
    from .db import channels_col

    data = project_list(auth)
    clients = []
    for p in data["projects"]:
        clients.append(
            _client_row(p, channels_col().count_documents({"project_id": p["id"]}))
        )
    return {
        "clients": clients,
        "active_client_id": None,
        "active_channel_id": None,
    }


@router.post("/client.list")
def client_list(auth: dict = Depends(current_user)):
    return _clients_payload(auth)


@router.post("/client.create")
def client_create(body: dict, auth: dict = Depends(current_user)):
    name = ((body or {}).get("name") or "Untitled").strip()
    # project_create sets owner_user_id + default domain grants
    project_create(ProjectCreateBody(name=name), auth)
    return _clients_payload(auth)


@router.post("/client.update")
def client_update(body: ClientUpdateCompat, auth: dict = Depends(current_user)):
    from .models import Topic

    topics = None
    if body.topics is not None:
        topics = []
        for item in body.topics:
            if isinstance(item, dict):
                topics.append(Topic(**item) if "text" in item else Topic(text=str(item.get("title") or item)))
            else:
                topics.append(Topic(text=str(item)))

    project_update(
        ProjectUpdateBody(
            project_id=body.client_id,
            name=body.name,
            website_url=body.website_url,
            specialty=body.specialty,
            designation=body.designation,
            description=body.description,
            reference_youtube_channel=body.reference_youtube_channel,
            ai_videos_started_from=body.ai_videos_started_from,
            topics=topics,
            is_active=body.is_active,
            onboarding_date=body.onboarding_date,
            tracker_start_year=body.tracker_start_year,
            tracker_start_month=body.tracker_start_month,
            tracker_start_week=body.tracker_start_week,
            tracker_deliverables=body.tracker_deliverables,
        ),
        auth,
    )
    return _clients_payload(auth)


@router.post("/client.delete")
def client_delete(body: ClientIdBody, auth: dict = Depends(current_user)):
    project_delete(ProjectIdBody(project_id=body.client_id), auth)
    return _clients_payload(auth)


@router.post("/client.select")
def client_select(body: ClientIdBody, auth: dict = Depends(current_user)):
    project_get(ProjectIdBody(project_id=body.client_id), auth)
    return _clients_payload(auth)


# Path name aliases (TG → Beacon)


class SocialProjectCompat(BaseModel):
    client_id: Optional[str] = None
    project_id: Optional[str] = None


@router.post("/social.post-sources.get")
def social_post_sources_get(
    body: SocialProjectCompat, auth: dict = Depends(current_user)
):
    """Keywords/scripts sources for the generate UI — from project.topics + plan stubs."""
    from .access_guards import require_domain_access
    from .main_crudl import find_project

    project_id = body.project_id or body.client_id
    require_domain_access(auth["user_id"], project_id, Domain.SOCIALMEDIA)
    project = find_project(project_id)
    keywords = []
    for t in project.get("topics") or []:
        keywords.append(
            {
                "topic_id": t.get("id"),
                "topic_text": t.get("text"),
                "recommendation_score": t.get("recommendation_score") or 0,
            }
        )
    return {
        "recommended_keywords": keywords,
        "scripted_items": [],
    }


@router.post("/social.posts.source.get")
def social_posts_source_get(
    body: dict, auth: dict = Depends(current_user)
):
    project_id = (body or {}).get("project_id") or (body or {}).get("client_id")
    return social.social_post_list(
        social.PostListBody(project_id=project_id, status=(body or {}).get("status")),
        auth,
    )


class SocialScheduleSaveCompat(BaseModel):
    client_id: Optional[str] = None
    project_id: Optional[str] = None
    frequency: str = "off"
    selected_days: list[str] = Field(default_factory=list)
    auto_fallback: bool = False
    facebook_auto_publish: bool = False
    festive_auto_publish: bool = False
    festive_facebook_auto_publish: bool = False
    posts_per_day: int = 1


@router.post("/social.schedule.save")
def social_schedule_save_compat(
    body: SocialScheduleSaveCompat, auth: dict = Depends(current_user)
):
    return social.social_schedule_update(
        social.ScheduleUpdateBody(
            project_id=body.project_id,
            client_id=body.client_id,
            frequency=body.frequency,
            selected_days=body.selected_days,
            auto_fallback=body.auto_fallback,
            facebook_auto_publish=body.facebook_auto_publish,
            festive_auto_publish=body.festive_auto_publish,
            festive_facebook_auto_publish=body.festive_facebook_auto_publish,
            posts_per_day=body.posts_per_day,
        ),
        auth,
    )


class SocialPostDraftCompat(BaseModel):
    client_id: Optional[str] = None
    project_id: Optional[str] = None
    source_type: str = "keyword"
    topic_id: Optional[str] = None
    content_plan_item_id: Optional[str] = None
    topic_text: Optional[str] = None
    custom_prompt: Optional[str] = None


@router.post("/social.post-draft.generate")
def social_post_draft_generate_compat(
    body: SocialPostDraftCompat, auth: dict = Depends(current_user)
):
    brief = {}
    if body.topic_text:
        brief["caption"] = body.topic_text
    if body.custom_prompt:
        brief["supporting_text"] = body.custom_prompt
    return social.social_post_generate(
        social.PostGenerateBody(
            project_id=body.project_id,
            client_id=body.client_id,
            source_type=body.source_type,
            topic_id=body.topic_id,
            plan_item_id=body.content_plan_item_id,
            brief=brief,
        ),
        auth,
    )


class SocialPublishCompat(BaseModel):
    client_id: Optional[str] = None
    project_id: Optional[str] = None
    post_id: str
    caption: Optional[str] = None
    targets: list[str] = Field(default_factory=lambda: ["instagram"])


@router.post("/social.post.publish")
def social_post_publish_compat(
    body: SocialPublishCompat, auth: dict = Depends(current_user)
):
    if body.caption:
        social.social_post_update(
            social.PostUpdateBody(
                project_id=body.project_id,
                client_id=body.client_id,
                post_id=body.post_id,
                brief={"caption": body.caption},
                publish_targets=body.targets,
            ),
            auth,
        )
    return social.social_post_publish(
        social.PostPublishBody(
            project_id=body.project_id,
            client_id=body.client_id,
            post_id=body.post_id,
        ),
        auth,
    )


# --- profile / credentials (project-wide) ---


class DoctorRefBody(BaseModel):
    client_id: Optional[str] = None
    project_id: Optional[str] = None
    sections: Optional[list] = None


@router.post("/client.doctor-reference.get")
def doctor_reference_get(body: DoctorRefBody, auth: dict = Depends(current_user)):
    from .access_guards import require_project_access
    from .main_crudl import find_project

    project_id = body.project_id or body.client_id
    require_project_access(auth["user_id"], project_id)
    project = find_project(project_id)
    from backend.trackers.editors import ensure_editor_sections

    return {
        "client_id": project_id,
        "sections": ensure_editor_sections(
            project.get("profile_sections") or [],
            project.get("video_editor_id") or "",
            project=project,
        ),
    }


@router.post("/client.doctor-reference.save")
def doctor_reference_save(body: DoctorRefBody, auth: dict = Depends(current_user)):
    from .access_guards import require_internal, require_project_access
    from .db import projects_col
    from .main_crudl import find_project
    from .models import utc_now
    from backend.trackers.editors import editor_value_from_sections, ensure_editor_sections, hours_values_from_sections

    require_internal(auth)
    project_id = body.project_id or body.client_id
    require_project_access(auth["user_id"], project_id)
    project = find_project(project_id)
    sections = ensure_editor_sections(body.sections or [], project=project)
    hours = hours_values_from_sections(sections, project)
    projects_col().update_one(
        {"id": project_id},
        {
            "$set": {
                "profile_sections": sections,
                "video_editor_id": editor_value_from_sections(sections) or None,
                "long_video_hours": hours["long_video_hours"],
                "short_video_hours": hours["short_video_hours"],
                "updated_at": utc_now(),
            }
        },
    )
    project = find_project(project_id)
    return {
        "client_id": project_id,
        "sections": project.get("profile_sections") or [],
    }


class CredentialsBody(BaseModel):
    client_id: Optional[str] = None
    project_id: Optional[str] = None
    credentials: Optional[list] = None


@router.post("/client.credentials.get")
def credentials_get(body: CredentialsBody, auth: dict = Depends(current_user)):
    from .access_guards import require_internal, require_project_access
    from .db import project_secrets_col

    require_internal(auth)
    project_id = body.project_id or body.client_id
    require_project_access(auth["user_id"], project_id)
    rows = list(
        project_secrets_col().find(
            {"project_id": project_id, "kind": "manual"}, {"_id": 0}
        )
    )
    credentials = [
        {
            "id": r.get("id"),
            "service": r.get("provider"),
            "username": r.get("username"),
            "password": r.get("secret_encrypted"),
            "notes": (r.get("metadata") or {}).get("notes") or "",
        }
        for r in rows
    ]
    return {"client_id": project_id, "credentials": credentials}


@router.post("/client.credentials.save")
def credentials_save(body: CredentialsBody, auth: dict = Depends(current_user)):
    from .access_guards import require_internal, require_project_access
    from .db import project_secrets_col
    from .models import ProjectSecret, SecretKind, utc_now

    require_internal(auth)
    project_id = body.project_id or body.client_id
    require_project_access(auth["user_id"], project_id)
    project_secrets_col().delete_many({"project_id": project_id, "kind": "manual"})
    for row in body.credentials or []:
        if not isinstance(row, dict):
            continue
        fields = dict(
            project_id=project_id,
            kind=SecretKind.MANUAL,
            provider=str(row.get("service") or "portal"),
            label=str(row.get("service") or "Credential"),
            username=row.get("username"),
            secret_encrypted=row.get("password"),
            metadata={"notes": row.get("notes") or ""},
        )
        if row.get("id"):
            fields["id"] = row["id"]
        project_secrets_col().insert_one(ProjectSecret(**fields).model_dump(mode="json"))
    return credentials_get(body, auth)


class SocialConfigBody(BaseModel):
    client_id: Optional[str] = None
    project_id: Optional[str] = None
    app_id: Optional[str] = None
    app_secret: Optional[str] = None


def _social_app_get(project_id: str, provider: str) -> dict:
    from .db import project_secrets_col

    doc = project_secrets_col().find_one(
        {"project_id": project_id, "provider": provider, "kind": "app_config"},
        {"_id": 0},
    )
    if not doc:
        return {"client_id": project_id, "app_id": "", "app_secret": "", "configured": False}
    return {
        "client_id": project_id,
        "app_id": doc.get("username") or (doc.get("metadata") or {}).get("app_id") or "",
        "app_secret": doc.get("secret_encrypted") or "",
        "configured": True,
    }


@router.post("/social.instagram-config.get")
def ig_config_get(body: SocialConfigBody, auth: dict = Depends(current_user)):
    from .access_guards import require_domain_access

    project_id = body.project_id or body.client_id
    require_domain_access(auth["user_id"], project_id, Domain.SOCIALMEDIA)
    return _social_app_get(project_id, "instagram")


@router.post("/social.facebook-config.get")
def fb_config_get(body: SocialConfigBody, auth: dict = Depends(current_user)):
    from .access_guards import require_domain_access

    project_id = body.project_id or body.client_id
    require_domain_access(auth["user_id"], project_id, Domain.SOCIALMEDIA)
    return _social_app_get(project_id, "facebook")


@router.post("/social.instagram-config.save")
def ig_config_save(body: SocialConfigBody, auth: dict = Depends(current_user)):
    from .access_guards import require_domain_access, require_internal
    from .db import project_secrets_col
    from .models import ProjectSecret, SecretKind

    require_internal(auth)
    project_id = body.project_id or body.client_id
    require_domain_access(auth["user_id"], project_id, Domain.SOCIALMEDIA)
    project_secrets_col().delete_many(
        {"project_id": project_id, "provider": "instagram", "kind": "app_config"}
    )
    doc = ProjectSecret(
        project_id=project_id,
        kind=SecretKind.APP_CONFIG,
        provider="instagram",
        label="instagram app",
        username=body.app_id,
        secret_encrypted=body.app_secret,
        metadata={"app_id": body.app_id},
    ).model_dump(mode="json")
    project_secrets_col().insert_one(doc)
    return _social_app_get(project_id, "instagram")


@router.post("/social.facebook-config.save")
def fb_config_save(body: SocialConfigBody, auth: dict = Depends(current_user)):
    from .access_guards import require_domain_access, require_internal
    from .db import project_secrets_col
    from .models import ProjectSecret, SecretKind

    require_internal(auth)
    project_id = body.project_id or body.client_id
    require_domain_access(auth["user_id"], project_id, Domain.SOCIALMEDIA)
    project_secrets_col().delete_many(
        {"project_id": project_id, "provider": "facebook", "kind": "app_config"}
    )
    doc = ProjectSecret(
        project_id=project_id,
        kind=SecretKind.APP_CONFIG,
        provider="facebook",
        label="facebook app",
        username=body.app_id,
        secret_encrypted=body.app_secret,
        metadata={"app_id": body.app_id},
    ).model_dump(mode="json")
    project_secrets_col().insert_one(doc)
    return _social_app_get(project_id, "facebook")
