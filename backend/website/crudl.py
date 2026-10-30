"""Website domain CRUDL — CMS_NEW-style collections, entries, media, content API."""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field

from backend.main.access_guards import require_domain_access, require_internal
from backend.main.auth import current_user
from backend.main.config import SECRET_KEY
from backend.main.db import (
    cms_api_keys_col,
    cms_collections_col,
    cms_entries_col,
    cms_media_col,
)
from backend.main.models import Domain, utc_now
from backend.main.project_scope import WithProjectId
from backend.website.generation import generate_entry_draft
from backend.website.models import CmsApiKey, CmsCollection, CmsEntry, CmsMedia, EntryStatus
from backend.website.schema_presets import (
    SCHEMA_PRESETS,
    normalize_schema_value,
    resolve_preset_schema,
)

router = APIRouter(tags=["website"])
DOMAIN = Domain.WEBSITE


def _clean(doc: dict | None) -> dict | None:
    if not doc:
        return None
    doc = {**doc}
    doc.pop("_id", None)
    return jsonable_encoder(doc)


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return text or "collection"


def _public_collection(doc: dict) -> dict:
    """Normalize stored collection for API (schema + legacy entry_schema)."""
    out = _clean(doc) or {}
    schema = out.get("schema")
    if schema is None and "entry_schema" in out:
        schema = out.get("entry_schema") or {}
        out["schema"] = schema
    elif schema is None:
        out["schema"] = {}
    # Keep entry_schema as alias for older UI
    out["entry_schema"] = out.get("schema") or {}
    return out


def _public_entry(doc: dict) -> dict:
    out = _clean(doc) or {}
    if "entry" not in out and "data" in out:
        out["entry"] = out.get("data") or {}
    if "data" not in out:
        out["data"] = out.get("entry") or {}
    return out


def _media_response(doc: dict) -> dict:
    media = _clean(doc) or {}
    media["preview_url"] = media.get("url")
    media["download_url"] = media.get("url")
    return media


def _hash_api_token(token: str) -> str:
    return hashlib.sha256(f"{SECRET_KEY}:{token}".encode("utf-8")).hexdigest()


def _create_raw_api_token() -> str:
    return f"cms_live_{secrets.token_urlsafe(32)}"


def _public_api_key(doc: dict) -> dict:
    out = _clean(doc) or {}
    out.pop("key_hash", None)
    return out


# --- bodies ---


class ProjectBody(WithProjectId):
    pass


class CollectionGetBody(WithProjectId):
    collection_id: str


class CollectionCreateBody(WithProjectId):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    slug: Optional[str] = None
    preset: Optional[str] = None  # blogs | products | pages | other
    schema_: Optional[dict[str, Any]] = Field(default=None, alias="schema")
    entry_schema: Optional[dict[str, Any]] = None  # legacy
    ai_context: dict[str, Any] = Field(default_factory=dict)


class CollectionUpdateBody(WithProjectId):
    model_config = ConfigDict(populate_by_name=True)

    collection_id: str
    name: Optional[str] = None
    slug: Optional[str] = None
    schema_: Optional[dict[str, Any]] = Field(default=None, alias="schema")
    entry_schema: Optional[dict[str, Any]] = None
    ai_context: Optional[dict[str, Any]] = None


class EntryListBody(WithProjectId):
    collection_id: str
    status: Optional[str] = None


class EntryGetBody(WithProjectId):
    entry_id: str


class EntryCreateBody(WithProjectId):
    collection_id: str
    entry: Optional[dict[str, Any]] = None
    data: Optional[dict[str, Any]] = None  # legacy
    status: str = "draft"


class EntryUpdateBody(WithProjectId):
    entry_id: str
    entry: Optional[dict[str, Any]] = None
    data: Optional[dict[str, Any]] = None
    status: Optional[str] = None
    collection_id: Optional[str] = None


class EntryGenerateBody(WithProjectId):
    collection_id: str
    prompt: str = ""


class MediaCreateBody(WithProjectId):
    url: str
    filename: str = ""
    alt_text: str = ""
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MediaUpdateBody(WithProjectId):
    media_id: str
    url: Optional[str] = None
    filename: Optional[str] = None
    alt_text: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    metadata: Optional[dict[str, Any]] = None


class MediaGetBody(WithProjectId):
    media_id: str


class ApiTokenCreateBody(WithProjectId):
    name: str = "Production website"
    scopes: Optional[list[str]] = None


