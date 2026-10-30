"""Map CMS_NEW docs → Beacon website CMS docs (project_id scoped)."""

from __future__ import annotations

import re
from typing import Any, Optional

from backend.main.models import Project, utc_now
from backend.website.models import CmsApiKey, CmsCollection, CmsEntry, CmsMedia, EntryStatus
from backend.website.schema_presets import normalize_schema_value


def _norm_name(value: str) -> str:
    text = (value or "").lower()
    text = re.sub(r"^dr\.?\s+", "", text)
    text = text.replace("-", " ").replace("_", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # drop generic suffixes
    for junk in ("website", "main website", "untitled cms project", "cms connect", "boiler website"):
        if text.endswith(junk):
            text = text[: -len(junk)].strip()
    return text


def cms_project_label(user: dict[str, Any]) -> str:
    details = user.get("project_details") if isinstance(user.get("project_details"), dict) else {}
    name = (details.get("name") or "").strip()
    if name and name.lower() not in {"untitled cms project", "test project"}:
        return name.replace("-", " ").replace("_", " ").strip()
    return (user.get("username") or user.get("email") or "CMS Project").strip()


# Hand aliases: CMS username/email → Beacon project name fragment
_ALIASES: list[tuple[str, str]] = [
    ("manjinder", "manjinder sandhu"),
    ("drakdhar", "ak dhar"),
    ("ayush", "ak dhar"),
    ("tripti", "tripti"),
    ("anilraheja", "anil raheja"),
    ("prey_creator", "anil raheja"),
    ("vikram", "vikram"),
    ("parveen", "parveen"),
]


def match_project_id(
    user: dict[str, Any],
    beacon_projects: list[dict[str, Any]],
) -> Optional[str]:
    """Best-effort match CMS user → existing Beacon project by name."""
    label = _norm_name(cms_project_label(user))
    username = _norm_name(user.get("username") or "")
    email = (user.get("email") or "").lower()
    email_local = _norm_name(email.split("@")[0])
    hay = f"{label} {username} {email_local}"

    best_id = None
    best_score = 0
    for project in beacon_projects:
        raw_name = project.get("name") or ""
        pname = _norm_name(raw_name)
        if not pname:
            continue
        # Prefer human project names over raw URLs
        url_penalty = 25 if "http" in raw_name.lower() or "vercel" in pname else 0
        score = 0
        if label and (label == pname or label in pname or pname in label):
            score = max(score, 100 if label == pname else 80)
        if username and (username == pname or username in pname or pname in username):
            score = max(score, 70)
        if email_local and len(email_local) > 3 and (
            email_local in pname or pname in email_local
        ):
            score = max(score, 60)
        for needle, target in _ALIASES:
            if needle in hay and target in pname:
                score = max(score, 95)
        lt, pt = set(label.split()), set(pname.split())
        if lt and pt:
            overlap = len(lt & pt) / max(len(lt | pt), 1)
            if overlap >= 0.5:
                score = max(score, int(50 + overlap * 40))
        score = max(0, score - url_penalty)
        if score > best_score:
            best_score = score
            best_id = project.get("id")
    return best_id if best_score >= 60 else None


def transform_collection(doc: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    schema = doc.get("schema") or doc.get("entry_schema") or {}
    if not isinstance(schema, dict):
        schema = {}
    model = CmsCollection(
        id=str(doc.get("collection_id") or doc.get("id")),
        project_id=project_id,
        name=str(doc.get("name") or "Untitled"),
        slug=str(doc.get("slug") or "collection"),
        schema_=normalize_schema_value(schema) if schema else schema,
        ai_context=doc.get("ai_context") if isinstance(doc.get("ai_context"), dict) else {},
        created_at=doc.get("created_at") or utc_now(),
        updated_at=doc.get("updated_at") or utc_now(),
    )
    out = model.model_dump(mode="json", by_alias=True)
    out["entry_schema"] = out.get("schema") or {}
    out["cms_user_id"] = doc.get("user_id")
    return out


def transform_entry(doc: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    payload = doc.get("entry") if isinstance(doc.get("entry"), dict) else {}
    status_raw = (doc.get("status") or "draft").lower()
    try:
        status = EntryStatus(status_raw)
    except ValueError:
        status = EntryStatus.DRAFT
    model = CmsEntry(
        id=str(doc.get("entry_id") or doc.get("id")),
        project_id=project_id,
        collection_id=str(doc.get("collection_id")),
        entry=payload,
        status=status,
        created_at=doc.get("created_at") or utc_now(),
        updated_at=doc.get("updated_at") or utc_now(),
        published_at=doc.get("published_at"),
    )
    out = model.model_dump(mode="json")
    out["data"] = out.get("entry") or {}
    out["cms_user_id"] = doc.get("user_id")
    return out


def transform_media(doc: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    model = CmsMedia(
        id=str(doc.get("media_id") or doc.get("id")),
        project_id=project_id,
        url=str(doc.get("url") or ""),
        filename=str(doc.get("filename") or ""),
        alt_text=str(doc.get("alt_text") or ""),
        content_type=doc.get("content_type"),
        size_bytes=doc.get("size_bytes"),
        metadata=doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {},
        created_at=doc.get("created_at") or utc_now(),
        updated_at=doc.get("updated_at") or utc_now(),
    )
    out = model.model_dump(mode="json")
    out["cms_user_id"] = doc.get("user_id")
    return out


def transform_api_key(doc: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    model = CmsApiKey(
        id=str(doc.get("api_key_id") or doc.get("id")),
        project_id=project_id,
        name=str(doc.get("name") or "CMS token"),
        key_prefix=str(doc.get("key_prefix") or "")[:32],
        key_hash=str(doc.get("key_hash") or ""),
        scopes=list(doc.get("scopes") or ["content:read", "media:read"]),
        allowed_collections=list(doc.get("allowed_collections") or []),
        allowed_origins=list(doc.get("allowed_origins") or []),
        is_active=bool(doc.get("is_active", True)),
        created_at=doc.get("created_at") or utc_now(),
        updated_at=doc.get("updated_at") or utc_now(),
        last_used_at=doc.get("last_used_at"),
        expires_at=doc.get("expires_at"),
    )
    out = model.model_dump(mode="json")
    out["cms_user_id"] = doc.get("user_id")
    return out


def new_project_for_cms_user(user: dict[str, Any]) -> dict[str, Any]:
    label = cms_project_label(user)
    return Project(name=label).model_dump(mode="json")
