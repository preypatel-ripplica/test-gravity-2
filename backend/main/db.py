"""MongoDB connection and indexes for all Beacon collections."""

from __future__ import annotations

from typing import Optional

import certifi
from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from backend.socialmedia.models import COL_SOCIAL_POSTS, COL_SOCIAL_SCHEDULES
from backend.videos.models import (
    COL_CHANNELS,
    COL_MONTHLY_REPORTS,
    COL_PRODUCTIONS,
    COL_VIDEOS,
    COL_YT_METADATA,
)
from backend.website.models import (
    COL_CMS_API_KEYS,
    COL_CMS_COLLECTIONS,
    COL_CMS_ENTRIES,
    COL_CMS_MEDIA,
    COL_OAUTH_CONNECTIONS,
    COL_OAUTH_STATES,
    COL_WEBSITE_MONTHLY_REPORTS,
    COL_WEBSITE_SETTINGS,
)

from .config import MONGODB_DB_NAME, MONGODB_URI
from .models import (
    COL_ACCESS,
    COL_CUSTOM_TRACKERS,
    COL_PLAN_ITEMS,
    COL_PROJECT_SECRETS,
    COL_PROJECTS,
    COL_TASKS,
    COL_USERS,
    COL_WEEKLY_TRACKERS,
)

_client: Optional[MongoClient] = None
_indexes_ready = False


def get_client() -> MongoClient:
    global _client
    if not MONGODB_URI:
        raise RuntimeError(
            "MONGODB_URI is not set. Add it to beacon/.env before connecting."
        )
    if _client is None:
        _client = MongoClient(
            MONGODB_URI,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=15000,
            connectTimeoutMS=20000,
            socketTimeoutMS=45000,
            retryWrites=True,
            retryReads=True,
            maxPoolSize=25,
            minPoolSize=0,
        )
    return _client


def reset_client() -> None:
    """Drop the cached client so the next call opens a fresh TLS pool.

    Do not close() the old client here — concurrent requests may still hold it,
    and closing mid-flight raises ``Cannot use MongoClient after close``.
    """
    global _client, _indexes_ready
    _client = None
    _indexes_ready = False


def get_db() -> Database:
    return get_client()[MONGODB_DB_NAME]


def users_col() -> Collection:
    return get_db()[COL_USERS]


def projects_col() -> Collection:
    return get_db()[COL_PROJECTS]


def access_col() -> Collection:
    return get_db()[COL_ACCESS]


def project_secrets_col() -> Collection:
    return get_db()[COL_PROJECT_SECRETS]


def plan_items_col() -> Collection:
    return get_db()[COL_PLAN_ITEMS]


def tasks_col() -> Collection:
    """Deprecated. Prefer weekly_trackers_col / custom_trackers_col."""
    return get_db()[COL_TASKS]


def weekly_trackers_col() -> Collection:
    return get_db()[COL_WEEKLY_TRACKERS]


def custom_trackers_col() -> Collection:
    return get_db()[COL_CUSTOM_TRACKERS]


def channels_col() -> Collection:
    return get_db()[COL_CHANNELS]


def videos_col() -> Collection:
    return get_db()[COL_VIDEOS]


def yt_metadata_col() -> Collection:
    return get_db()[COL_YT_METADATA]


def productions_col() -> Collection:
    """Legacy alias for yt_metadata_col()."""
    return yt_metadata_col()


def monthly_reports_col() -> Collection:
    return get_db()[COL_MONTHLY_REPORTS]


def social_posts_col() -> Collection:
    return get_db()[COL_SOCIAL_POSTS]


def social_schedules_col() -> Collection:
    return get_db()[COL_SOCIAL_SCHEDULES]


def cms_collections_col() -> Collection:
    return get_db()[COL_CMS_COLLECTIONS]


def cms_entries_col() -> Collection:
    return get_db()[COL_CMS_ENTRIES]


def cms_media_col() -> Collection:
    return get_db()[COL_CMS_MEDIA]


def cms_api_keys_col() -> Collection:
    return get_db()[COL_CMS_API_KEYS]


def oauth_connections_col() -> Collection:
    return get_db()[COL_OAUTH_CONNECTIONS]


def oauth_states_col() -> Collection:
    return get_db()[COL_OAUTH_STATES]


def website_settings_col() -> Collection:
    return get_db()[COL_WEBSITE_SETTINGS]


def website_monthly_reports_col() -> Collection:
    return get_db()[COL_WEBSITE_MONTHLY_REPORTS]