class ApiTokenGetBody(WithProjectId):
    api_key_id: str


class ContentEntriesListBody(BaseModel):
    collection_slug: str
    limit: int = 100


class ContentMediaGetBody(BaseModel):
    media_id: str


# --- presets ---


@router.post("/website.schema.presets")
def schema_presets(_auth: dict = Depends(current_user)):
    return {
        "presets": [
            {"id": key, "label": val["label"], "description": val["description"], "schema": val["schema"]}
            for key, val in SCHEMA_PRESETS.items()
        ]
    }


# --- collections ---


@router.post("/website.collection.list")
def collection_list(body: ProjectBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    rows = list(
        cms_collections_col()
        .find({"project_id": body.project_id}, {"_id": 0})
        .sort("name", 1)
    )
    return {"collections": [_public_collection(r) for r in rows]}


@router.post("/website.collection.get")
def collection_get(body: CollectionGetBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    doc = cms_collections_col().find_one(
        {"id": body.collection_id, "project_id": body.project_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Collection not found")
    return _public_collection(doc)


@router.post("/website.collection.create")
def collection_create(body: CollectionCreateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name is required")
    slug = _slugify(body.slug or name)
    existing = cms_collections_col().find_one(
        {"project_id": body.project_id, "slug": slug}, {"_id": 0}
    )
    if existing:
        raise HTTPException(409, "Collection slug already exists")
    schema = resolve_preset_schema(
        body.preset,
        body.schema_ if body.schema_ is not None else body.entry_schema,
    )
    doc = CmsCollection(
        project_id=body.project_id,
        name=name,
        slug=slug,
        schema_=schema,
        ai_context=body.ai_context or {},
    ).model_dump(mode="json", by_alias=True)
    doc["entry_schema"] = doc.get("schema") or {}
    cms_collections_col().insert_one(doc)
    return _public_collection(doc)


@router.post("/website.collection.update")
def collection_update(body: CollectionUpdateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    if not cms_collections_col().find_one(
        {"id": body.collection_id, "project_id": body.project_id}
    ):
        raise HTTPException(404, "Collection not found")
    patch: dict[str, Any] = {"updated_at": utc_now()}
    if body.name is not None:
        patch["name"] = body.name.strip()
    if body.slug is not None:
        patch["slug"] = _slugify(body.slug)
    schema_in = body.schema_ if body.schema_ is not None else body.entry_schema
    if schema_in is not None:
        patch["schema"] = normalize_schema_value(schema_in)
        patch["entry_schema"] = patch["schema"]  # keep legacy field in sync
    if body.ai_context is not None:
        patch["ai_context"] = body.ai_context
    cms_collections_col().update_one(
        {"id": body.collection_id, "project_id": body.project_id}, {"$set": patch}
    )
    return _public_collection(
        cms_collections_col().find_one(
            {"id": body.collection_id, "project_id": body.project_id}, {"_id": 0}
        )
    )


@router.post("/website.collection.delete")
def collection_delete(body: CollectionGetBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    result = cms_collections_col().delete_one(
        {"id": body.collection_id, "project_id": body.project_id}
    )
    if result.deleted_count == 0:
        raise HTTPException(404, "Collection not found")
    cms_entries_col().delete_many(
        {"collection_id": body.collection_id, "project_id": body.project_id}
    )
    return {"deleted": True, "collection_id": body.collection_id}


# --- entries ---


@router.post("/website.entry.list")
def entry_list(body: EntryListBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    query: dict[str, Any] = {
        "project_id": body.project_id,
        "collection_id": body.collection_id,
    }
    if body.status:
        query["status"] = body.status
    rows = list(cms_entries_col().find(query, {"_id": 0}).sort("updated_at", -1))
    return {"entries": [_public_entry(r) for r in rows]}


@router.post("/website.entry.get")
def entry_get(body: EntryGetBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    doc = cms_entries_col().find_one(
        {"id": body.entry_id, "project_id": body.project_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Entry not found")
    return _public_entry(doc)


@router.post("/website.entry.create")
def entry_create(body: EntryCreateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    if not cms_collections_col().find_one(
        {"id": body.collection_id, "project_id": body.project_id}
    ):
        raise HTTPException(404, "Collection not found")
    try:
        status = EntryStatus(body.status)
    except ValueError:
        status = EntryStatus.DRAFT
    payload = body.entry if body.entry is not None else (body.data or {})
    doc = CmsEntry(
        project_id=body.project_id,
        collection_id=body.collection_id,
        entry=payload,
        status=status,
        published_at=utc_now() if status == EntryStatus.PUBLISHED else None,
    ).model_dump(mode="json")
    # Dual-write legacy `data` for older readers
    doc["data"] = doc.get("entry") or {}
    cms_entries_col().insert_one(doc)
    return _public_entry(doc)


@router.post("/website.entry.update")
def entry_update(body: EntryUpdateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    existing = cms_entries_col().find_one(
        {"id": body.entry_id, "project_id": body.project_id}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(404, "Entry not found")
    patch: dict[str, Any] = {"updated_at": utc_now()}
    payload = body.entry if body.entry is not None else body.data
    if payload is not None:
        patch["entry"] = payload
        patch["data"] = payload
    if body.collection_id is not None:
        if not cms_collections_col().find_one(
            {"id": body.collection_id, "project_id": body.project_id}
        ):
            raise HTTPException(404, "Collection not found")
        patch["collection_id"] = body.collection_id
    if body.status is not None:
        try:
            status = EntryStatus(body.status)
        except ValueError:
            raise HTTPException(400, "Invalid status")
        patch["status"] = status.value
        if status == EntryStatus.PUBLISHED and not existing.get("published_at"):
            patch["published_at"] = utc_now()
    cms_entries_col().update_one(
        {"id": body.entry_id, "project_id": body.project_id}, {"$set": patch}
    )
    return _public_entry(
        cms_entries_col().find_one(
            {"id": body.entry_id, "project_id": body.project_id}, {"_id": 0}
        )
    )


@router.post("/website.entry.delete")
def entry_delete(body: EntryGetBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    result = cms_entries_col().delete_one(
        {"id": body.entry_id, "project_id": body.project_id}
    )
    if result.deleted_count == 0:
        raise HTTPException(404, "Entry not found")
    return {"deleted": True, "entry_id": body.entry_id}


@router.post("/website.entry.generate")
def entry_generate(body: EntryGenerateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    collection = cms_collections_col().find_one(
        {"id": body.collection_id, "project_id": body.project_id}, {"_id": 0}
    )
    if not collection:
        raise HTTPException(404, "Collection not found")
    schema = collection.get("schema") or collection.get("entry_schema") or {}
    samples = list(
        cms_entries_col()
        .find(
            {
                "collection_id": body.collection_id,
                "project_id": body.project_id,
                "status": {"$ne": EntryStatus.ARCHIVED.value},
            },
            {"_id": 0},
        )
        .sort("updated_at", -1)
        .limit(5)
    )
    return generate_entry_draft(
        schema=schema,
        collection=_public_collection(collection),
        samples=samples,
        prompt=body.prompt or "",
    )


# --- media ---


@router.post("/website.media.list")
def media_list(body: ProjectBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    rows = list(
        cms_media_col()
        .find({"project_id": body.project_id}, {"_id": 0})
        .sort("created_at", -1)
    )
    return {"media": [_media_response(r) for r in rows]}


@router.post("/website.media.get")
def media_get(body: MediaGetBody, auth: dict = Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    doc = cms_media_col().find_one(
        {"id": body.media_id, "project_id": body.project_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Media not found")
    return _media_response(doc)


@router.post("/website.media.create")
def media_create(body: MediaCreateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    if not (body.url or "").strip():
        raise HTTPException(400, "url is required")
    doc = CmsMedia(
        project_id=body.project_id,
        url=body.url.strip(),
        filename=body.filename or "",
        alt_text=body.alt_text or "",
        content_type=body.content_type,
        size_bytes=body.size_bytes,
        metadata=body.metadata,
    ).model_dump(mode="json")
    cms_media_col().insert_one(doc)
    return _media_response(doc)


@router.post("/website.media.update")
def media_update(body: MediaUpdateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    if not cms_media_col().find_one(
        {"id": body.media_id, "project_id": body.project_id}
    ):
        raise HTTPException(404, "Media not found")
    patch: dict[str, Any] = {"updated_at": utc_now()}
    for key in ("url", "filename", "alt_text", "content_type", "size_bytes", "metadata"):
        val = getattr(body, key)
        if val is not None:
            patch[key] = val.strip() if isinstance(val, str) and key in ("url", "filename", "alt_text") else val
    cms_media_col().update_one(
        {"id": body.media_id, "project_id": body.project_id}, {"$set": patch}
    )
    return _media_response(
        cms_media_col().find_one(
            {"id": body.media_id, "project_id": body.project_id}, {"_id": 0}
        )
    )


@router.post("/website.media.delete")
def media_delete(body: MediaGetBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    result = cms_media_col().delete_one(
        {"id": body.media_id, "project_id": body.project_id}
    )
    if result.deleted_count == 0:
        raise HTTPException(404, "Media not found")
    return {"deleted": True, "media_id": body.media_id}


# --- API tokens (public content access) ---


@router.post("/website.api_token.create")
def api_token_create(body: ApiTokenCreateBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    raw = _create_raw_api_token()
    prefix = raw[:16]
    scopes = body.scopes or ["content:read", "media:read"]
    doc = CmsApiKey(
        project_id=body.project_id,
        name=(body.name or "Production website").strip() or "Production website",
        key_prefix=prefix,
        key_hash=_hash_api_token(raw),
        scopes=scopes,
    ).model_dump(mode="json")
    cms_api_keys_col().insert_one(doc)
    out = _public_api_key(doc)
    out["token"] = raw  # shown once
    return out


@router.post("/website.api_token.list")
def api_token_list(body: ProjectBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    rows = list(
        cms_api_keys_col()
        .find({"project_id": body.project_id}, {"_id": 0})
        .sort("created_at", -1)
    )
    return {"api_keys": [_public_api_key(r) for r in rows]}


@router.post("/website.api_token.revoke")
def api_token_revoke(body: ApiTokenGetBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    result = cms_api_keys_col().update_one(
        {"id": body.api_key_id, "project_id": body.project_id},
        {"$set": {"is_active": False, "updated_at": utc_now()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "API key not found")
    return {"revoked": True, "api_key_id": body.api_key_id}


def _require_content_api_key(request: Request) -> dict:
    header = request.headers.get("Authorization") or ""
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "Invalid API token")
    token = header.split(" ", 1)[1].strip()
    api_key = cms_api_keys_col().find_one(
        {"key_hash": _hash_api_token(token), "is_active": True}, {"_id": 0}
    )
    if not api_key:
        raise HTTPException(401, "Invalid API token")
    cms_api_keys_col().update_one(
        {"id": api_key["id"]}, {"$set": {"last_used_at": utc_now()}}
    )
    return api_key


@router.post("/website.content.collections.list")
def content_collections_list(request: Request):
    api_key = _require_content_api_key(request)
    if "content:read" not in (api_key.get("scopes") or []):
        raise HTTPException(403, "API token does not have content read access")
    rows = list(
        cms_collections_col()
        .find({"project_id": api_key["project_id"]}, {"_id": 0})
        .sort("name", 1)
    )
    allowed = set(api_key.get("allowed_collections") or [])
    out = []
    for item in rows:
        if allowed and item.get("id") not in allowed and item.get("slug") not in allowed:
            continue
        pub = _public_collection(item)
        out.append(
            {
                "id": pub["id"],
                "collection_id": pub["id"],
                "name": pub["name"],
                "slug": pub["slug"],
                "schema": pub.get("schema") or {},
            }
        )
    return {"collections": out}


@router.post("/website.content.entries.list")
def content_entries_list(request: Request, body: ContentEntriesListBody):
    api_key = _require_content_api_key(request)
    if "content:read" not in (api_key.get("scopes") or []):
        raise HTTPException(403, "API token does not have content read access")
    collection = cms_collections_col().find_one(
        {"project_id": api_key["project_id"], "slug": body.collection_slug},
        {"_id": 0},
    )
    if not collection:
        raise HTTPException(404, "Collection not found")
    limit = max(1, min(body.limit, 200))
    rows = list(
        cms_entries_col()
        .find(
            {
                "project_id": api_key["project_id"],
                "collection_id": collection["id"],
                "status": EntryStatus.PUBLISHED.value,
            },
            {"_id": 0},
        )
        .sort("published_at", -1)
        .limit(limit)
    )
    return {"entries": [_public_entry(r) for r in rows]}


@router.post("/website.content.media.get")
def content_media_get(request: Request, body: ContentMediaGetBody):
    api_key = _require_content_api_key(request)
    if "media:read" not in (api_key.get("scopes") or []):
        raise HTTPException(403, "API token does not have media read access")
    doc = cms_media_col().find_one(
        {"id": body.media_id, "project_id": api_key["project_id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Media not found")
    return _media_response(doc)
