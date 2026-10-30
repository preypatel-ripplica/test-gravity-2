"""Build CMS → Beacon website migration bundle."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.main.db import projects_col
from backend.main.models import Access, Domain

from . import cms_source as S
from . import cms_transform as T


def build_cms_bundle() -> tuple[dict[str, Any], dict[str, Any]]:
    users = {u["user_id"]: u for u in S.iter_collection(S.COL_USERS) if u.get("user_id")}
    collections = list(S.iter_collection(S.COL_COLLECTIONS))
    entries = list(S.iter_collection(S.COL_ENTRIES))
    media = list(S.iter_collection(S.COL_MEDIA))
    api_keys = list(S.iter_collection(S.COL_API_KEYS))

    beacon_projects = list(projects_col().find({}, {"_id": 0, "id": 1, "name": 1}))

    # Users that own any CMS content
    content_user_ids = set()
    for row in collections + entries + media + api_keys:
        if row.get("user_id"):
            content_user_ids.add(row["user_id"])

    user_to_project: dict[str, str] = {}
    projects_to_create: list[dict[str, Any]] = []
    mapping_notes: list[str] = []

    for uid in sorted(content_user_ids):
        user = users.get(uid) or {"user_id": uid, "username": uid}
        matched = T.match_project_id(user, beacon_projects)
        if matched:
            user_to_project[uid] = matched
            mapping_notes.append(
                f"map {user.get('username') or uid} → existing project {matched} "
                f"({next((p['name'] for p in beacon_projects if p['id']==matched), '?')})"
            )
        else:
            project = T.new_project_for_cms_user(user)
            projects_to_create.append(project)
            user_to_project[uid] = project["id"]
            beacon_projects.append({"id": project["id"], "name": project["name"]})
            mapping_notes.append(
                f"create project {project['id']} name={project['name']!r} "
                f"for CMS user {user.get('username') or uid}"
            )

    out_collections = []
    out_entries = []
    out_media = []
    out_keys = []
    errors: list[str] = []

    for doc in collections:
        uid = doc.get("user_id")
        pid = user_to_project.get(uid)
        if not pid:
            errors.append(f"collection {doc.get('collection_id')} missing project map")
            continue
        try:
            out_collections.append(T.transform_collection(doc, project_id=pid))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"collection {doc.get('collection_id')}: {exc}")

    for doc in entries:
        uid = doc.get("user_id")
        pid = user_to_project.get(uid)
        if not pid:
            errors.append(f"entry {doc.get('entry_id')} missing project map")
            continue
        try:
            out_entries.append(T.transform_entry(doc, project_id=pid))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"entry {doc.get('entry_id')}: {exc}")

    for doc in media:
        uid = doc.get("user_id")
        pid = user_to_project.get(uid)
        if not pid:
            errors.append(f"media {doc.get('media_id')} missing project map")
            continue
        try:
            out_media.append(T.transform_media(doc, project_id=pid))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"media {doc.get('media_id')}: {exc}")

    for doc in api_keys:
        uid = doc.get("user_id")
        pid = user_to_project.get(uid)
        if not pid or not doc.get("key_hash"):
            continue
        try:
            out_keys.append(T.transform_api_key(doc, project_id=pid))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"api_key {doc.get('api_key_id')}: {exc}")

    # Website domain grants for every project we touch
    project_ids = sorted(set(user_to_project.values()))
    access_docs = []
    # filled later with superuser id in load

    by_project = defaultdict(lambda: {"collections": 0, "entries": 0, "media": 0})
    for c in out_collections:
        by_project[c["project_id"]]["collections"] += 1
    for e in out_entries:
        by_project[e["project_id"]]["entries"] += 1
    for m in out_media:
        by_project[m["project_id"]]["media"] += 1

    bundle = {
        "projects": projects_to_create,
        "cms_collections": out_collections,
        "cms_entries": out_entries,
        "cms_media": out_media,
        "cms_api_keys": out_keys,
        "access": access_docs,
        "user_to_project": user_to_project,
        "project_ids": project_ids,
    }
    stats = {
        "source_counts": {
            "users": len(users),
            "collections": len(collections),
            "entries": len(entries),
            "media": len(media),
            "api_keys": len(api_keys),
            "content_users": len(content_user_ids),
        },
        "bundle_counts": {
            "projects_create": len(projects_to_create),
            "cms_collections": len(out_collections),
            "cms_entries": len(out_entries),
            "cms_media": len(out_media),
            "cms_api_keys": len(out_keys),
        },
        "mapping": mapping_notes,
        "by_project": dict(by_project),
        "errors": errors,
    }
    return bundle, stats


def make_website_access(user_id: str, project_ids: list[str]) -> list[dict[str, Any]]:
    return [
        Access(user_id=user_id, project_id=pid, domain=Domain.WEBSITE).model_dump(
            mode="json"
        )
        for pid in project_ids
    ]
