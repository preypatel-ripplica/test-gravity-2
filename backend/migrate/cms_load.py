"""Write CMS website bundle into Beacon (does not wipe Videos/Social)."""

from __future__ import annotations

from typing import Any

from backend.main.db import (
    access_col,
    cms_api_keys_col,
    cms_collections_col,
    cms_entries_col,
    cms_media_col,
    ensure_indexes,
    projects_col,
    users_col,
)
from backend.main.models import Domain

from .cms_build import make_website_access
from .cms_config import BEACON_SUPERUSER_EMAIL


CMS_WIPE_COLS = (
    cms_collections_col,
    cms_entries_col,
    cms_media_col,
    cms_api_keys_col,
)


def wipe_cms_only() -> dict[str, int]:
    ensure_indexes()
    out = {}
    for fn in CMS_WIPE_COLS:
        col = fn()
        out[col.name] = col.delete_many({}).deleted_count
    # Remove website-only access rows? Keep them — grants stay valid.
    return out


def _upsert_many(col, docs: list[dict[str, Any]], id_field: str = "id") -> int:
    n = 0
    for doc in docs:
        if not doc.get(id_field):
            continue
        col.update_one({id_field: doc[id_field]}, {"$set": doc}, upsert=True)
        n += 1
    return n


def write_cms_bundle(bundle: dict[str, Any]) -> dict[str, int]:
    ensure_indexes()
    written = {}

    # New projects first
    projects = bundle.get("projects") or []
    n_proj = 0
    for doc in projects:
        if not projects_col().find_one({"id": doc["id"]}):
            projects_col().insert_one(doc)
            n_proj += 1
    written["projects_created"] = n_proj

    written["cms_collections"] = _upsert_many(
        cms_collections_col(), bundle.get("cms_collections") or []
    )
    written["cms_entries"] = _upsert_many(
        cms_entries_col(), bundle.get("cms_entries") or []
    )
    written["cms_media"] = _upsert_many(cms_media_col(), bundle.get("cms_media") or [])
    written["cms_api_keys"] = _upsert_many(
        cms_api_keys_col(), bundle.get("cms_api_keys") or []
    )

    # Grant website domain to Beacon superuser for all touched projects
    superuser = users_col().find_one(
        {"email": BEACON_SUPERUSER_EMAIL}, {"_id": 0, "id": 1}
    )
    if superuser and bundle.get("project_ids"):
        grants = make_website_access(superuser["id"], bundle["project_ids"])
        n_access = 0
        for g in grants:
            access_col().update_one(
                {
                    "user_id": g["user_id"],
                    "project_id": g["project_id"],
                    "domain": Domain.WEBSITE.value,
                },
                {"$setOnInsert": g},
                upsert=True,
            )
            n_access += 1
        written["website_access_grants"] = n_access
    else:
        written["website_access_grants"] = 0

    return written
