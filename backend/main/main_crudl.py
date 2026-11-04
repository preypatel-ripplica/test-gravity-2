"""CRUDL APIs for users and projects. Access is handled internally."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, EmailStr, Field
from pymongo.errors import DuplicateKeyError

from .access_guards import (
    require_internal,
    require_project_access,
    require_project_owner,
)
from .auth import current_user, create_token, decode_token, hash_password, verify_password
from .db import access_col, channels_col, projects_col, users_col
from .models import (
    Access,
    Domain,
    ProfileSection,
    Project,
    ProjectStatus,
    Topic,
    User,
    UserType,
    utc_now,
)

OWNER_DEFAULT_DOMAINS = (
    Domain.VIDEOS,
    Domain.SOCIALMEDIA,
    Domain.WEBSITE,
)

router = APIRouter()


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class UserCreateBody(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1)
    password: str = Field(min_length=8)
    type: UserType


class UserGetBody(BaseModel):
    user_id: str


class UserListBody(BaseModel):
    type: Optional[UserType] = None


class UserUpdateBody(BaseModel):
    user_id: str
    name: Optional[str] = Field(default=None, min_length=1)
    type: Optional[UserType] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8)


class ProjectCreateBody(BaseModel):
    name: str = Field(min_length=1)


class ProjectIdBody(BaseModel):
    project_id: str


class ProjectUpdateBody(BaseModel):
    project_id: str
    name: Optional[str] = Field(default=None, min_length=1)
    status: Optional[ProjectStatus] = None
    website_url: Optional[str] = None
    specialty: Optional[str] = None
    designation: Optional[str] = None
    description: Optional[str] = None
    reference_youtube_channel: Optional[str] = None
    ai_videos_started_from: Optional[str] = None
    # TG parity: inactive maps to archived; soft-delete sets deleted_at
    is_active: Optional[bool] = None
    soft_delete: Optional[bool] = None
    onboarding_date: Optional[str] = None
    tracker_start_year: Optional[int] = None
    tracker_start_month: Optional[int] = None
    tracker_start_week: Optional[int] = None
    tracker_deliverables: Optional[list] = None
    profile_sections: Optional[list[ProfileSection]] = None
    topics: Optional[list[Topic]] = None


class MembersSetBody(BaseModel):
    project_id: str
    user_id: Optional[str] = None
    email: Optional[EmailStr] = None
    domains: list[Domain] = Field(min_length=1)  # videos | socialmedia | …


class MembersRemoveBody(BaseModel):
    project_id: str
    user_id: Optional[str] = None
    email: Optional[EmailStr] = None


ALL_DOMAIN_VALUES = [d.value for d in Domain]


def public_user(doc: dict) -> dict:
    doc = {**doc}
    doc.pop("_id", None)
    doc.pop("password_hash", None)
    return jsonable_encoder(doc)


def public_project(doc: dict, domains: list[str] | None = None) -> dict:
    doc = {**doc}
    doc.pop("_id", None)
    if domains is not None:
        doc["domains"] = domains
    return jsonable_encoder(doc)


def _resolve_member_user(*, user_id: Optional[str], email: Optional[EmailStr]) -> dict:
    if user_id:
        return find_user(user_id)
    if email:
        user = users_col().find_one({"email": str(email).lower()}, {"_id": 0})
        if not user:
            raise HTTPException(404, "No user with that email")
        return user
    raise HTTPException(400, "user_id or email is required")


def find_user(user_id: str) -> dict:
    user = users_col().find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    return user


def find_project(project_id: str) -> dict:
    project = projects_col().find_one({"id": project_id}, {"_id": 0})
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.post("/auth.login")
def auth_login(body: LoginBody):
    user = users_col().find_one({"email": body.email.lower()}, {"_id": 0})
    if (
        not user
        or not user.get("password_hash")
        or not verify_password(body.password, user["password_hash"])
    ):
        raise HTTPException(401, "Invalid email or password")
    if not user.get("is_active", True):
        raise HTTPException(403, "User is inactive")
    return {"token": create_token(user), "user": public_user(user)}


@router.post("/auth.me")
def auth_me(auth: dict = Depends(current_user)):
    """TG frontend expects clients[] on me (Beacon projects = TG clients)."""
    user = find_user(auth["user_id"])
    if not user.get("is_active", True):
        raise HTTPException(403, "User is inactive")

    from backend.trackers.tracker_settings import stored_monthly_slots

    data = project_list(auth)
    clients = []
    for p in data["projects"]:
        channel_count = channels_col().count_documents({"project_id": p["id"]})
        status = str(p.get("status") or ProjectStatus.ACTIVE.value)
        clients.append(
            {
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
                "is_active": status != ProjectStatus.ARCHIVED.value,
                "status": status,
                "onboarding_date": p.get("onboarding_date"),
                "tracker_start_year": p.get("tracker_start_year"),
                "tracker_start_month": p.get("tracker_start_month"),
                "tracker_start_week": p.get("tracker_start_week"),
                "tracker_deliverables": stored_monthly_slots(p),
                "tracker_deliverables_period": p.get("tracker_deliverables_period")
                or "",
                "video_editor_id": p.get("video_editor_id") or "",
                "long_video_hours": p.get("long_video_hours") or 0,
                "short_video_hours": p.get("short_video_hours") or 0,
            }
        )

    out = public_user(user)
    out.update(
        {
            # TG UI still reads username in a few places
            "username": user.get("email"),
            "has_clients": len(clients) > 0,
            "active_client_id": None,
            "active_channel_id": None,
            "clients": clients,
            "channels": [],
        }
    )
    return out


@router.post("/user.create")
def user_create(request: Request, body: UserCreateBody):
    # First user ever: no token. After that: internal token required.
    if users_col().count_documents({}) > 0:
        header = request.headers.get("Authorization") or ""
        if not header.startswith("Bearer "):
            raise HTTPException(401, "Token is missing")
        payload = decode_token(header.split(" ", 1)[1])
        if not payload:
            raise HTTPException(401, "Token is invalid or expired")
        require_internal(payload)

    doc = User(
        email=body.email.lower(),
        name=body.name.strip(),
        password_hash=hash_password(body.password),
        type=body.type,
    ).model_dump(mode="json")
    try:
        users_col().insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "User with this email already exists")
    return public_user(doc)


@router.post("/user.get")
def user_get(body: UserGetBody, _auth: dict = Depends(current_user)):
    return public_user(find_user(body.user_id))


@router.post("/user.list")
def user_list(
    body: UserListBody = UserListBody(),
    _auth: dict = Depends(current_user),
):
    query = {"type": body.type.value} if body.type else {}
    users = users_col().find(query, {"_id": 0, "password_hash": 0}).sort("created_at", -1)
    return {"users": [jsonable_encoder(u) for u in users]}


@router.post("/user.update")
def user_update(body: UserUpdateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    find_user(body.user_id)
    updates = {"updated_at": utc_now()}
    if body.name is not None:
        updates["name"] = body.name.strip()
    if body.type is not None:
        updates["type"] = body.type.value
    if body.is_active is not None:
        updates["is_active"] = body.is_active
    if body.password is not None:
        updates["password_hash"] = hash_password(body.password)
    if len(updates) == 1:
        raise HTTPException(400, "No fields to update")
    users_col().update_one({"id": body.user_id}, {"$set": updates})
    return public_user(find_user(body.user_id))


@router.post("/user.delete")
def user_delete(body: UserGetBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    find_user(body.user_id)
    users_col().update_one(
        {"id": body.user_id},
        {"$set": {"is_active": False, "updated_at": utc_now()}},
    )
    return public_user(find_user(body.user_id))


@router.post("/project.create")
def project_create(body: ProjectCreateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    from backend.trackers.tracker_settings import current_week_tuple

    start_year, start_month, start_week = current_week_tuple()
    doc = Project(
        name=body.name.strip(),
        owner_user_id=auth["user_id"],
        tracker_start_year=start_year,
        tracker_start_month=start_month,
        tracker_start_week=start_week,
    ).model_dump(mode="json")
    projects_col().insert_one(doc)
    for domain in OWNER_DEFAULT_DOMAINS:
        access_col().update_one(
            {
                "user_id": auth["user_id"],
                "project_id": doc["id"],
                "domain": domain.value,
            },
            {
                "$setOnInsert": Access(
                    user_id=auth["user_id"],
                    project_id=doc["id"],
                    domain=domain,
                ).model_dump(mode="json")
            },
            upsert=True,
        )
    out = public_project(doc, [d.value for d in OWNER_DEFAULT_DOMAINS])
    out["is_owner"] = True
    return out


@router.post("/project.get")
def project_get(body: ProjectIdBody, auth: dict = Depends(current_user)):
    project = require_project_access(auth["user_id"], body.project_id)
    domains = [
        row["domain"]
        for row in access_col().find(
            {"user_id": auth["user_id"], "project_id": body.project_id},
            {"_id": 0, "domain": 1},
        )
    ]
    is_owner = project.get("owner_user_id") == auth["user_id"]
    out = public_project(
        project,
        ALL_DOMAIN_VALUES if is_owner else sorted(domains),
    )
    out["is_owner"] = is_owner
    return out


@router.post("/project.list")
def project_list(auth: dict = Depends(current_user)):
    uid = auth["user_id"]
    by_project: dict[str, set[str]] = {}
    for row in access_col().find({"user_id": uid}, {"_id": 0}):
        by_project.setdefault(row["project_id"], set()).add(row["domain"])

    not_deleted = {"$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]}
    for p in projects_col().find(
        {"owner_user_id": uid, **not_deleted},
        {"_id": 0, "id": 1},
    ):
        by_project.setdefault(p["id"], set())

    if not by_project:
        return {"projects": []}

    projects = {
        p["id"]: p
        for p in projects_col().find(
            {"id": {"$in": list(by_project)}, **not_deleted},
            {"_id": 0},
        )
    }
    result = []
    for pid, domains in by_project.items():
        if pid not in projects:
            continue
        project = projects[pid]
        is_owner = project.get("owner_user_id") == uid
        out = public_project(
            project,
            ALL_DOMAIN_VALUES if is_owner else sorted(domains),
        )
        out["is_owner"] = is_owner
        result.append(out)
    result.sort(key=lambda p: p["name"].lower())
    return {"projects": result}


@router.post("/project.update")
def project_update(body: ProjectUpdateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_project_access(auth["user_id"], body.project_id)
    existing = find_project(body.project_id)
    updates = {"updated_at": utc_now()}
    if body.name is not None:
        updates["name"] = body.name.strip()
    if body.status is not None:
        updates["status"] = body.status.value
    if body.is_active is not None:
        updates["status"] = (
            ProjectStatus.ACTIVE.value if body.is_active else ProjectStatus.ARCHIVED.value
        )
    if body.soft_delete:
        updates["deleted_at"] = utc_now()
        updates["status"] = ProjectStatus.ARCHIVED.value
    for key in (
        "website_url",
        "specialty",
        "designation",
        "description",
        "reference_youtube_channel",
        "ai_videos_started_from",
        "onboarding_date",
    ):
        val = getattr(body, key)
        if val is not None:
            updates[key] = val
    if (
        body.tracker_start_year is not None
        or body.tracker_start_month is not None
        or body.tracker_start_week is not None
    ):
        from backend.trackers.tracker_settings import tracker_start_tuple

        year = body.tracker_start_year
        month = body.tracker_start_month
        week = body.tracker_start_week
        if year is None or month is None or week is None:
            raise HTTPException(400, "tracker start needs year, month, and week")
        probe = {
            "tracker_start_year": int(year),
            "tracker_start_month": int(month),
            "tracker_start_week": int(week),
        }
        if tracker_start_tuple(probe) is None:
            raise HTTPException(400, "tracker start week must be 1-4 in a valid month")
        updates.update(probe)
    sync_deliverables = False
    if body.tracker_deliverables is not None:
        from backend.trackers.tracker_settings import (
            DELIVERABLES_PERIOD_MONTH,
            current_week_tuple,
            merge_week_slot_plan,
            monthly_counts_changed,
            normalize_deliverables,
            record_deliverable_change,
            remaining_week_slot_plan,
            tracker_start_tuple,
        )

        new_slots = normalize_deliverables(body.tracker_deliverables)
        updates["tracker_deliverables"] = new_slots
        updates["tracker_deliverables_period"] = DELIVERABLES_PERIOD_MONTH
        updates["tracker_deliverable_history"] = record_deliverable_change(
            existing, new_slots
        )
        if monthly_counts_changed(existing, new_slots):
            updates["tracker_week_slot_plan"] = merge_week_slot_plan(
                existing.get("tracker_week_slot_plan"),
                remaining_week_slot_plan(existing, new_slots),
            )
            sync_deliverables = True
    if body.profile_sections is not None:
        updates["profile_sections"] = [
            s.model_dump(mode="json") for s in body.profile_sections
        ]
    if body.topics is not None:
        updates["topics"] = [t.model_dump(mode="json") for t in body.topics]
    if len(updates) == 1:
        raise HTTPException(400, "No fields to update")
    projects_col().update_one({"id": body.project_id}, {"$set": updates})
    if sync_deliverables:
        from backend.trackers.crudl import sync_weeks_from_deliverable_change

        project = find_project(body.project_id)
        start = tracker_start_tuple(project)
        from_week = current_week_tuple()
        if start and from_week < start:
            from_week = start
        sync_weeks_from_deliverable_change(
            body.project_id, auth.get("email") or auth["user_id"], from_week
        )
    return public_project(find_project(body.project_id))


@router.post("/project.delete")
def project_delete(body: ProjectIdBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_project_access(auth["user_id"], body.project_id)
    # Soft-delete only — related rows stay in DB
    projects_col().update_one(
        {"id": body.project_id},
        {
            "$set": {
                "status": ProjectStatus.ARCHIVED.value,
                "deleted_at": utc_now(),
                "updated_at": utc_now(),
            }
        },
    )
    return public_project(find_project(body.project_id))


@router.post("/project.members.list")
def project_members_list(body: ProjectIdBody, auth: dict = Depends(current_user)):
    project = require_project_owner(auth, body.project_id)
    owner_id = project.get("owner_user_id")
    by_user: dict[str, set[str]] = {}
    for row in access_col().find({"project_id": body.project_id}, {"_id": 0}):
        by_user.setdefault(row["user_id"], set()).add(row["domain"])
    if owner_id:
        by_user.setdefault(owner_id, set(ALL_DOMAIN_VALUES))

    members = []
    for user_id, domains in by_user.items():
        user = users_col().find_one(
            {"id": user_id},
            {"_id": 0, "email": 1, "name": 1, "type": 1},
        )
        is_owner = user_id == owner_id
        members.append(
            {
                "user_id": user_id,
                "email": user.get("email") if user else None,
                "name": user.get("name") if user else None,
                "type": user.get("type") if user else None,
                "domains": ALL_DOMAIN_VALUES if is_owner else sorted(domains),
                "is_owner": is_owner,
            }
        )
    members.sort(
        key=lambda m: (not m["is_owner"], (m["name"] or m["user_id"] or "").lower())
    )
    return {
        "project_id": body.project_id,
        "owner_user_id": owner_id,
        "members": members,
    }


@router.post("/project.members.set")
def project_members_set(body: MembersSetBody, auth: dict = Depends(current_user)):
    project = require_project_owner(auth, body.project_id)
    target = _resolve_member_user(user_id=body.user_id, email=body.email)
    if target["id"] == project.get("owner_user_id"):
        raise HTTPException(
            400, "Cannot change the owner's domain grants — they always have full access"
        )
    domains = list(dict.fromkeys(body.domains))

    access_col().delete_many({"project_id": body.project_id, "user_id": target["id"]})
    access_col().insert_many(
        [
            Access(
                user_id=target["id"],
                project_id=body.project_id,
                domain=domain,
            ).model_dump(mode="json")
            for domain in domains
        ]
    )
    return {
        "project_id": body.project_id,
        "user_id": target["id"],
        "email": target.get("email"),
        "domains": [d.value for d in domains],
    }


@router.post("/project.members.remove")
def project_members_remove(
    body: MembersRemoveBody,
    auth: dict = Depends(current_user),
):
    project = require_project_owner(auth, body.project_id)
    target = _resolve_member_user(user_id=body.user_id, email=body.email)
    if target["id"] == project.get("owner_user_id"):
        raise HTTPException(400, "Cannot remove the project owner")
    result = access_col().delete_many(
        {"project_id": body.project_id, "user_id": target["id"]}
    )
    return {
        "project_id": body.project_id,
        "user_id": target["id"],
        "removed": result.deleted_count,
    }
