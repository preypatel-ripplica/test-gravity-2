"""Read-only access to CMS_NEW Mongo (collections / entries / media / …)."""

from __future__ import annotations

from typing import Any, Iterator, Optional

import certifi
from pymongo import MongoClient, ReadPreference
from pymongo.database import Database

from .cms_config import CMS_MONGO_DB_NAME, require_cms_source

_client: Optional[MongoClient] = None

COL_USERS = "users"
COL_COLLECTIONS = "collections"
COL_ENTRIES = "entries"
COL_MEDIA = "media"
COL_API_KEYS = "api_keys"


def get_client() -> MongoClient:
    global _client
    uri = require_cms_source()
    if _client is None:
        _client = MongoClient(
            uri,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=20000,
            read_preference=ReadPreference.SECONDARY_PREFERRED,
        )
    return _client


def cms_db() -> Database:
    return get_client()[CMS_MONGO_DB_NAME]


def iter_collection(name: str) -> Iterator[dict[str, Any]]:
    for doc in cms_db()[name].find({}, {"_id": 0}):
        yield doc


def ping_source() -> dict[str, Any]:
    db = cms_db()
    db.command("ping")
    names = set(db.list_collection_names())
    counts = {}
    for name in (
        COL_USERS,
        COL_COLLECTIONS,
        COL_ENTRIES,
        COL_MEDIA,
        COL_API_KEYS,
    ):
        counts[name] = db[name].estimated_document_count() if name in names else 0
    return {"db": CMS_MONGO_DB_NAME, "counts": counts}


def close_source() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