def ensure_indexes() -> None:
    """Create indexes once per process. Safe to call on every startup."""
    global _indexes_ready
    if _indexes_ready:
        return

    users_col().create_index([("email", ASCENDING)], unique=True)
    users_col().create_index([("id", ASCENDING)], unique=True)

    projects_col().create_index([("id", ASCENDING)], unique=True)
    projects_col().create_index([("status", ASCENDING)])

    access_col().create_index([("id", ASCENDING)], unique=True)
    access_col().create_index([("user_id", ASCENDING)])
    access_col().create_index([("project_id", ASCENDING)])
    access_col().create_index(
        [("user_id", ASCENDING), ("project_id", ASCENDING), ("domain", ASCENDING)],
        unique=True,
    )

    project_secrets_col().create_index([("id", ASCENDING)], unique=True)
    project_secrets_col().create_index([("project_id", ASCENDING)])
    project_secrets_col().create_index(
        [("project_id", ASCENDING), ("provider", ASCENDING), ("kind", ASCENDING)]
    )

    plan_items_col().create_index([("id", ASCENDING)], unique=True)
    plan_items_col().create_index([("project_id", ASCENDING)])
    plan_items_col().create_index(
        [("project_id", ASCENDING), ("is_latest", ASCENDING)]
    )

    weekly_trackers_col().create_index([("id", ASCENDING)], unique=True)
    weekly_trackers_col().create_index([("project_id", ASCENDING)])
    weekly_trackers_col().create_index(
        [
            ("project_id", ASCENDING),
            ("year", ASCENDING),
            ("month", ASCENDING),
            ("week", ASCENDING),
        ],
        unique=True,
    )

    custom_trackers_col().create_index([("id", ASCENDING)], unique=True)
    custom_trackers_col().create_index([("project_id", ASCENDING)], unique=True)

    channels_col().create_index([("id", ASCENDING)], unique=True)
    channels_col().create_index([("project_id", ASCENDING)])

    videos_col().create_index([("id", ASCENDING)], unique=True)
    videos_col().create_index([("project_id", ASCENDING)])
    videos_col().create_index([("channel_id", ASCENDING)])
    videos_col().create_index([("project_id", ASCENDING), ("topic_id", ASCENDING)])

    yt_metadata_col().create_index([("id", ASCENDING)], unique=True)
    yt_metadata_col().create_index([("project_id", ASCENDING)])
    yt_metadata_col().create_index(
        [("project_id", ASCENDING), ("topic_id", ASCENDING)]
    )
    plan_items_col().create_index([("yt_metadata_id", ASCENDING)])

    monthly_reports_col().create_index([("id", ASCENDING)], unique=True)
    monthly_reports_col().create_index(
        [("project_id", ASCENDING), ("report_month", ASCENDING)],
        unique=True,
    )

    social_posts_col().create_index([("id", ASCENDING)], unique=True)
    social_posts_col().create_index([("project_id", ASCENDING)])
    social_posts_col().create_index(
        [("project_id", ASCENDING), ("status", ASCENDING)]
    )

    social_schedules_col().create_index([("id", ASCENDING)], unique=True)
    social_schedules_col().create_index([("project_id", ASCENDING)], unique=True)

    cms_collections_col().create_index([("id", ASCENDING)], unique=True)
    cms_collections_col().create_index([("project_id", ASCENDING)])
    cms_collections_col().create_index(
        [("project_id", ASCENDING), ("slug", ASCENDING)], unique=True
    )

    cms_entries_col().create_index([("id", ASCENDING)], unique=True)
    cms_entries_col().create_index([("project_id", ASCENDING)])
    cms_entries_col().create_index(
        [("project_id", ASCENDING), ("collection_id", ASCENDING)]
    )

    cms_media_col().create_index([("id", ASCENDING)], unique=True)
    cms_media_col().create_index([("project_id", ASCENDING)])

    cms_api_keys_col().create_index([("id", ASCENDING)], unique=True)
    cms_api_keys_col().create_index([("project_id", ASCENDING)])
    cms_api_keys_col().create_index([("key_hash", ASCENDING)], unique=True)

    oauth_connections_col().create_index([("connection_id", ASCENDING)], unique=True)
    oauth_connections_col().create_index(
        [("project_id", ASCENDING), ("provider", ASCENDING)], unique=True
    )
    oauth_connections_col().create_index([("status", ASCENDING)])

    # Shared with Instagram/Facebook OAuth; SEO rows use provider=google_seo
    oauth_states_col().create_index([("state", ASCENDING)])
    oauth_states_col().create_index([("provider", ASCENDING)])
    oauth_states_col().create_index(
        [("expires_at", ASCENDING)], expireAfterSeconds=0
    )

    website_settings_col().create_index([("project_id", ASCENDING)], unique=True)

    website_monthly_reports_col().create_index([("id", ASCENDING)], unique=True)
    website_monthly_reports_col().create_index(
        [("project_id", ASCENDING), ("report_month", ASCENDING)],
        unique=True,
    )

    _indexes_ready = True


def ping() -> dict:
    return get_client().admin.command("ping")


def close() -> None:
    global _client, _indexes_ready
    if _client is not None:
        _client.close()
        _client = None
    _indexes_ready = False
