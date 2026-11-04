"""Beacon-backed implementations of test-gravity's `app.database` helpers.

Signatures and return shapes follow TG so ported routes/services keep working.

Vocabulary mapping
------------------
username            -> users.email   (falls back to users.id)
client_id           -> projects.id   (project_id on every child collection)
client ownership    -> `access` grants (any domain) for that user on the project
topics              -> projects.topics (embedded list)
content plan        -> projects.content_plan (suggestions blob) +
                       plan_items (scripts) + videos.topic_id/out_of_keyword/video_type
channels            -> channels (+ google_credentials rebuilt from project_secrets,
                       provider=youtube, external_account_id=channel_id)
videos              -> videos
content_videos      -> yt_metadata (TG keys + Beacon keys written together)
IG / FB config      -> project_secrets kind=app_config
IG / FB connection  -> project_secrets kind=oauth
OAuth `state` rows  -> generic `oauth_states` collection (no Beacon equivalent)
social posts        -> social_posts (TG fields kept next to Beacon fields)
social schedule     -> social_schedules
monthly reports     -> monthly_reports (full TG doc stored, + project_id)
weekly/custom       -> weekly_trackers / custom_trackers (TG shape, already migrated)
doctor reference    -> projects.profile_sections
client credentials  -> project_secrets kind=manual
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Optional

from pymongo import ASCENDING, DESCENDING, UpdateOne
from pymongo.errors import DuplicateKeyError

from backend.main.db import (
    access_col,
    channels_col,
    get_db,
    monthly_reports_col,
    plan_items_col,
    yt_metadata_col,
    project_secrets_col,
    projects_col,
    social_posts_col,
    social_schedules_col,
    users_col,
    videos_col,
    weekly_trackers_col,
    custom_trackers_col,
)
from backend.main.models import (
    Domain,
    Project,
    ProjectSecret,
    ProjectStatus,
    SecretKind,
    new_id,
    utc_now,
)

# ── names TG code imports ────────────────────────────────────────────────────

COL_USERS = "users"
COL_CLIENTS = "projects"
COL_CHANNELS = "channels"
COL_VIDEOS = "videos"
COL_SOCIAL_POSTS = "social_posts"
COL_SOCIAL_SCHEDULES = "social_schedules"
COL_WEEKLY_TRACKERS = "weekly_trackers"
COL_CUSTOM_TRACKERS = "custom_trackers"
COL_MONTHLY_REPORTS = "monthly_reports"
COL_CONTENT_VIDEOS = "yt_metadata"
COL_TRACKER_SHEET_COMMENTS = "tracker_sheet_comments"
COL_INSTAGRAM_OAUTH_STATES = "oauth_states"
COL_FACEBOOK_OAUTH_STATES = "oauth_states"

CLIENT_PROFILE_KEYS = (
    "name",
    "website_url",
    "specialty",
    "designation",
    "description",
    "reference_youtube_channel",
    "ai_videos_started_from",
    "onboarding_date",
    "tracker_start_year",
    "tracker_start_month",
    "tracker_start_week",
    "tracker_deliverables",
    "tracker_deliverables_period",
    "tracker_deliverable_history",
    "tracker_week_slot_plan",
    "status",
    "deleted_at",
)

CHANNEL_META_KEYS = (
    "title",
    "description",
    "custom_url",
    "published_at",
    "view_count",
    "subscriber_count",
    "video_count",
    "google_credentials",
    "language",
)

GRANT_DOMAINS = (Domain.VIDEOS, Domain.SOCIALMEDIA, Domain.WEBSITE)

_DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"


# ── tiny helpers / TG shims ──────────────────────────────────────────────────


def _use_mongo() -> bool:
    """Beacon is always Mongo-backed."""
    return True


def _mdb():
    return get_db()


def mongo_db():
    return get_db()


def _load_file(username: str | None = None) -> dict:
    """TG JSON-file fallback does not exist in Beacon."""
    return {}


def _strip_mongo_id(doc: dict | None) -> dict:
    if not doc:
        return {}
    out = dict(doc)
    out.pop("_id", None)
    return out


def _now_iso_for_db() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso() -> str:
    """UTC timestamp string in the same style pydantic emits for Beacon docs."""
    return utc_now().isoformat().replace("+00:00", "Z")


def _clean(doc: dict | None) -> dict | None:
    if not doc:
        return None
    out = dict(doc)
    out.pop("_id", None)
    return out


# ── users ────────────────────────────────────────────────────────────────────


def _find_user_doc(username: str | None) -> dict | None:
    if not username:
        return None
    key = str(username).strip()
    doc = users_col().find_one({"email": key.lower()}, {"_id": 0})
    if doc is None and key != key.lower():
        doc = users_col().find_one({"email": key}, {"_id": 0})
    if doc is None:
        doc = users_col().find_one({"id": key}, {"_id": 0})
    return doc


def _user_id_for(username: str | None) -> str | None:
    doc = _find_user_doc(username)
    return doc.get("id") if doc else None


def _has_project_access(username: str | None, project_id: str) -> bool:
    """True if username is None (no filter), is owner, or has any access grant."""
    if username is None:
        return True
    user_id = _user_id_for(username)
    if not user_id:
        return False
    project = projects_col().find_one(
        {"id": project_id}, {"_id": 0, "owner_user_id": 1}
    )
    if project and project.get("owner_user_id") == user_id:
        return True
    return (
        access_col().find_one({"user_id": user_id, "project_id": project_id}, {"_id": 1})
        is not None
    )


def _has_domain_access(
    username: str | None, project_id: str, domain: Domain | str
) -> bool:
    """True if username is None, is owner, or has a grant for this domain."""
    if username is None:
        return True
    user_id = _user_id_for(username)
    if not user_id:
        return False
    domain_value = domain.value if isinstance(domain, Domain) else str(domain)
    project = projects_col().find_one(
        {"id": project_id}, {"_id": 0, "owner_user_id": 1}
    )
    if not project:
        return False
    if project.get("owner_user_id") == user_id:
        return True
    return (
        access_col().find_one(
            {"user_id": user_id, "project_id": project_id, "domain": domain_value},
            {"_id": 1},
        )
        is not None
    )


def require_domain_for_user(
    username: str, project_id: str, domain: Domain | str
) -> None:
    """Raise 403 unless username may use this domain on the project."""
    from fastapi import HTTPException

    if _has_domain_access(username, project_id, domain):
        return
    domain_value = domain.value if isinstance(domain, Domain) else str(domain)
    raise HTTPException(
        status_code=403,
        detail=f"No access to domain '{domain_value}' on this project",
    )


def fetch_user(username: str) -> dict | None:
    """users collection by email. No clients/channels/videos."""
    doc = _find_user_doc(username)
    if not doc:
        return None
    email = doc.get("email") or username
    return {
        "username": email,
        "email": email,
        "id": doc.get("id"),
        "user_id": doc.get("id"),
        "name": doc.get("name") or email,
        "type": doc.get("type") or "client",
        "hashed_password": doc.get("password_hash") or "",
        "is_active": bool(doc.get("is_active", True)),
        "active_client_id": doc.get("active_client_id"),
        "active_channel_id": doc.get("active_channel_id"),
        "clients": [],
    }


def insert_user(user: dict) -> None:
    username = str(user["username"]).strip().lower()
    now = _iso()
    users_col().insert_one(
        {
            "id": user.get("id") or new_id("user"),
            "email": username,
            "name": user.get("name") or user["username"],
            "password_hash": user.get("hashed_password") or None,
            "type": user.get("type") or "client",
            "is_active": bool(user.get("is_active", True)),
            "active_client_id": user.get("active_client_id"),
            "active_channel_id": user.get("active_channel_id"),
            "created_at": now,
            "updated_at": now,
        }
    )


def update_user_fields(username: str, **fields: Any) -> None:
    allowed = {"hashed_password", "is_active", "active_client_id", "active_channel_id"}
    patch = {k: v for k, v in fields.items() if k in allowed}
    if not patch:
        return
    if "hashed_password" in patch:
        patch["password_hash"] = patch.pop("hashed_password")
    doc = _find_user_doc(username)
    if not doc:
        return
    patch["updated_at"] = _iso()
    users_col().update_one({"id": doc["id"]}, {"$set": patch})


def delete_user(username: str) -> bool:
    doc = _find_user_doc(username)
    if not doc:
        return False
    access_col().delete_many({"user_id": doc["id"]})
    users_col().delete_one({"id": doc["id"]})
    return True


# ── clients (= projects) ─────────────────────────────────────────────────────


def _project_doc(client_id: str, *, username: str | None = None) -> dict | None:
    if not client_id:
        return None
    doc = projects_col().find_one({"id": client_id}, {"_id": 0})
    if not doc:
        return None
    if username is not None and not _has_project_access(username, client_id):
        return None
    return doc


def _client_from_project(doc: dict, *, topics: list[dict] | None = None) -> dict:
    status = str(doc.get("status") or ProjectStatus.ACTIVE.value)
    client = {
        "id": doc["id"],
        "name": doc.get("name") or "Client",
        "website_url": doc.get("website_url"),
        "specialty": doc.get("specialty"),
        "designation": doc.get("designation"),
        "description": doc.get("description"),
        "reference_youtube_channel": doc.get("reference_youtube_channel"),
        "ai_videos_started_from": doc.get("ai_videos_started_from"),
        "onboarding_date": doc.get("onboarding_date"),
        "tracker_start_year": doc.get("tracker_start_year"),
        "tracker_start_month": doc.get("tracker_start_month"),
        "tracker_start_week": doc.get("tracker_start_week"),
        "tracker_deliverables": doc.get("tracker_deliverables"),
        "tracker_deliverables_period": doc.get("tracker_deliverables_period") or "",
        "tracker_deliverable_history": doc.get("tracker_deliverable_history"),
        "tracker_week_slot_plan": doc.get("tracker_week_slot_plan"),
        "status": status,
        "is_active": status != ProjectStatus.ARCHIVED.value,
        "deleted_at": doc.get("deleted_at"),
        "topics": topics if topics is not None else [],
        "channels": [],
    }
    return client


def fetch_client_doc(client_id: str, *, username: str | None = None) -> dict | None:
    """projects doc -> nested-shaped client shell (no topics/channels)."""
    doc = _project_doc(client_id, username=username)
    if not doc:
        return None
    return _client_from_project(doc)


def fetch_topics(client_id: str) -> list[dict]:
    doc = projects_col().find_one({"id": client_id}, {"_id": 0, "topics": 1})
    return [dict(t) for t in ((doc or {}).get("topics") or []) if isinstance(t, dict)]


def replace_topics(client_id: str, topics: list[dict]) -> None:
    """Replace all topics on the project (embedded list)."""
    rows = [dict(t) for t in topics if isinstance(t, dict) and t.get("id")]
    projects_col().update_one(
        {"id": client_id}, {"$set": {"topics": rows, "updated_at": _iso()}}
    )


def update_client_fields(client_id: str, username: str, fields: dict[str, Any]) -> dict | None:
    """Update profile fields on the project for this client_id + user."""
    if not _project_doc(client_id, username=username):
        return None
    allowed = set(CLIENT_PROFILE_KEYS) | {"status", "deleted_at"}
    patch = {k: fields[k] for k in fields if k in allowed}
    patch["updated_at"] = _iso()
    projects_col().update_one({"id": client_id}, {"$set": patch})
    return fetch_client_doc(client_id, username=username)


def grant_project_access(user_id: str, project_id: str, domains=GRANT_DOMAINS) -> None:
    for domain in domains:
        value = domain.value if isinstance(domain, Domain) else str(domain)
        access_col().update_one(
            {"user_id": user_id, "project_id": project_id, "domain": value},
            {
                "$setOnInsert": {
                    "id": new_id("access"),
                    "created_at": _iso(),
                }
            },
            upsert=True,
        )


def insert_client(username: str, client: dict) -> None:
    user = _find_user_doc(username)
    if not user:
        return
    from backend.trackers.tracker_settings import current_week_tuple

    start_year, start_month, start_week = current_week_tuple()
    project = Project(
        id=client.get("id") or new_id("project"),
        name=(client.get("name") or "Untitled").strip() or "Untitled",
        owner_user_id=user["id"],
        website_url=client.get("website_url"),
        specialty=client.get("specialty"),
        designation=client.get("designation"),
        description=client.get("description"),
        reference_youtube_channel=client.get("reference_youtube_channel"),
        ai_videos_started_from=client.get("ai_videos_started_from"),
        tracker_start_year=client.get("tracker_start_year", start_year),
        tracker_start_month=client.get("tracker_start_month", start_month),
        tracker_start_week=client.get("tracker_start_week", start_week),
    ).model_dump(mode="json")
    project["topics"] = [dict(t) for t in (client.get("topics") or []) if isinstance(t, dict)]
    projects_col().insert_one(project)
    grant_project_access(user["id"], project["id"])
    users_col().update_one(
        {"id": user["id"]},
        {"$set": {"active_client_id": project["id"], "active_channel_id": None}},
    )


def _cascade_archive_client(client_id: str) -> None:
    """Soft-delete: archive + deleted_at. Related rows stay in DB."""
    projects_col().update_one(
        {"id": client_id},
        {
            "$set": {
                "status": ProjectStatus.ARCHIVED.value,
                "deleted_at": _iso(),
                "updated_at": _iso(),
            }
        },
    )


def delete_client_owned(client_id: str, username: str) -> bool:
    """Archive the project (Beacon semantics) if the user has access; fix pointers."""
    if not _project_doc(client_id, username=username):
        return False
    _cascade_archive_client(client_id)
    udoc = _find_user_doc(username)
    if udoc and udoc.get("active_client_id") == client_id:
        remaining = list_clients_for_user(username, with_topics=False)
        next_id = remaining[0]["id"] if remaining else None
        active_ch = None
        if next_id:
            ids = list_channel_ids(next_id)
            active_ch = ids[0] if ids else None
        users_col().update_one(
            {"id": udoc["id"]},
            {"$set": {"active_client_id": next_id, "active_channel_id": active_ch}},
        )
    return True


def list_clients_for_user(username: str, *, with_topics: bool = True) -> list[dict]:
    """Light clients for API list responses — no videos. Includes inactive; excludes soft-deleted."""
    from backend.trackers.tracker_settings import stored_monthly_slots

    user_id = _user_id_for(username)
    if not user_id:
        return []
    project_ids = sorted({r["project_id"] for r in access_col().find({"user_id": user_id}, {"project_id": 1})})
    if not project_ids:
        return []
    docs = list(
        projects_col().find(
            {
                "id": {"$in": project_ids},
                "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
            },
            {"_id": 0},
        )
    )
    channel_ids_by_client: dict[str, list[str]] = {}
    for ch in channels_col().find({"project_id": {"$in": project_ids}}, {"id": 1, "project_id": 1}):
        channel_ids_by_client.setdefault(ch["project_id"], []).append(ch["id"])
    docs.sort(key=lambda d: (d.get("name") or "").lower())
    out: list[dict] = []
    for doc in docs:
        ch_ids = channel_ids_by_client.get(doc["id"], [])
        status = str(doc.get("status") or ProjectStatus.ACTIVE.value)
        out.append(
            {
                "id": doc["id"],
                **{k: doc.get(k) for k in CLIENT_PROFILE_KEYS},
                "status": status,
                "is_active": status != ProjectStatus.ARCHIVED.value,
                "tracker_deliverables": stored_monthly_slots(doc),
                "tracker_deliverables_period": doc.get("tracker_deliverables_period") or "",
                "topics": [dict(t) for t in (doc.get("topics") or [])] if with_topics else [],
                "channels": [{"id": i} for i in ch_ids],
                "channel_count": len(ch_ids),
            }
        )
    return out


def fetch_all_clients() -> list[dict]:
    """Every active project, TG client-ish (used by cron jobs)."""
    out = []
    for doc in projects_col().find({"status": {"$ne": ProjectStatus.ARCHIVED.value}}, {"_id": 0}):
        out.append({"id": doc["id"], **{k: doc.get(k) for k in CLIENT_PROFILE_KEYS}})
    return out


def heal_user_pointers(username: str) -> None:
    """Fix stale active_client_id / active_channel_id using collection lookups only."""
    user = fetch_user(username)
    if not user:
        return
    clients = list_clients_for_user(username, with_topics=False)
    client_ids = {c["id"] for c in clients}
    active_cid = user.get("active_client_id")
    patch: dict[str, Any] = {}
    if active_cid and active_cid not in client_ids:
        active_cid = clients[0]["id"] if clients else None
        patch["active_client_id"] = active_cid
    elif not active_cid and clients:
        active_cid = clients[0]["id"]
        patch["active_client_id"] = active_cid

    active_chid = user.get("active_channel_id")
    if active_cid:
        ch_ids = list_channel_ids(active_cid)
        if active_chid and active_chid not in ch_ids:
            patch["active_channel_id"] = ch_ids[0] if ch_ids else None
        elif not active_chid and ch_ids:
            patch["active_channel_id"] = ch_ids[0]
    elif active_chid:
        patch["active_channel_id"] = None

    if patch:
        update_user_fields(username, **patch)


# ── channels + youtube credentials (project_secrets) ─────────────────────────


def _secret_to_google_creds(secret: dict | None) -> dict:
    """Rebuild TG `google_credentials` dict from a project_secrets youtube row."""
    if not secret:
        return {}
    meta = secret.get("metadata") or {}
    creds: dict[str, Any] = {
        "token": secret.get("access_token_encrypted"),
        "refresh_token": secret.get("refresh_token_encrypted"),
        "token_uri": meta.get("token_uri") or _DEFAULT_TOKEN_URI,
        "client_id": meta.get("client_id"),
        "client_secret": meta.get("client_secret"),
        "scopes": list(secret.get("scopes") or []),
    }
    if meta.get("expiry"):
        creds["expiry"] = meta["expiry"]
    # Nothing useful stored -> behave like "not linked".
    if not creds["token"] and not creds["refresh_token"]:
        return {}
    return creds


def _find_youtube_secret(project_id: str | None, channel_id: str, secret_id: str | None = None) -> dict | None:
    if secret_id:
        doc = project_secrets_col().find_one({"id": secret_id}, {"_id": 0})
        if doc:
            return doc
    query: dict[str, Any] = {
        "provider": "youtube",
        "kind": SecretKind.OAUTH.value,
        "external_account_id": channel_id,
    }
    if project_id:
        query["project_id"] = project_id
    return project_secrets_col().find_one(query, {"_id": 0})


def _write_youtube_secret(
    project_id: str,
    channel_id: str,
    creds: dict,
    *,
    title: str | None = None,
    secret_id: str | None = None,
) -> str:
    """Create/update the youtube oauth secret for one channel. Returns secret id."""
    existing = _find_youtube_secret(None, channel_id, secret_id)
    prev_meta = (existing or {}).get("metadata") or {}
    meta = {
        "token_uri": creds.get("token_uri") or prev_meta.get("token_uri") or _DEFAULT_TOKEN_URI,
        "client_id": creds.get("client_id") or prev_meta.get("client_id"),
        "client_secret": creds.get("client_secret") or prev_meta.get("client_secret"),
        "expiry": creds.get("expiry"),
    }
    fields: dict[str, Any] = {
        "project_id": project_id,
        "scopes": list(creds.get("scopes") or (existing or {}).get("scopes") or []),
        "refresh_token_encrypted": creds.get("refresh_token")
        or (existing or {}).get("refresh_token_encrypted"),
        "access_token_encrypted": creds.get("token") or creds.get("access_token"),
        "metadata": meta,
        "status": "active",
        "updated_at": _iso(),
    }
    if title:
        fields["external_account_name"] = title
    if existing:
        project_secrets_col().update_one({"id": existing["id"]}, {"$set": fields})
        return existing["id"]
    doc = ProjectSecret(
        project_id=project_id,
        kind=SecretKind.OAUTH,
        provider="youtube",
        label=title or channel_id,
        external_account_id=channel_id,
        external_account_name=title,
    ).model_dump(mode="json")
    doc.update(fields)
    project_secrets_col().insert_one(doc)
    return doc["id"]


def _channel_from_doc(doc: dict, creds: dict | None = None, videos: list[dict] | None = None) -> dict:
    language = doc.get("language") or None
    if language:
        language = str(language).strip().lower() or None
    return {
        "id": doc["id"],
        "title": doc.get("title") or "",
        "description": doc.get("description") or "",
        "custom_url": doc.get("custom_url"),
        "published_at": doc.get("published_at"),
        "view_count": int(doc.get("view_count") or 0),
        "subscriber_count": int(doc.get("subscriber_count") or 0),
        "video_count": int(doc.get("video_count") or 0),
        "google_credentials": creds or {},
        "language": language,
        "videos": videos if videos is not None else [],
    }


def _creds_for_channel_docs(docs: list[dict]) -> dict[str, dict]:
    """channel_id -> google_credentials for many channel docs (one secrets query)."""
    if not docs:
        return {}
    by_secret_id = {d["secret_id"]: d["id"] for d in docs if d.get("secret_id")}
    channel_ids = [d["id"] for d in docs]
    or_clauses: list[dict] = [{"external_account_id": {"$in": channel_ids}}]
    if by_secret_id:
        or_clauses.append({"id": {"$in": list(by_secret_id)}})
    rows = project_secrets_col().find(
        {"provider": "youtube", "kind": SecretKind.OAUTH.value, "$or": or_clauses},
        {"_id": 0},
    )
    out: dict[str, dict] = {}
    for row in rows:
        chid = by_secret_id.get(row.get("id")) or row.get("external_account_id")
        if chid and (chid not in out or by_secret_id.get(row.get("id"))):
            out[chid] = _secret_to_google_creds(row)
    return out


def count_channels(client_id: str) -> int:
    return channels_col().count_documents({"project_id": client_id})


def list_channel_ids(client_id: str) -> list[str]:
    return [d["id"] for d in channels_col().find({"project_id": client_id}, {"id": 1})]


def list_channel_summaries(client_id: str) -> list[dict]:
    """Channel id/title only."""
    return [
        {"id": d["id"], "title": d.get("title") or d["id"]}
        for d in channels_col().find({"project_id": client_id}, {"id": 1, "title": 1})
    ]


def fetch_channel(
    channel_id: str,
    *,
    client_id: str | None = None,
    username: str | None = None,
) -> dict | None:
    """channels doc by id (optional owner filters). Includes rebuilt credentials, no videos."""
    query: dict[str, Any] = {"id": channel_id}
    if client_id is not None:
        query["project_id"] = client_id
    doc = channels_col().find_one(query, {"_id": 0})
    if not doc:
        return None
    if username is not None and not _has_project_access(username, doc["project_id"]):
        return None
    secret = _find_youtube_secret(doc["project_id"], channel_id, doc.get("secret_id"))
    return _channel_from_doc(doc, _secret_to_google_creds(secret), videos=[])


def list_channels_meta(client_id: str) -> list[dict]:
    """Full channel meta for a client_id (no videos)."""
    docs = list(channels_col().find({"project_id": client_id}, {"_id": 0}))
    creds = _creds_for_channel_docs(docs)
    return [_channel_from_doc(d, creds.get(d["id"]), videos=[]) for d in docs]


def find_client_id_by_channel(username: str, channel_id: str) -> str | None:
    doc = channels_col().find_one({"id": channel_id}, {"_id": 0, "project_id": 1})
    if not doc:
        return None
    if not _has_project_access(username, doc["project_id"]):
        return None
    return doc["project_id"]


def update_channel_fields(channel_id: str, client_id: str, fields: dict[str, Any]) -> None:
    patch = {k: fields[k] for k in CHANNEL_META_KEYS if k in fields}
    if not patch:
        return
    doc = channels_col().find_one({"id": channel_id, "project_id": client_id}, {"_id": 0})
    if not doc:
        return
    creds = patch.pop("google_credentials", None)
    if creds is not None:
        if creds:
            secret_id = _write_youtube_secret(
                client_id,
                channel_id,
                creds,
                title=patch.get("title") or doc.get("title"),
                secret_id=doc.get("secret_id"),
            )
            patch["secret_id"] = secret_id
        else:
            secret = _find_youtube_secret(client_id, channel_id, doc.get("secret_id"))
            if secret:
                project_secrets_col().delete_one({"id": secret["id"]})
            patch["secret_id"] = None
    if patch:
        patch["updated_at"] = _iso()
        channels_col().update_one({"id": channel_id, "project_id": client_id}, {"$set": patch})


def upsert_channel(
    username: str,
    client_id: str,
    channel: dict,
    *,
    replace_videos: bool = False,
) -> None:
    """Upsert one channel by id (+ its youtube secret). Optionally replace its videos."""
    chid = channel.get("id")
    if not chid:
        return
    meta = {k: channel.get(k) for k in CHANNEL_META_KEYS if k != "google_credentials"}
    incoming_lang = (channel.get("language") or "").strip() or None
    if incoming_lang:
        meta["language"] = incoming_lang
    else:
        meta.pop("language", None)
    for key in ("view_count", "subscriber_count", "video_count"):
        meta[key] = int(meta.get(key) or 0)
    for key in ("title", "description"):
        meta[key] = meta.get(key) or ""

    existing = channels_col().find_one({"id": chid}, {"_id": 0})
    if existing and "language" not in meta and existing.get("language"):
        meta["language"] = existing["language"]

    set_fields = {**meta, "project_id": client_id, "updated_at": _iso()}
    creds = channel.get("google_credentials")
    if isinstance(creds, dict) and creds:
        set_fields["secret_id"] = _write_youtube_secret(
            client_id,
            chid,
            creds,
            title=meta.get("title"),
            secret_id=(existing or {}).get("secret_id"),
        )
    channels_col().update_one(
        {"id": chid},
        {"$set": set_fields, "$setOnInsert": {"created_at": _iso()}},
        upsert=True,
    )
    if replace_videos:
        replace_channel_videos(chid, client_id, channel.get("videos") or [])


def delete_channel_owned(channel_id: str, client_id: str, username: str) -> bool:
    """Delete one channel + its videos + its youtube secret."""
    if not _has_project_access(username, client_id):
        return False
    doc = channels_col().find_one({"id": channel_id, "project_id": client_id}, {"_id": 0})
    if not doc:
        return False
    videos_col().delete_many({"channel_id": channel_id, "project_id": client_id})
    secret = _find_youtube_secret(client_id, channel_id, doc.get("secret_id"))
    if secret:
        project_secrets_col().delete_one({"id": secret["id"]})
    channels_col().delete_one({"id": channel_id, "project_id": client_id})
    return True


def sync_client_channels(
    username: str,
    client_id: str,
    channels: list[dict],
    *,
    drop_missing: bool = False,
) -> None:
    """Upsert channel rows for a client. Optionally delete channels not in the list."""
    keep_ids: set[str] = set()
    for channel in channels:
        if not isinstance(channel, dict) or not channel.get("id"):
            continue
        keep_ids.add(channel["id"])
        # Videos live in their own collection; never rewrite them here.
        upsert_channel(username, client_id, channel, replace_videos=False)
    if not drop_missing:
        return
    for chid in list_channel_ids(client_id):
        if chid not in keep_ids:
            delete_channel_owned(chid, client_id, username)


# ── videos ───────────────────────────────────────────────────────────────────

_VIDEO_INTERNAL_KEYS = ("_id", "project_id", "channel_id", "created_at", "updated_at")


def _video_from_doc(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in _VIDEO_INTERNAL_KEYS}


# AI keyword map — lives on videos docs (not projects.content_topic_coverage).
VIDEO_TOPIC_MAP_FIELDS = (
    "topic_id",
    "out_of_keyword",
    "video_type",
    "topic_mapped_at",
)


def merge_preserved_video_fields(row: dict, existing: dict | None) -> dict:
    """Keep local-only fields across YouTube catalog sync."""
    out = dict(row)
    prev = existing or {}
    out["notes"] = prev.get("notes", "") or ""
    out["metadata_fields"] = prev.get("metadata_fields", {}) or {}
    for key in VIDEO_TOPIC_MAP_FIELDS:
        if key in prev:
            out[key] = prev[key]
    return out


def list_videos_for_channel(channel_id: str, client_id: str) -> list[dict]:
    return [
        _video_from_doc(v)
        for v in videos_col().find({"channel_id": channel_id, "project_id": client_id})
    ]


def replace_channel_videos(channel_id: str, client_id: str, videos: list[dict]) -> None:
    """Replace videos rows for one channel (upsert given rows, delete the rest)."""
    keep_ids: list[str] = []
    ops: list = []
    now = _iso()
    for video in videos:
        if not isinstance(video, dict) or not video.get("id"):
            continue
        vid = video["id"]
        keep_ids.append(vid)
        body = {k: v for k, v in video.items() if k not in ("_id", "created_at")}
        body.update({"project_id": client_id, "channel_id": channel_id, "updated_at": now})
        ops.append(
            UpdateOne(
                {"id": vid},
                {"$set": body, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
        )
    if ops:
        videos_col().bulk_write(ops, ordered=False)
    videos_col().delete_many(
        {"channel_id": channel_id, "project_id": client_id, "id": {"$nin": keep_ids}}
    )
    channels_col().update_one(
        {"id": channel_id, "project_id": client_id},
        {"$set": {"video_count": len(keep_ids), "updated_at": now}},
    )


def persist_video_topic_maps(client_id: str, updates: dict[str, dict]) -> None:
    """Persist AI topic map fields onto videos docs. updates: video_id → field patch."""
    if not client_id or not updates:
        return
    now = _iso()
    ops: list = []
    for vid, fields in updates.items():
        if not vid or not isinstance(fields, dict):
            continue
        patch = {k: fields.get(k) for k in VIDEO_TOPIC_MAP_FIELDS}
        patch["updated_at"] = now
        ops.append(UpdateOne({"id": vid, "project_id": client_id}, {"$set": patch}))
    if ops:
        videos_col().bulk_write(ops, ordered=False)


def update_video_fields(video_id: str, client_id: str, fields: dict[str, Any]) -> dict | None:
    patch = dict(fields)
    patch["updated_at"] = _iso()
    videos_col().update_one({"id": video_id, "project_id": client_id}, {"$set": patch})
    doc = videos_col().find_one({"id": video_id, "project_id": client_id})
    return _video_from_doc(doc) if doc else None


def fetch_video_titles(client_id: str) -> list[str]:
    titles: list[str] = []
    for v in videos_col().find({"project_id": client_id}, {"title": 1}):
        t = (v.get("title") or "").strip()
        if t:
            titles.append(t)
    return titles


# ── content plan (projects.content_plan + plan_items for scripts) ─────────────

CONTENT_VIDEO_YT_KEYS = (
    "yt_title",
    "yt_description",
    "yt_tags",
    "yt_thumbnail_url",
    "yt_thumbnail_prompt",
    "yt_locales",
)

# Script body + metadata live on plan_items only — not duplicated on projects.content_plan.
CONTENT_PLAN_SCRIPT_FIELDS = (
    "script",
    "script_target_duration",
    "script_hook_used",
    "script_cta",
    "script_checklist_passed",
    "script_checklist_notes",
)

PLAN_ITEM_ORIGIN_GENERATED = "generated"
PLAN_ITEM_ORIGIN_MANUAL = "manual"
PLAN_ITEM_ORIGINS = (PLAN_ITEM_ORIGIN_GENERATED, PLAN_ITEM_ORIGIN_MANUAL)


def strip_script_fields_from_row(row: dict | None) -> bool:
    """Remove script*/origin keys from a content-plan item. True if anything changed."""
    if not isinstance(row, dict):
        return False
    changed = False
    for key in CONTENT_PLAN_SCRIPT_FIELDS:
        if key in row:
            row.pop(key, None)
            changed = True
    if "origin" in row:
        row.pop("origin", None)
        changed = True
    return changed


def strip_script_fields_from_suggestions(suggestions: dict | None) -> bool:
    if not isinstance(suggestions, dict):
        return False
    changed = False
    for row in suggestions.get("items") or []:
        if isinstance(row, dict) and strip_script_fields_from_row(row):
            changed = True
    return changed


def _plan_item_script_patch(item: dict) -> dict[str, Any]:
    """Fields written to plan_items from a (possibly hydrated) content-plan item."""
    script = str(item.get("script") or "")
    patch: dict[str, Any] = {
        "script": script,
        "script_target_duration": str(item.get("script_target_duration") or ""),
        "script_hook_used": str(item.get("script_hook_used") or ""),
        "script_cta": str(item.get("script_cta") or ""),
        "script_checklist_notes": str(item.get("script_checklist_notes") or ""),
        "status": "scripted" if script.strip() else "planned",
    }
    if "script_checklist_passed" in item:
        val = item.get("script_checklist_passed")
        patch["script_checklist_passed"] = None if val is None else bool(val)
    return patch


def hydrate_scripts_from_plan_items(client_id: str, suggestions: dict | None) -> dict:
    """Attach script* fields from plan_items onto content_plan items (API/UI shape)."""
    if not isinstance(suggestions, dict):
        return {"items": [], "count": 0}
    out = dict(suggestions)
    items = [dict(i) for i in (out.get("items") or []) if isinstance(i, dict)]
    if not items:
        out["items"] = []
        return out
    ids = [str(i.get("id")) for i in items if i.get("id")]
    by_id: dict[str, dict] = {}
    if ids:
        for row in plan_items_col().find(
            {"project_id": client_id, "id": {"$in": ids}},
            {"_id": 0},
        ):
            by_id[str(row.get("id"))] = row
    hydrated = []
    for item in items:
        row = dict(item)
        pi = by_id.get(str(row.get("id") or ""))
        if pi:
            for key in CONTENT_PLAN_SCRIPT_FIELDS:
                if key in pi:
                    row[key] = pi.get(key)
            # Prefer plan_items script when present (source of truth)
            if pi.get("script") is not None:
                row["script"] = pi.get("script") or ""
            if pi.get("origin") in PLAN_ITEM_ORIGINS:
                row["origin"] = pi["origin"]
        hydrated.append(row)
    out["items"] = hydrated
    out["count"] = len(hydrated)
    return out


def fetch_content_plan(client_id: str) -> dict | None:
    """TG content_plans-shaped dict: {_id, content_suggestions?}."""
    doc = projects_col().find_one(
        {"id": client_id},
        {"_id": 0, "content_plan": 1},
    )
    if not doc:
        return None
    plan: dict[str, Any] = {"_id": client_id}
    if doc.get("content_plan"):
        plan["content_suggestions"] = hydrate_scripts_from_plan_items(
            client_id, doc["content_plan"]
        )
    return plan if len(plan) > 1 else None


def _sync_plan_items(client_id: str, suggestions: dict) -> None:
    """Upsert plan_items from suggestions.items (scripts + script attrs)."""
    items = [i for i in (suggestions.get("items") or []) if isinstance(i, dict) and i.get("id")]
    now = _iso()
    keep: list[str] = []
    for idx, item in enumerate(items):
        title = (
            item.get("title_en")
            or item.get("title_hinglish")
            or item.get("topic_text")
            or item.get("title")
            or "Untitled"
        )
        keep.append(item["id"])
        patch = {
            "project_id": client_id,
            "topic_id": item.get("topic_id"),
            "title": str(title),
            "format": str(item.get("format") or item.get("video_type") or "long"),
            "sort_order": idx,
            "updated_at": now,
            **_plan_item_script_patch(item),
        }
        insert_fields = {
            "created_at": now,
            "yt_metadata_id": None,
        }
        origin = item.get("origin")
        if origin in PLAN_ITEM_ORIGINS:
            patch["origin"] = origin
        else:
            insert_fields["origin"] = PLAN_ITEM_ORIGIN_GENERATED
        plan_items_col().update_one(
            {"id": item["id"]},
            {"$set": patch, "$setOnInsert": insert_fields},
            upsert=True,
        )
    plan_items_col().delete_many({"project_id": client_id, "id": {"$nin": keep}})


def replace_content_plan(client_id: str, client: dict) -> None:
    """Write the content plan for one client.

    Scripts live on plan_items. AI video→keyword maps live on videos docs.
    projects.content_plan stores planning metadata + keyword_analysis only.
    Always drops legacy projects.content_topic_coverage if still present.
    """
    has_suggestions = "content_suggestions" in client
    suggestions = client.get("content_suggestions")
    if has_suggestions and isinstance(suggestions, dict):
        suggestions = copy.deepcopy(suggestions)
        strip_yt_fields_from_suggestions(suggestions)
        # Sync scripts to plan_items while still present on items
        _sync_plan_items(client_id, suggestions)
        # Persist lean content_plan without script duplication
        strip_script_fields_from_suggestions(suggestions)
        projects_col().update_one(
            {"id": client_id},
            {
                "$set": {
                    "content_plan": suggestions,
                    "updated_at": _iso(),
                },
                "$unset": {"content_topic_coverage": ""},
            },
        )
    else:
        projects_col().update_one(
            {"id": client_id},
            {
                "$set": {"content_plan": {}, "updated_at": _iso()},
                "$unset": {"content_topic_coverage": ""},
            },
        )


def fetch_client_bundle(
    client_id: str,
    username: str,
    *,
    with_videos: bool = True,
    with_topics: bool = True,
    with_plan: bool = True,
) -> dict | None:
    """Assemble one client from collections (in-memory only)."""
    base = fetch_client_doc(client_id, username=username)
    if not base:
        return None
    topics = fetch_topics(client_id) if with_topics else []
    channels = list_channels_meta(client_id)
    if with_videos:
        channels = [
            {**ch, "videos": list_videos_for_channel(ch["id"], client_id)} for ch in channels
        ]
    client = {**base, "topics": topics, "channels": channels}
    if with_plan:
        plan = fetch_content_plan(client_id)
        if plan and plan.get("content_suggestions") is not None:
            client["content_suggestions"] = plan["content_suggestions"]
    return client


# ── content_videos (TG) == yt_metadata (Beacon) ──────────────────────────────


def content_video_doc_id(client_id: str, topic_id: str) -> str:
    return f"cv:{client_id}:{topic_id}"


def _empty_content_video(client_id: str, topic_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": content_video_doc_id(client_id, topic_id),
        "client_id": client_id,
        "topic_id": topic_id,
        "topic_text": "",
        "source": "manual",
        "content_plan_item_id": None,
        "yt_locales": {},
        "youtube_urls": [],
        "instagram_urls": [],
        "facebook_urls": [],
        "source_urls": [],
        "created_at": now,
        "updated_at": now,
    }


def _content_video_from_doc(doc: dict | None) -> dict | None:
    """yt_metadata doc (TG-keys or Beacon-keys or both) -> TG content_video row."""
    if not isinstance(doc, dict):
        return None
    row = _strip_mongo_id(doc)
    client_id = row.get("project_id") or row.get("client_id") or ""
    row["client_id"] = client_id
    row.setdefault("id", content_video_doc_id(client_id, row.get("topic_id") or ""))
    row.setdefault("source", "manual")
    if row.get("content_plan_item_id") is None:
        row["content_plan_item_id"] = row.get("plan_item_id")
    if not isinstance(row.get("yt_locales"), dict) or not row.get("yt_locales"):
        row["yt_locales"] = dict(row.get("locales") or {})
    posted = [p for p in (row.get("posted_urls") or []) if isinstance(p, dict)]
    for key, platform in (
        ("youtube_urls", "youtube"),
        ("instagram_urls", "instagram"),
        ("facebook_urls", "facebook"),
    ):
        if not row.get(key):
            row[key] = [dict(p) for p in posted if p.get("platform") == platform]
    if not row.get("source_urls"):
        row["source_urls"] = [
            {**p, "kind": p.get("platform")} for p in posted if p.get("platform") == "social"
        ]
    for key in ("posted_urls", "locales", "plan_item_id", "project_id", "youtube_video_ids"):
        row.pop(key, None)
    return row


def fetch_content_video(client_id: str, topic_id: str) -> dict | None:
    if not client_id or not topic_id:
        return None
    doc = yt_metadata_col().find_one({"project_id": client_id, "topic_id": topic_id}, {"_id": 0})
    return _content_video_from_doc(doc)


def list_content_videos_for_client(client_id: str) -> list[dict]:
    docs = yt_metadata_col().find({"project_id": client_id}, {"_id": 0})
    return [row for row in (_content_video_from_doc(d) for d in docs) if row]


def _persist_content_video(row: dict) -> dict:
    client_id = row["client_id"]
    topic_id = row["topic_id"]
    existing = yt_metadata_col().find_one(
        {"project_id": client_id, "topic_id": topic_id}, {"_id": 0, "id": 1, "created_at": 1}
    )
    doc_id = (existing or {}).get("id") or content_video_doc_id(client_id, topic_id)
    now = datetime.now(timezone.utc).isoformat()
    row["id"] = doc_id
    row.setdefault("created_at", (existing or {}).get("created_at") or now)
    row["updated_at"] = now
    row.setdefault("yt_locales", {})
    row.setdefault("youtube_urls", [])
    row.setdefault("instagram_urls", [])
    row.setdefault("facebook_urls", [])
    row.setdefault("source_urls", [])

    posted: list[dict] = []
    for platform, key in (
        ("youtube", "youtube_urls"),
        ("instagram", "instagram_urls"),
        ("facebook", "facebook_urls"),
    ):
        for entry in row.get(key) or []:
            if isinstance(entry, dict):
                posted.append({**entry, "platform": platform})
    for entry in row.get("source_urls") or []:
        if isinstance(entry, dict):
            # Keep Drive/file sources off live destination platforms (youtube/instagram/facebook).
            posted.append({**entry, "platform": "source"})
    youtube_ids = [
        str(e.get("video_id") or e.get("youtube_video_id"))
        for e in (row.get("youtube_urls") or [])
        if isinstance(e, dict) and (e.get("video_id") or e.get("youtube_video_id"))
    ]

    body = {k: v for k, v in row.items() if k not in ("id", "_id")}
    body.update(
        {
            "project_id": client_id,
            "plan_item_id": row.get("content_plan_item_id"),
            "locales": row.get("yt_locales") or {},
            "posted_urls": posted,
            "youtube_video_ids": youtube_ids,
        }
    )
    yt_metadata_col().update_one({"id": doc_id}, {"$set": body}, upsert=True)
    return row


def _normalize_locale_payload(locale: dict | None) -> dict:
    loc = dict(locale or {})
    tags = loc.get("yt_tags")
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.replace(",", " ").split() if t.strip()]
    elif not isinstance(tags, list):
        tags = []
    return {
        "yt_title": loc.get("yt_title") or "",
        "yt_description": loc.get("yt_description") or "",
        "yt_tags": [str(t).strip() for t in tags if str(t).strip()],
        "yt_thumbnail_url": loc.get("yt_thumbnail_url") or "",
        "yt_thumbnail_prompt": loc.get("yt_thumbnail_prompt") or "",
    }


def _locale_has_title(locale: dict | None) -> bool:
    if not isinstance(locale, dict):
        return False
    return bool(str(locale.get("yt_title") or "").strip())


def _row_has_yt_metadata(row: dict | None) -> bool:
    if not isinstance(row, dict):
        return False
    if str(row.get("yt_title") or "").strip():
        return True
    locales = row.get("yt_locales")
    if not isinstance(locales, dict):
        return False
    return any(_locale_has_title(loc) for loc in locales.values())


def strip_yt_fields_from_row(row: dict | None) -> bool:
    """Remove yt_* keys from a plan item / keyword_analysis row. True if anything changed."""
    if not isinstance(row, dict):
        return False
    changed = False
    for key in CONTENT_VIDEO_YT_KEYS:
        if key in row:
            row.pop(key, None)
            changed = True
    return changed


def strip_yt_fields_from_suggestions(suggestions: dict | None) -> bool:
    if not isinstance(suggestions, dict):
        return False
    changed = False
    for row in suggestions.get("items") or []:
        if isinstance(row, dict) and strip_yt_fields_from_row(row):
            changed = True
    for row in suggestions.get("keyword_analysis") or []:
        if isinstance(row, dict) and strip_yt_fields_from_row(row):
            changed = True
    return changed


def _locales_from_plan_row(row: dict | None) -> dict[str, dict]:
    if not isinstance(row, dict):
        return {}
    out: dict[str, dict] = {}
    nested = row.get("yt_locales")
    if isinstance(nested, dict):
        for lang, loc in nested.items():
            if not isinstance(loc, dict):
                continue
            payload = _normalize_locale_payload(loc)
            if payload.get("yt_title") or payload.get("yt_description") or payload.get("yt_thumbnail_url"):
                out[str(lang)] = payload
    if not out and (row.get("yt_title") or row.get("yt_description") or row.get("yt_thumbnail_url")):
        out["hinglish"] = _normalize_locale_payload(row)
    return out


def _mirror_legacy_yt_fields(row: dict, locales: dict | None) -> dict:
    loc_map = locales if isinstance(locales, dict) else {}
    hinglish = loc_map.get("hinglish") if isinstance(loc_map.get("hinglish"), dict) else {}
    fallback = next((v for v in loc_map.values() if isinstance(v, dict)), {}) or {}
    src = hinglish or fallback
    row["yt_locales"] = loc_map
    row["yt_title"] = src.get("yt_title") or None
    row["yt_description"] = src.get("yt_description") or None
    row["yt_tags"] = src.get("yt_tags") or None
    row["yt_thumbnail_url"] = src.get("yt_thumbnail_url") or None
    row["yt_thumbnail_prompt"] = src.get("yt_thumbnail_prompt") or None
    return row


def upsert_content_video(
    client_id: str,
    topic_id: str,
    *,
    topic_text: str | None = None,
    source: str | None = None,
    content_plan_item_id: str | None = None,
    locales: dict | None = None,
    replace_locales: bool = False,
    merge_missing_locales_only: bool = False,
) -> dict:
    """Create or update the produced-video package (production) for one client+topic."""
    existing = fetch_content_video(client_id, topic_id)
    row = existing or _empty_content_video(client_id, topic_id)
    if topic_text and not row.get("topic_text"):
        row["topic_text"] = topic_text
    elif topic_text and not merge_missing_locales_only:
        row["topic_text"] = topic_text
    if source:
        if source == "script" or row.get("source") != "script":
            row["source"] = source
    if content_plan_item_id:
        row["content_plan_item_id"] = content_plan_item_id
    incoming = {}
    if isinstance(locales, dict):
        for lang, loc in locales.items():
            if isinstance(loc, dict):
                incoming[str(lang)] = _normalize_locale_payload(loc)
    current = dict(row.get("yt_locales") or {})
    if replace_locales:
        current.update(incoming)
    elif merge_missing_locales_only:
        for lang, loc in incoming.items():
            if lang not in current or not _locale_has_title(current.get(lang)):
                current[lang] = loc
    elif incoming:
        current.update(incoming)
    row["yt_locales"] = current
    return _persist_content_video(row)


def append_content_video_posted_url(
    client_id: str,
    topic_id: str,
    platform: str,
    entry: dict,
) -> dict | None:
    """Append a posted watch/permalink URL. No-op if topic_id is missing or url is empty."""
    if not client_id or not topic_id:
        return None
    url = str((entry or {}).get("url") or "").strip()
    if not url:
        return None
    row = fetch_content_video(client_id, topic_id) or _empty_content_video(client_id, topic_id)
    key = {
        "youtube": "youtube_urls",
        "instagram": "instagram_urls",
        "facebook": "facebook_urls",
    }.get(platform)
    if not key:
        return row
    posted = dict(entry)
    posted["url"] = url
    posted.setdefault("posted_at", datetime.now(timezone.utc).isoformat())
    bucket = list(row.get(key) or [])
    if any(isinstance(item, dict) and item.get("url") == url for item in bucket):
        row[key] = bucket
        return _persist_content_video(row)
    bucket.append(posted)
    row[key] = bucket
    return _persist_content_video(row)


def append_content_video_source_url(client_id: str, topic_id: str, entry: dict) -> dict | None:
    """Append a pasted Drive/file URL. Dedupe by url + kind."""
    if not client_id or not topic_id:
        return None
    url = str((entry or {}).get("url") or "").strip()
    kind = str((entry or {}).get("kind") or "").strip()
    if not url or kind not in {"youtube", "social"}:
        return None
    row = fetch_content_video(client_id, topic_id) or _empty_content_video(client_id, topic_id)
    posted = dict(entry)
    posted["url"] = url
    posted["kind"] = kind
    posted.setdefault("posted_at", datetime.now(timezone.utc).isoformat())
    bucket = list(row.get("source_urls") or [])
    if any(
        isinstance(item, dict) and item.get("url") == url and item.get("kind") == kind
        for item in bucket
    ):
        row["source_urls"] = bucket
        return _persist_content_video(row)
    bucket.append(posted)
    row["source_urls"] = bucket
    return _persist_content_video(row)


def hydrate_suggestions_from_content_videos(client_id: str, suggestions: dict | None) -> dict:
    """Copy current yt locales onto plan items / keyword_analysis for API responses.

    Lazy-backfills leftover nested yt_* into productions, then strips the plan.
    """
    if not isinstance(suggestions, dict):
        return {}
    items = [row for row in (suggestions.get("items") or []) if isinstance(row, dict)]
    keywords = [row for row in (suggestions.get("keyword_analysis") or []) if isinstance(row, dict)]
    packages = {row.get("topic_id"): row for row in list_content_videos_for_client(client_id)}
    dirty = False

    def _ensure_package(topic_id: str, row: dict, *, source_hint: str, item_id: str | None, topic_text: str):
        nonlocal dirty
        pkg = packages.get(topic_id)
        leftover = _locales_from_plan_row(row) if _row_has_yt_metadata(row) else {}
        if leftover and not pkg:
            pkg = upsert_content_video(
                client_id,
                topic_id,
                topic_text=topic_text,
                source=source_hint,
                content_plan_item_id=item_id,
                locales=leftover,
            )
            packages[topic_id] = pkg
            if strip_yt_fields_from_row(row):
                dirty = True
        elif leftover and pkg:
            missing = False
            current = dict(pkg.get("yt_locales") or {})
            for lang, loc in leftover.items():
                if lang not in current or not _locale_has_title(current.get(lang)):
                    current[lang] = loc
                    missing = True
            if missing:
                pkg = upsert_content_video(
                    client_id,
                    topic_id,
                    topic_text=topic_text or pkg.get("topic_text") or "",
                    source=source_hint,
                    content_plan_item_id=item_id,
                    locales=leftover,
                    merge_missing_locales_only=True,
                )
                packages[topic_id] = pkg
            if strip_yt_fields_from_row(row):
                dirty = True
        elif _row_has_yt_metadata(row):
            if strip_yt_fields_from_row(row):
                dirty = True
        return pkg

    for item in items:
        topic_id = str(item.get("topic_id") or "").strip()
        if not topic_id:
            continue
        source_hint = "script" if item.get("script") else "manual"
        _ensure_package(
            topic_id,
            item,
            source_hint=source_hint,
            item_id=item.get("id"),
            topic_text=item.get("topic") or item.get("topic_text") or item.get("working_title") or "",
        )

    for kw in keywords:
        topic_id = str(kw.get("topic_id") or "").strip()
        if not topic_id:
            continue
        matching_item = next((it for it in items if it.get("topic_id") == topic_id), None)
        source_hint = "script" if matching_item and matching_item.get("script") else "manual"
        _ensure_package(
            topic_id,
            kw,
            source_hint=source_hint,
            item_id=(matching_item or {}).get("id") if matching_item else None,
            topic_text=kw.get("topic_text") or "",
        )

    for item in items:
        topic_id = str(item.get("topic_id") or "").strip()
        pkg = packages.get(topic_id) if topic_id else None
        if pkg:
            _mirror_legacy_yt_fields(item, pkg.get("yt_locales") or {})

    for kw in keywords:
        topic_id = str(kw.get("topic_id") or "").strip()
        pkg = packages.get(topic_id) if topic_id else None
        if pkg:
            _mirror_legacy_yt_fields(kw, pkg.get("yt_locales") or {})

    if dirty:
        replace_content_plan(client_id, {"content_suggestions": suggestions})
    return suggestions


# ── project_secrets helpers (app config / connections) ───────────────────────


def _secret_one(client_id: str, provider: str, kind: SecretKind) -> dict | None:
    return project_secrets_col().find_one(
        {"project_id": client_id, "provider": provider, "kind": kind.value}, {"_id": 0}
    )


def _secret_upsert(client_id: str, provider: str, kind: SecretKind, fields: dict, *, label: str) -> dict:
    existing = _secret_one(client_id, provider, kind)
    fields = {**fields, "updated_at": _iso(), "status": "active"}
    if existing:
        project_secrets_col().update_one({"id": existing["id"]}, {"$set": fields})
        return {**existing, **fields}
    doc = ProjectSecret(
        project_id=client_id, kind=kind, provider=provider, label=label
    ).model_dump(mode="json")
    doc.update(fields)
    project_secrets_col().insert_one(dict(doc))
    return doc


# Instagram / Facebook app configs ------------------------------------------


def _app_config_get(client_id: str, provider: str) -> dict | None:
    doc = _secret_one(client_id, provider, SecretKind.APP_CONFIG)
    if not doc:
        return None
    meta = doc.get("metadata") or {}
    return {
        "client_id": client_id,
        "app_id": doc.get("username") or meta.get("app_id") or "",
        "app_secret": doc.get("secret_encrypted"),
    }


def _app_config_save(client_id: str, provider: str, *, app_id: str | None, app_secret: str | None, extra: dict | None = None) -> dict:
    existing = _app_config_get(client_id, provider) or {}
    secret = app_secret if app_secret is not None else existing.get("app_secret")
    meta = {"app_id": app_id}
    if extra:
        meta["tg_extra"] = extra
    _secret_upsert(
        client_id,
        provider,
        SecretKind.APP_CONFIG,
        {"username": app_id, "secret_encrypted": secret, "metadata": meta},
        label=f"{provider} app",
    )
    return {"client_id": client_id, "app_id": app_id, "app_secret": secret, **(extra or {})}


def get_instagram_app_config(client_id: str) -> dict | None:
    return _app_config_get(client_id, "instagram")


def save_instagram_app_config(client_id: str, *, app_id: str, app_secret: str | None = None) -> dict:
    return _app_config_save(client_id, "instagram", app_id=app_id, app_secret=app_secret)


def get_facebook_app_config(client_id: str) -> dict | None:
    doc = _app_config_get(client_id, "facebook")
    if not doc:
        return None
    raw = _secret_one(client_id, "facebook", SecretKind.APP_CONFIG) or {}
    extra = (raw.get("metadata") or {}).get("tg_extra") or {}
    return {**doc, **extra}


def save_facebook_app_config(client_id: str, config: dict) -> dict:
    config = dict(config or {})
    app_id = config.pop("app_id", None)
    app_secret = config.pop("app_secret", None)
    config.pop("client_id", None)
    return _app_config_save(
        client_id, "facebook", app_id=app_id, app_secret=app_secret, extra=config or None
    )


# Instagram connection --------------------------------------------------------

_IG_MAPPED = {"client_id", "access_token", "instagram_user_id", "instagram_username", "permissions", "token_type", "expires_in"}


def get_instagram_connection(client_id: str) -> dict | None:
    doc = _secret_one(client_id, "instagram", SecretKind.OAUTH)
    if not doc:
        return None
    meta = doc.get("metadata") or {}
    row: dict[str, Any] = {
        "client_id": client_id,
        "access_token": doc.get("access_token_encrypted"),
        "instagram_user_id": doc.get("external_account_id"),
        "instagram_username": doc.get("external_account_name"),
        "permissions": meta.get("permissions"),
        "token_type": meta.get("token_type"),
        "expires_in": meta.get("expires_in"),
    }
    row.update(meta.get("tg_extra") or {})
    return row


def save_instagram_connection(client_id: str, connection: dict) -> dict:
    row = {"client_id": client_id, **connection}
    extra = {k: v for k, v in row.items() if k not in _IG_MAPPED}
    _secret_upsert(
        client_id,
        "instagram",
        SecretKind.OAUTH,
        {
            "access_token_encrypted": row.get("access_token"),
            "external_account_id": row.get("instagram_user_id"),
            "external_account_name": row.get("instagram_username"),
            "label": str(row.get("instagram_username") or "Instagram"),
            "metadata": {
                "permissions": row.get("permissions"),
                "token_type": row.get("token_type"),
                "expires_in": row.get("expires_in"),
                "tg_extra": extra,
            },
        },
        label="Instagram",
    )
    return row


# Facebook connection ---------------------------------------------------------

_FB_MAPPED = {
    "client_id",
    "access_token",
    "page_access_token",
    "facebook_user_id",
    "selected_page_id",
    "selected_page_name",
}


def get_facebook_connection(client_id: str) -> dict | None:
    doc = _secret_one(client_id, "facebook", SecretKind.OAUTH)
    if not doc:
        return None
    meta = doc.get("metadata") or {}
    stored = doc.get("access_token_encrypted")
    page_token = meta.get("page_access_token")
    user_token = meta.get("user_access_token")
    row: dict[str, Any] = {
        "client_id": client_id,
        "access_token": user_token or (stored if not page_token else None),
        "page_access_token": page_token,
        "facebook_user_id": meta.get("facebook_user_id"),
        "selected_page_id": meta.get("selected_page_id") or doc.get("external_account_id"),
        "selected_page_name": meta.get("selected_page_name") or doc.get("external_account_name"),
    }
    row.update(meta.get("tg_extra") or {})
    return row


def save_facebook_connection(client_id: str, payload: dict) -> dict:
    row = {"client_id": client_id, **payload}
    extra = {k: v for k, v in row.items() if k not in _FB_MAPPED}
    _secret_upsert(
        client_id,
        "facebook",
        SecretKind.OAUTH,
        {
            "access_token_encrypted": row.get("page_access_token") or row.get("access_token"),
            "external_account_id": row.get("selected_page_id") or row.get("facebook_user_id"),
            "external_account_name": row.get("selected_page_name"),
            "label": str(row.get("selected_page_name") or "Facebook"),
            "metadata": {
                "facebook_user_id": row.get("facebook_user_id"),
                "user_access_token": row.get("access_token"),
                "page_access_token": row.get("page_access_token"),
                "selected_page_id": row.get("selected_page_id"),
                "selected_page_name": row.get("selected_page_name"),
                "tg_extra": extra,
            },
        },
        label="Facebook",
    )
    return row


# OAuth state rows (no Beacon equivalent -> generic collection) ----------------


def _states_col():
    return get_db()["oauth_states"]


def _save_oauth_state(provider: str, state: str, payload: dict) -> dict:
    row = {"state": state, **payload}
    _states_col().replace_one(
        {"_id": f"{provider}:{state}"},
        {"_id": f"{provider}:{state}", "provider": provider, "created_at": utc_now(), **row},
        upsert=True,
    )
    return row


def _pop_oauth_state(provider: str, state: str) -> dict | None:
    doc = _states_col().find_one_and_delete({"_id": f"{provider}:{state}"})
    if not doc:
        return None
    out = _strip_mongo_id(doc)
    out.pop("provider", None)
    out.pop("created_at", None)
    return out


def save_instagram_oauth_state(state: str, payload: dict) -> dict:
    return _save_oauth_state("instagram", state, payload)


def pop_instagram_oauth_state(state: str) -> dict | None:
    return _pop_oauth_state("instagram", state)


def save_facebook_oauth_state(state: str, payload: dict) -> dict:
    return _save_oauth_state("facebook", state, payload)


def pop_facebook_oauth_state(state: str) -> dict | None:
    return _pop_oauth_state("facebook", state)


# ── social posts / schedule ──────────────────────────────────────────────────

_PUBLISH_TO_STATUS = {"draft": "draft", "scheduled": "queued", "published": "published"}
_STATUS_TO_PUBLISH = {"draft": "draft", "queued": "scheduled", "published": "published"}


def _social_post_from_doc(doc: dict) -> dict:
    """social_posts doc (TG fields and/or Beacon fields) -> TG post dict."""
    row = _strip_mongo_id(doc)
    project_id = row.get("project_id") or row.get("client_id")
    row["client_id"] = project_id
    if not row.get("publish_status"):
        row["publish_status"] = _STATUS_TO_PUBLISH.get(str(row.get("status") or "draft"), "draft")
    if not row.get("content_plan_item_id") and row.get("plan_item_id"):
        row["content_plan_item_id"] = row["plan_item_id"]
    if not row.get("platform"):
        targets = row.get("publish_targets") or []
        row["platform"] = targets[0] if targets else "instagram"
    return row


def save_social_post(post_id: str, post: dict) -> dict:
    row = {"id": post_id, **post}
    project_id = row.get("client_id") or row.get("project_id")
    body = {k: v for k, v in row.items() if k not in ("id", "_id", "created_at")}
    body["project_id"] = project_id
    body["client_id"] = project_id
    publish_status = row.get("publish_status")
    if publish_status:
        body["status"] = _PUBLISH_TO_STATUS.get(str(publish_status), "draft")
    if row.get("content_plan_item_id") is not None:
        body["plan_item_id"] = row["content_plan_item_id"]
    if not row.get("publish_targets") and row.get("platform"):
        body["publish_targets"] = [row["platform"]]
    body["updated_at"] = _iso()
    social_posts_col().update_one(
        {"id": post_id},
        {
            "$set": body,
            "$setOnInsert": {"created_at": row.get("created_at") or _iso()},
        },
        upsert=True,
    )
    return row


def fetch_social_post(post_id: str) -> dict | None:
    doc = social_posts_col().find_one({"id": post_id})
    return _social_post_from_doc(doc) if doc else None


def _posts_for_client(client_id: str) -> list[dict]:
    return [_social_post_from_doc(d) for d in social_posts_col().find({"project_id": client_id})]


def fetch_social_posts_for_source(
    client_id: str,
    *,
    content_plan_item_id: str | None = None,
    topic_id: str | None = None,
) -> list[dict]:
    if not content_plan_item_id and not topic_id:
        return []
    rows = []
    for post in _posts_for_client(client_id):
        if post.get("platform") != "instagram":
            continue
        if content_plan_item_id:
            if post.get("content_plan_item_id") != content_plan_item_id:
                continue
        elif post.get("topic_id") != topic_id:
            continue
        rows.append(post)
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def fetch_social_posts_by_source_type(client_id: str, source_type: str) -> list[dict]:
    """Newest-first posts of one source_type (replaces TG's direct collection query)."""
    rows = [p for p in _posts_for_client(client_id) if p.get("source_type") == source_type]
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def fetch_scheduled_posts(client_id: str) -> list[dict]:
    rows = [p for p in _posts_for_client(client_id) if p.get("publish_status") == "scheduled"]
    rows.sort(key=lambda r: (r.get("queue_order") if r.get("queue_order") is not None else 0))
    return rows


def fetch_latest_draft_post(client_id: str) -> dict | None:
    drafts = [p for p in _posts_for_client(client_id) if p.get("publish_status") in (None, "draft")]
    if not drafts:
        return None
    drafts.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return drafts[0]


def mark_social_post_selected(post_id: str) -> dict | None:
    post = fetch_social_post(post_id)
    if not post:
        return None
    platform = post.get("platform") or "instagram"
    use_script = post.get("source_type") == "script" and post.get("content_plan_item_id")
    for other in _posts_for_client(post["client_id"]):
        if other.get("platform") != platform:
            continue
        if use_script:
            same = other.get("content_plan_item_id") == post.get("content_plan_item_id")
        elif post.get("topic_id"):
            same = other.get("topic_id") == post.get("topic_id")
        else:
            same = other.get("id") == post_id
        if same:
            social_posts_col().update_one({"id": other["id"]}, {"$set": {"is_selected": False}})
    social_posts_col().update_one(
        {"id": post_id},
        {"$set": {"is_selected": True, "selected_at": _now_iso_for_db(), "updated_at": _iso()}},
    )
    return fetch_social_post(post_id)


def delete_social_post(post_id: str) -> dict | None:
    post = fetch_social_post(post_id)
    if not post:
        return None
    social_posts_col().delete_one({"id": post_id})
    return post


def save_social_schedule(client_id: str, schedule: dict) -> dict:
    body = {k: v for k, v in schedule.items() if k not in ("id", "_id", "client_id")}
    body["project_id"] = client_id
    body["updated_at"] = _iso()
    social_schedules_col().update_one(
        {"project_id": client_id},
        {"$set": body, "$setOnInsert": {"id": new_id("ssched")}},
        upsert=True,
    )
    return {"id": client_id, **schedule}


def fetch_social_schedule(client_id: str) -> dict | None:
    doc = social_schedules_col().find_one({"project_id": client_id}, {"_id": 0})
    if not doc:
        return None
    row = dict(doc)
    row.pop("project_id", None)
    row["id"] = client_id
    row["client_id"] = client_id
    return row


# ── monthly reports ──────────────────────────────────────────────────────────


def _report_from_doc(doc: dict) -> dict:
    row = _strip_mongo_id(doc)
    row["client_id"] = row.get("project_id") or row.get("client_id")
    return row


def fetch_monthly_report(report_id: str, *, username: str | None = None) -> dict | None:
    doc = monthly_reports_col().find_one({"id": report_id})
    if not doc:
        return None
    row = _report_from_doc(doc)
    if username and not _has_project_access(username, row["client_id"]):
        return None
    if username:
        row.setdefault("username", username)
    return row


def fetch_monthly_report_by_month(
    client_id: str,
    report_month: str,
    *,
    username: str | None = None,
) -> dict | None:
    if username and not _has_project_access(username, client_id):
        return None
    doc = monthly_reports_col().find_one({"project_id": client_id, "report_month": report_month})
    if not doc:
        return None
    row = _report_from_doc(doc)
    if username:
        row.setdefault("username", username)
    return row


def list_monthly_reports(client_id: str, *, username: str) -> list[dict]:
    """Report summaries (omit heavy metrics/html payloads)."""
    summary_keys = (
        "client_id",
        "username",
        "report_month",
        "previous_month",
        "ai_videos_started_from",
        "channel_ids",
        "status",
        "error",
        "created_at",
        "updated_at",
        "has_metrics_cache",
        "refine_history",
    )
    if not _has_project_access(username, client_id):
        return []
    try:  # services are copied later; degrade gracefully until then
        from .services.monthly_report_render import has_metrics_cache
    except ImportError:  # pragma: no cover

        def has_metrics_cache(_report_id: str) -> bool:
            return False

    out = []
    cursor = monthly_reports_col().find({"project_id": client_id}).sort("report_month", DESCENDING)
    for doc in cursor:
        row = _report_from_doc(doc)
        row.setdefault("username", username)
        slim = {k: row.get(k) for k in summary_keys if k in row or k == "has_metrics_cache"}
        slim["id"] = row["id"]
        slim["has_metrics_cache"] = has_metrics_cache(row["id"])
        slim["refine_history"] = list(row.get("refine_history") or [])[-5:]
        out.append(slim)
    return out


def upsert_monthly_report(report: dict) -> dict:
    """Insert or replace a report. Requires id, client_id, report_month.

    Metrics are never stored in DB (local file cache only). Beacon enforces one report
    per (project, month): a stale doc with a different id for the same month is replaced.
    """
    report_id = report["id"]
    client_id = report.get("client_id") or report.get("project_id")
    body = {k: v for k, v in report.items() if k not in {"id", "metrics", "_id", "created_at"}}
    body["project_id"] = client_id
    body["client_id"] = client_id
    now = _iso()
    body.setdefault("updated_at", now)
    created_at = report.get("created_at") or now

    def _write() -> None:
        monthly_reports_col().update_one(
            {"id": report_id},
            {"$set": body, "$setOnInsert": {"created_at": created_at}},
            upsert=True,
        )

    try:
        _write()
    except DuplicateKeyError:
        monthly_reports_col().delete_many(
            {
                "project_id": client_id,
                "report_month": body.get("report_month"),
                "id": {"$ne": report_id},
            }
        )
        _write()
    return fetch_monthly_report(report_id) or {"id": report_id, **body}


def update_monthly_report_fields(
    report_id: str,
    fields: dict[str, Any],
    *,
    unset: list[str] | None = None,
) -> dict | None:
    """Patch report fields. Use unset=['metrics'] to drop heavy payloads from DB."""
    unset_keys = list(unset or [])
    if "metrics" in fields:
        fields = {k: v for k, v in fields.items() if k != "metrics"}
        if "metrics" not in unset_keys:
            unset_keys.append("metrics")
    ops: dict[str, Any] = {}
    if fields:
        ops["$set"] = {**fields, "updated_at": fields.get("updated_at") or _iso()}
    if unset_keys:
        ops["$unset"] = {k: "" for k in unset_keys}
    if not ops:
        return fetch_monthly_report(report_id)
    result = monthly_reports_col().update_one({"id": report_id}, ops)
    if result.matched_count == 0:
        return None
    return fetch_monthly_report(report_id)


# ── trackers (TG shape already preserved in Beacon) ──────────────────────────


def weekly_tracker_doc_id(client_id: str, year: int, month: int, week: int) -> str:
    return f"weekly:{client_id}:{int(year)}:{int(month)}:{int(week)}"


def _tracker_out(doc: dict | None) -> dict | None:
    if not doc:
        return None
    row = _strip_mongo_id(doc)
    row["client_id"] = row.get("client_id") or row.get("project_id")
    return row


def fetch_weekly_tracker(client_id: str, year: int, month: int, week: int) -> dict | None:
    doc = weekly_trackers_col().find_one(
        {"project_id": client_id, "year": int(year), "month": int(month), "week": int(week)}
    )
    return _tracker_out(doc)


def fetch_weekly_trackers_by_ids(doc_ids: list[str]) -> dict[str, dict]:
    """Batch-load weekly tracker docs keyed by id (weekly:client:y:m:w)."""
    ids = [doc_id for doc_id in doc_ids if doc_id]
    if not ids:
        return {}
    out: dict[str, dict] = {}
    for doc in weekly_trackers_col().find({"id": {"$in": ids}}):
        row = _tracker_out(doc)
        if row and row.get("id"):
            out[str(row["id"])] = row
    return out


def fetch_custom_trackers_by_client_ids(client_ids: list[str]) -> dict[str, dict]:
    """Batch-load custom tracker docs keyed by client/project id."""
    ids = [client_id for client_id in client_ids if client_id]
    if not ids:
        return {}
    out: dict[str, dict] = {}
    for doc in custom_trackers_col().find({"project_id": {"$in": ids}}):
        row = _tracker_out(doc)
        client_id = str(row.get("client_id") or row.get("project_id") or "")
        if client_id:
            out[client_id] = row
    return out


def save_weekly_tracker(doc: dict) -> dict:
    client_id = doc["client_id"]
    year, month, week = int(doc["year"]), int(doc["month"]), int(doc["week"])
    doc_id = doc.get("id") or weekly_tracker_doc_id(client_id, year, month, week)
    row = {**doc, "id": doc_id, "client_id": client_id, "year": year, "month": month, "week": week}
    body = {k: v for k, v in row.items() if k not in ("id", "_id")}
    body["project_id"] = client_id
    weekly_trackers_col().update_one(
        {"project_id": client_id, "year": year, "month": month, "week": week},
        {"$set": body, "$setOnInsert": {"id": doc_id}},
        upsert=True,
    )
    return row


def list_weekly_trackers_for_month(client_id: str, year: int, month: int) -> list[dict]:
    docs = weekly_trackers_col().find(
        {"project_id": client_id, "year": int(year), "month": int(month)}
    )
    return [_tracker_out(d) for d in docs]


def list_weekly_trackers_for_client(client_id: str) -> list[dict]:
    return [_tracker_out(d) for d in weekly_trackers_col().find({"project_id": client_id})]


def custom_tracker_client_doc_id(client_id: str) -> str:
    return f"custom:{client_id}"


def custom_tracker_doc_id(client_id: str, year: int, month: int, week: int) -> str:
    return f"custom:{client_id}:{int(year)}:{int(month)}:{int(week)}"


def fetch_custom_tracker(client_id: str) -> dict | None:
    return _tracker_out(custom_trackers_col().find_one({"project_id": client_id}))


def save_custom_tracker(doc: dict) -> dict:
    client_id = doc["client_id"]
    doc_id = custom_tracker_client_doc_id(client_id)
    row = {**doc, "id": doc_id, "client_id": client_id, "tasks": list(doc.get("tasks") or [])}
    for key in ("issues", "year", "month", "week", "categories"):
        row.pop(key, None)
    body = {k: v for k, v in row.items() if k not in ("id", "_id")}
    body["project_id"] = client_id
    custom_trackers_col().update_one(
        {"project_id": client_id}, {"$set": body, "$setOnInsert": {"id": doc_id}}, upsert=True
    )
    return row


def list_legacy_custom_trackers(client_id: str) -> list[dict]:
    """Beacon keeps one custom tracker per project; legacy per-week docs don't exist."""
    return []


def list_tracker_script_placements(client_id: str) -> list[dict]:
    """Map content-plan item ids to tracker week cards that currently hold them."""
    out = []
    for doc in list_weekly_trackers_for_client(client_id):
        year = int(doc.get("year") or 0)
        month = int(doc.get("month") or 0)
        week = int(doc.get("week") or 0)
        for card in doc.get("cards") or []:
            if not isinstance(card, dict):
                continue
            item_id = str(card.get("content_plan_item_id") or "").strip()
            if not item_id:
                continue
            out.append(
                {
                    "item_id": item_id,
                    "year": year,
                    "month": month,
                    "week": week,
                    "card_id": card.get("id") or "",
                    "card_type": card.get("type") or "",
                }
            )
    return out


def sync_tracker_scripts_for_item(client_id: str, item_id: str, script_text: str) -> int:
    """Copy updated script text onto every tracker card linked to this plan item."""
    item_id = str(item_id or "").strip()
    if not client_id or not item_id:
        return 0
    updated = 0
    for doc in list_weekly_trackers_for_client(client_id):
        changed = False
        for card in doc.get("cards") or []:
            if not isinstance(card, dict):
                continue
            if str(card.get("content_plan_item_id") or "") != item_id:
                continue
            assets = dict(card.get("assets") or {})
            if assets.get("script_source") == "manual":
                continue
            assets["script_text"] = script_text or ""
            assets["script_url"] = ""
            assets["script_source"] = "plan"
            card["assets"] = assets
            changed = True
            updated += 1
        if changed:
            save_weekly_tracker(doc)
    return updated


def sheet_comment_doc_id(client_id: str, year: int, month: int, week: int, row_key: str) -> str:
    return f"sheet:{client_id}:{int(year)}:{int(month)}:{int(week)}:weekly:{row_key}"


def _sheet_col():
    return get_db()[COL_TRACKER_SHEET_COMMENTS]


def list_sheet_comments_for_month(
    client_id: str, year: int, month: int, tracker: str = "weekly"
) -> list[dict]:
    docs = _sheet_col().find(
        {"project_id": client_id, "year": int(year), "month": int(month), "tracker": tracker}
    )
    return [_tracker_out(d) for d in docs]


def save_sheet_comment(doc: dict) -> dict:
    client_id = doc["client_id"]
    year, month, week = int(doc["year"]), int(doc["month"]), int(doc["week"])
    row_key = str(doc["row_key"] or "").strip()
    tracker = str(doc.get("tracker") or "weekly").strip() or "weekly"
    doc_id = doc.get("id") or sheet_comment_doc_id(client_id, year, month, week, row_key)
    row = {
        **doc,
        "id": doc_id,
        "client_id": client_id,
        "year": year,
        "month": month,
        "week": week,
        "tracker": tracker,
        "row_key": row_key,
        "comment": str(doc.get("comment") or ""),
    }
    body = {k: v for k, v in row.items() if k not in ("id", "_id")}
    body["project_id"] = client_id
    _sheet_col().update_one({"id": doc_id}, {"$set": body}, upsert=True)
    return row


# ── doctor reference / client credentials ────────────────────────────────────


def fetch_doctor_reference(client_id: str) -> dict | None:
    doc = projects_col().find_one(
        {"id": client_id},
        {"_id": 0, "profile_sections": 1, "video_editor_id": 1, "long_video_hours": 1, "short_video_hours": 1, "name": 1, "specialty": 1, "designation": 1},
    )
    if not doc or not doc.get("profile_sections"):
        return None
    from backend.trackers.editors import ensure_editor_sections

    sections = ensure_editor_sections(
        doc.get("profile_sections") or [],
        doc.get("video_editor_id") or "",
        project=doc,
    )
    if not sections:
        return None
    return {
        "id": client_id,
        "client_id": client_id,
        "sections": sections,
    }


def save_doctor_reference(doc: dict) -> dict:
    from backend.trackers.editors import editor_value_from_sections, ensure_editor_sections, hours_values_from_sections

    client_id = doc["client_id"]
    existing = projects_col().find_one({"id": client_id}, {"_id": 0}) or {}
    sections = ensure_editor_sections(list(doc.get("sections") or []), project=existing)
    editor_id = editor_value_from_sections(sections)
    hours = hours_values_from_sections(sections, existing)
    projects_col().update_one(
        {"id": client_id},
        {
            "$set": {
                "profile_sections": sections,
                "video_editor_id": editor_id or None,
                "long_video_hours": hours["long_video_hours"],
                "short_video_hours": hours["short_video_hours"],
                "updated_at": _iso(),
            }
        },
    )
    return {**doc, "id": client_id, "client_id": client_id, "sections": sections}


def fetch_client_credentials(client_id: str) -> dict | None:
    rows = list(
        project_secrets_col().find(
            {"project_id": client_id, "kind": SecretKind.MANUAL.value}, {"_id": 0}
        )
    )
    if not rows:
        return None
    return {
        "id": client_id,
        "client_id": client_id,
        "credentials": [
            {
                "id": r.get("id"),
                "service": r.get("provider"),
                "username": r.get("username"),
                "password": r.get("secret_encrypted"),
                "notes": (r.get("metadata") or {}).get("notes") or "",
            }
            for r in rows
        ],
    }


def save_client_credentials(doc: dict) -> dict:
    client_id = doc["client_id"]
    project_secrets_col().delete_many({"project_id": client_id, "kind": SecretKind.MANUAL.value})
    saved = []
    for row in doc.get("credentials") or []:
        if not isinstance(row, dict):
            continue
        fields: dict[str, Any] = dict(
            project_id=client_id,
            kind=SecretKind.MANUAL,
            provider=str(row.get("service") or "portal"),
            label=str(row.get("service") or "Credential"),
            username=row.get("username"),
            secret_encrypted=row.get("password"),
            metadata={"notes": row.get("notes") or ""},
        )
        if row.get("id"):
            fields["id"] = row["id"]
        secret = ProjectSecret(**fields).model_dump(mode="json")
        project_secrets_col().insert_one(dict(secret))
        saved.append({**row, "id": secret["id"]})
    return {**doc, "id": client_id, "client_id": client_id, "credentials": saved}


# ── misc ─────────────────────────────────────────────────────────────────────


def collection_stats() -> dict[str, int]:
    return {
        "users": users_col().count_documents({}),
        "clients": projects_col().count_documents({}),
        "channels": channels_col().count_documents({}),
        "videos": videos_col().count_documents({}),
        "social_posts": social_posts_col().count_documents({}),
        "monthly_reports": monthly_reports_col().count_documents({}),
    }
