"""Write migrated documents into Beacon (destination only)."""

from __future__ import annotations

from typing import Any, Iterable

from backend.main.auth import hash_password
from backend.main.db import (
    access_col,
    channels_col,
    custom_trackers_col,
    ensure_indexes,
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
)
from backend.main.models import Domain

from . import transform as T
from .config import (
    BEACON_SUPERUSER_EMAIL,
    BEACON_SUPERUSER_NAME,
    require_superuser_password,
)

PRODUCT_COLLECTIONS = (
    "access",
    "projects",
    "project_secrets",
    "plan_items",
    "tasks",  # legacy combined collection — clear on wipe
    "weekly_trackers",
    "custom_trackers",
    "channels",
    "videos",
    "productions",
    "yt_metadata",
    "monthly_reports",
    "social_posts",
    "social_schedules",
)


def wipe_product_data(*, keep_users: bool = False) -> dict[str, int]:
    """Delete Beacon product collections. Optionally wipe all users too."""
    ensure_indexes()
    deleted: dict[str, int] = {}
    db = get_db()
    for name in PRODUCT_COLLECTIONS:
        result = db[name].delete_many({})
        deleted[name] = result.deleted_count
    if not keep_users:
        deleted["users"] = users_col().delete_many({}).deleted_count
    return deleted


def upsert_superuser(*, wipe: bool) -> dict[str, Any]:
    password = require_superuser_password(wipe=wipe)
    if not password:
        existing = users_col().find_one(
            {"email": BEACON_SUPERUSER_EMAIL}, {"_id": 0}
        )
        if existing:
            return existing
        raise SystemExit("BEACON_SUPERUSER_PASSWORD required to create superuser")

    password_hash = hash_password(password)
    existing = users_col().find_one({"email": BEACON_SUPERUSER_EMAIL}, {"_id": 0})
    if existing:
        users_col().update_one(
            {"email": BEACON_SUPERUSER_EMAIL},
            {
                "$set": {
                    "password_hash": password_hash,
                    "name": BEACON_SUPERUSER_NAME,
                    "type": "internal",
                    "is_active": True,
                }
            },
        )
        return users_col().find_one({"email": BEACON_SUPERUSER_EMAIL}, {"_id": 0})

    doc = T.make_superuser(
        email=BEACON_SUPERUSER_EMAIL,
        name=BEACON_SUPERUSER_NAME,
        password_hash=password_hash,
    )
    users_col().insert_one(doc)
    doc.pop("_id", None)
    return doc


def _insert_many(col, docs: Iterable[dict[str, Any]]) -> int:
    batch = []
    for doc in docs:
        if not doc:
            continue
        row = {**doc}
        row.pop("_id", None)
        batch.append(row)
    if not batch:
        return 0
    # chunk to avoid huge payloads
    total = 0
    size = 500
    for i in range(0, len(batch), size):
        chunk = batch[i : i + size]
        col.insert_many(chunk, ordered=False)
        total += len(chunk)
    return total


def grant_superuser_access(user_id: str, project_ids: list[str]) -> int:
    docs = []
    for pid in project_ids:
        docs.append(T.make_access(user_id, pid, Domain.VIDEOS))
        docs.append(T.make_access(user_id, pid, Domain.SOCIALMEDIA))
        docs.append(T.make_access(user_id, pid, Domain.WEBSITE))
    return _insert_many(access_col(), docs)


def write_bundle(bundle: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    ensure_indexes()
    written = {
        "projects": _insert_many(projects_col(), bundle.get("projects") or []),
        "project_secrets": _insert_many(
            project_secrets_col(), bundle.get("project_secrets") or []
        ),
        "plan_items": _insert_many(plan_items_col(), bundle.get("plan_items") or []),
        "weekly_trackers": _insert_many(
            weekly_trackers_col(), bundle.get("weekly_trackers") or []
        ),
        "custom_trackers": _insert_many(
            custom_trackers_col(), bundle.get("custom_trackers") or []
        ),
        "channels": _insert_many(channels_col(), bundle.get("channels") or []),
        "videos": _insert_many(videos_col(), bundle.get("videos") or []),
        "yt_metadata": _insert_many(
            yt_metadata_col(),
            bundle.get("yt_metadata") or bundle.get("productions") or [],
        ),
        "monthly_reports": _insert_many(
            monthly_reports_col(), bundle.get("monthly_reports") or []
        ),
        "social_posts": _insert_many(
            social_posts_col(), bundle.get("social_posts") or []
        ),
        "social_schedules": _insert_many(
            social_schedules_col(), bundle.get("social_schedules") or []
        ),
    }
    return written
