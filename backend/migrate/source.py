"""Read-only access to the Test-Gravity Mongo database."""

from __future__ import annotations

from typing import Any, Iterator

import certifi
from pymongo import MongoClient, ReadPreference
from pymongo.database import Database

from .config import TG_MONGODB_DB_NAME, require_source_uri

# TG collection names (mirror test-gravity/backend/app/database.py)
COL_CLIENTS = "clients"
COL_TOPICS = "topics"
COL_CHANNELS = "channels"
COL_VIDEOS = "videos"
COL_CONTENT_PLANS = "content_plans"
COL_CONTENT_VIDEOS = "content_videos"
COL_SOCIAL_POSTS = "social_posts"
COL_SOCIAL_SCHEDULES = "social_schedules"
COL_WEEKLY_TRACKERS = "weekly_trackers"
COL_CUSTOM_TRACKERS = "custom_trackers"
COL_MONTHLY_REPORTS = "monthly_reports"
COL_DOCTOR_REFERENCES = "doctor_references"
COL_CLIENT_CREDENTIALS = "client_credentials"
COL_IG_APP = "instagram_app_configs"
COL_IG_CONN = "instagram_connections"
COL_FB_APP = "facebook_app_configs"
COL_FB_CONN = "facebook_connections"
COL_USERS = "users"

COUNTED_COLLECTIONS = (
    COL_CLIENTS,
    COL_TOPICS,
    COL_CHANNELS,
    COL_VIDEOS,
    COL_CONTENT_PLANS,
    COL_CONTENT_VIDEOS,
    COL_SOCIAL_POSTS,
    COL_SOCIAL_SCHEDULES,
    COL_WEEKLY_TRACKERS,
    COL_CUSTOM_TRACKERS,
    COL_MONTHLY_REPORTS,
    COL_DOCTOR_REFERENCES,
    COL_CLIENT_CREDENTIALS,
    COL_IG_APP,
    COL_IG_CONN,
    COL_FB_APP,
    COL_FB_CONN,
    COL_USERS,
)

_client: MongoClient | None = None


def tg_client() -> MongoClient:
    global _client
    if _client is None:
        uri = require_source_uri()
        _client = MongoClient(
            uri,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=30000,
            # Source is read-only — allow secondaries if primary is electing
            read_preference=ReadPreference.SECONDARY_PREFERRED,
        )
    return _client


def tg_db() -> Database:
    return tg_client().get_database(
        TG_MONGODB_DB_NAME, read_preference=ReadPreference.SECONDARY_PREFERRED
    )


def close_source() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def strip_id(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    row = {**doc}
    mongo_id = row.pop("_id", None)
    if mongo_id is not None and "id" not in row:
        row["id"] = str(mongo_id)
    elif mongo_id is not None:
        row.setdefault("_mongo_id", str(mongo_id))
    return row


def iter_collection(name: str) -> Iterator[dict[str, Any]]:
    for doc in tg_db()[name].find({}):
        row = strip_id(doc)
        if row:
            yield row


def count_all() -> dict[str, int]:
    db = tg_db()
    existing = set(db.list_collection_names())
    return {
        name: (db[name].estimated_document_count() if name in existing else 0)
        for name in COUNTED_COLLECTIONS
    }


def ping_source() -> dict[str, Any]:
    tg_client().admin.command("ping")
    return {
        "db": TG_MONGODB_DB_NAME,
        "collections": sorted(tg_db().list_collection_names()),
        "counts": count_all(),
    }
