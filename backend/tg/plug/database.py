"""Plug persistence — own collections, never touches users/clients/topics.

Collections:
  plug_creators._id     = username
  plug_topic_runs._id   = run uuid  → username
  plug_todos._id        = todo uuid → username

Falls back to backend/plug_db.json when MONGODB_URI is empty.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING

from backend.tg.config import settings
from backend.tg.database import _use_mongo, mongo_db

DB_FILE = Path(__file__).resolve().parent.parent.parent / "plug_db.json"

COL_CREATORS = "plug_creators"
COL_TOPIC_RUNS = "plug_topic_runs"
COL_TODOS = "plug_todos"

_indexes_ready = False

PROFILE_KEYS = (
    "name",
    "website",
    "instagram",
    "niche",
    "niche_details",
    "example_topics",
    "example_scripts",
    "reference_videos",
    "language",
    "instagram_connected",
    "todos_seeded",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready or not _use_mongo():
        return
    db = mongo_db()
    db[COL_TOPIC_RUNS].create_index([("username", ASCENDING), ("created_at", DESCENDING)])
    db[COL_TODOS].create_index([("username", ASCENDING), ("created_at", DESCENDING)])
    _indexes_ready = True


def _strip(doc: dict | None) -> dict:
    if not doc:
        return {}
    out = dict(doc)
    out.pop("_id", None)
    return out


def _load_file() -> dict:
    if not DB_FILE.exists():
        return {"creators": {}, "topic_runs": {}, "todos": {}}
    try:
        with open(DB_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"creators": {}, "topic_runs": {}, "todos": {}}
    data.setdefault("creators", {})
    data.setdefault("topic_runs", {})
    data.setdefault("todos", {})
    return data


def _save_file(data: dict) -> None:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def missing_search_profile_fields(creator: dict | None) -> list[str]:
    """Fields required for topic search. Search needs both niche and details."""
    missing: list[str] = []
    if not creator or not str(creator.get("niche") or "").strip():
        missing.append("niche")
    if not creator or not str(creator.get("niche_details") or "").strip():
        missing.append("details about niche")
    return missing


def search_profile_error(creator: dict | None) -> str | None:
    missing = missing_search_profile_fields(creator)
    if not missing:
        return None
    if missing == ["niche"]:
        return "Add niche in Profile before searching."
    if missing == ["details about niche"]:
        return "Add details about niche in Profile before searching."
    return "Add niche and details about niche in Profile before searching."


def _creator_public(doc: dict, *, username: str | None = None) -> dict:
    name = username or doc.get("username") or ""
    return {
        "username": name,
        "is_active": bool(doc.get("is_active", True)),
        "name": doc.get("name") or "",
        "website": doc.get("website") or "",
        "instagram": doc.get("instagram") or "",
        "niche": doc.get("niche") or "",
        "niche_details": doc.get("niche_details") or "",
        "example_topics": list(doc.get("example_topics") or []),
        "example_scripts": list(doc.get("example_scripts") or []),
        "reference_videos": list(doc.get("reference_videos") or []),
        "language": (doc.get("language") or "english").strip() or "english",
        "instagram_connected": bool(doc.get("instagram_connected")),
        "todos_seeded": bool(doc.get("todos_seeded")),
        "latest_run_id": doc.get("latest_run_id"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def fetch_creator(username: str, *, include_password: bool = False) -> dict | None:
    if not username:
        return None
    _ensure_indexes()
    if _use_mongo():
        doc = mongo_db()[COL_CREATORS].find_one({"_id": username})
        if not doc:
            return None
        out = _creator_public(doc, username=doc["_id"])
        if include_password:
            out["hashed_password"] = doc.get("hashed_password") or ""
        return out

    data = _load_file()
    doc = (data.get("creators") or {}).get(username)
    if not doc:
        return None
    out = _creator_public(doc, username=username)
    if include_password:
        out["hashed_password"] = doc.get("hashed_password") or ""
    return out


def insert_creator(creator: dict) -> dict:
    username = creator["username"]
    now = _now()
    doc = {
        "hashed_password": creator.get("hashed_password") or "",
        "is_active": bool(creator.get("is_active", True)),
        "name": creator.get("name") or "",
        "website": creator.get("website") or "",
        "instagram": creator.get("instagram") or "",
        "niche": creator.get("niche") or "",
        "niche_details": creator.get("niche_details") or "",
        "example_topics": list(creator.get("example_topics") or []),
        "example_scripts": list(creator.get("example_scripts") or []),
        "reference_videos": list(creator.get("reference_videos") or []),
        "language": (creator.get("language") or "english").strip() or "english",
        "instagram_connected": False,
        "todos_seeded": False,
        "latest_run_id": None,
        "created_at": now,
        "updated_at": now,
    }
    if _use_mongo():
        mongo_db()[COL_CREATORS].insert_one({"_id": username, **doc})
        created = _creator_public(doc, username=username)
        ensure_default_todos(username)
        return created

    data = _load_file()
    data["creators"][username] = {"username": username, **doc}
    _save_file(data)
    ensure_default_todos(username)
    return _creator_public(doc, username=username)


def update_creator(username: str, **fields: Any) -> dict | None:
    allowed = set(PROFILE_KEYS) | {"latest_run_id"}
    patch = {k: v for k, v in fields.items() if k in allowed}
    if "example_topics" in patch and not isinstance(patch["example_topics"], list):
        patch["example_topics"] = []
    if "example_scripts" in patch and not isinstance(patch["example_scripts"], list):
        patch["example_scripts"] = []
    if "reference_videos" in patch and not isinstance(patch["reference_videos"], list):
        patch["reference_videos"] = []
    if "language" in patch:
        patch["language"] = (str(patch["language"] or "english")).strip() or "english"
    if "instagram_connected" in patch:
        patch["instagram_connected"] = bool(patch["instagram_connected"])
    if "todos_seeded" in patch:
        patch["todos_seeded"] = bool(patch["todos_seeded"])
    patch["updated_at"] = _now()

    if _use_mongo():
        result = mongo_db()[COL_CREATORS].update_one({"_id": username}, {"$set": patch})
        if result.matched_count == 0:
            return None
        return fetch_creator(username)

    data = _load_file()
    doc = (data.get("creators") or {}).get(username)
    if not doc:
        return None
    doc.update(patch)
    _save_file(data)
    return _creator_public(doc, username=username)


def insert_topic_run(run: dict) -> dict:
    _ensure_indexes()
    run_id = run["id"]
    doc = {
        "username": run["username"],
        "language": run.get("language") or "english",
        "prompt": run.get("prompt") or "",
        "topics": list(run.get("topics") or []),
        "sources": list(run.get("sources") or []),
        "created_at": run.get("created_at") or _now(),
    }
    if _use_mongo():
        mongo_db()[COL_TOPIC_RUNS].insert_one({"_id": run_id, **doc})
        update_creator(run["username"], latest_run_id=run_id)
        return {"id": run_id, **doc}

    data = _load_file()
    data.setdefault("topic_runs", {})[run_id] = {"id": run_id, **doc}
    _save_file(data)
    update_creator(run["username"], latest_run_id=run_id)
    return {"id": run_id, **doc}


def fetch_topic_run(run_id: str, *, username: str | None = None) -> dict | None:
    if not run_id:
        return None
    _ensure_indexes()
    if _use_mongo():
        query: dict[str, Any] = {"_id": run_id}
        if username is not None:
            query["username"] = username
        doc = mongo_db()[COL_TOPIC_RUNS].find_one(query)
        if not doc:
            return None
        return {"id": doc["_id"], **_strip(doc)}

    data = _load_file()
    doc = (data.get("topic_runs") or {}).get(run_id)
    if not doc:
        return None
    if username is not None and doc.get("username") != username:
        return None
    return dict(doc)


def latest_topic_run(username: str) -> dict | None:
    creator = fetch_creator(username)
    if not creator:
        return None
    run_id = creator.get("latest_run_id")
    if run_id:
        run = fetch_topic_run(run_id, username=username)
        if run:
            return run

    _ensure_indexes()
    if _use_mongo():
        doc = mongo_db()[COL_TOPIC_RUNS].find_one(
            {"username": username},
            sort=[("created_at", DESCENDING)],
        )
        if not doc:
            return None
        return {"id": doc["_id"], **_strip(doc)}

    data = _load_file()
    runs = [
        r
        for r in (data.get("topic_runs") or {}).values()
        if r.get("username") == username
    ]
    if not runs:
        return None
    runs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return dict(runs[0])


def replace_topic_run(run: dict) -> dict:
    run_id = run["id"]
    username = run["username"]
    doc = {
        "username": username,
        "language": run.get("language") or "english",
        "prompt": run.get("prompt") or "",
        "topics": list(run.get("topics") or []),
        "sources": list(run.get("sources") or []),
        "created_at": run.get("created_at") or _now(),
        "updated_at": _now(),
    }
    if _use_mongo():
        mongo_db()[COL_TOPIC_RUNS].replace_one(
            {"_id": run_id, "username": username},
            {"_id": run_id, **doc},
            upsert=False,
        )
        return {"id": run_id, **doc}

    data = _load_file()
    existing = (data.get("topic_runs") or {}).get(run_id)
    if not existing or existing.get("username") != username:
        raise KeyError(run_id)
    data["topic_runs"][run_id] = {"id": run_id, **doc}
    _save_file(data)
    return {"id": run_id, **doc}


DEFAULT_TODOS = [
    "Verify AI clone",
    "Finalise niche and topics",
    "Feedback on initial scripts and topics",
    "Sample videos from internet for editing style",
    "Instagram account access - Convert to creator account",
    "(optional) Sample topics and scripts",
]


def _todo_public(doc: dict, todo_id: str) -> dict:
    return {
        "id": todo_id,
        "text": doc.get("text") or "",
        "done": bool(doc.get("done")),
        "sort": int(doc.get("sort") or 0),
        "created_at": doc.get("created_at"),
        "completed_at": doc.get("completed_at"),
    }


def _sort_todos(items: list[dict]) -> list[dict]:
    open_items = [t for t in items if not t.get("done")]
    done_items = [t for t in items if t.get("done")]
    open_items.sort(key=lambda t: (int(t.get("sort") or 0), t.get("created_at") or ""))
    done_items.sort(key=lambda t: (int(t.get("sort") or 0), t.get("completed_at") or t.get("created_at") or ""))
    return open_items + done_items


def _load_todos(username: str) -> list[dict]:
    _ensure_indexes()
    if _use_mongo():
        rows = list(mongo_db()[COL_TODOS].find({"username": username}))
        return [_todo_public(doc, doc["_id"]) for doc in rows]

    data = _load_file()
    return [
        _todo_public(doc, todo_id)
        for todo_id, doc in (data.get("todos") or {}).items()
        if doc.get("username") == username
    ]


def ensure_default_todos(username: str) -> None:
    creator = fetch_creator(username)
    if not creator or creator.get("todos_seeded"):
        return
    if not _load_todos(username):
        for index, text in enumerate(DEFAULT_TODOS):
            insert_todo(username, text, sort=index)
    update_creator(username, todos_seeded=True)


def list_todos(username: str) -> list[dict]:
    ensure_default_todos(username)
    return _sort_todos(_load_todos(username))


def insert_todo(username: str, text: str, *, sort: int | None = None) -> dict:
    _ensure_indexes()
    todo_id = str(uuid4())
    now = _now()
    if sort is None:
        open_sorts = [int(t.get("sort") or 0) for t in _load_todos(username) if not t.get("done")]
        sort = (max(open_sorts) + 1) if open_sorts else 0
    doc = {
        "username": username,
        "text": text,
        "done": False,
        "sort": int(sort),
        "created_at": now,
        "completed_at": None,
    }
    if _use_mongo():
        mongo_db()[COL_TODOS].insert_one({"_id": todo_id, **doc})
        return _todo_public(doc, todo_id)

    data = _load_file()
    data.setdefault("todos", {})[todo_id] = {"id": todo_id, **doc}
    _save_file(data)
    return _todo_public(doc, todo_id)


def update_todo(
    username: str,
    todo_id: str,
    *,
    text: str | None = None,
    done: bool | None = None,
    sort: int | None = None,
) -> dict | None:
    _ensure_indexes()
    patch: dict[str, Any] = {}
    if text is not None:
        patch["text"] = text
    if done is not None:
        current = fetch_todo(username, todo_id)
        was_done = bool(current.get("done")) if current else False
        patch["done"] = bool(done)
        if was_done != bool(done):
            patch["completed_at"] = _now() if done else None
        if sort is None:
            siblings = [
                t
                for t in list_todos(username)
                if bool(t.get("done")) == bool(done) and t.get("id") != todo_id
            ]
            sibling_sorts = [int(t.get("sort") or 0) for t in siblings]
            patch["sort"] = (max(sibling_sorts) + 1) if sibling_sorts else 0
    if sort is not None:
        patch["sort"] = int(sort)
    if not patch:
        existing = fetch_todo(username, todo_id)
        return existing

    if _use_mongo():
        result = mongo_db()[COL_TODOS].update_one(
            {"_id": todo_id, "username": username},
            {"$set": patch},
        )
        if result.matched_count == 0:
            return None
        return fetch_todo(username, todo_id)

    data = _load_file()
    doc = (data.get("todos") or {}).get(todo_id)
    if not doc or doc.get("username") != username:
        return None
    doc.update(patch)
    _save_file(data)
    return _todo_public(doc, todo_id)


def fetch_todo(username: str, todo_id: str) -> dict | None:
    _ensure_indexes()
    if _use_mongo():
        doc = mongo_db()[COL_TODOS].find_one({"_id": todo_id, "username": username})
        if not doc:
            return None
        return _todo_public(doc, doc["_id"])

    data = _load_file()
    doc = (data.get("todos") or {}).get(todo_id)
    if not doc or doc.get("username") != username:
        return None
    return _todo_public(doc, todo_id)


def delete_todo(username: str, todo_id: str) -> bool:
    _ensure_indexes()
    if _use_mongo():
        result = mongo_db()[COL_TODOS].delete_one({"_id": todo_id, "username": username})
        return result.deleted_count > 0

    data = _load_file()
    doc = (data.get("todos") or {}).get(todo_id)
    if not doc or doc.get("username") != username:
        return False
    del data["todos"][todo_id]
    _save_file(data)
    return True


def reorder_todos(username: str, open_ids: list[str], done_ids: list[str]) -> list[dict]:
    existing = {t["id"]: t for t in list_todos(username)}
    seen: set[str] = set()

    def apply(ids: list[str], done: bool) -> None:
        position = 0
        for todo_id in ids:
            if todo_id not in existing or todo_id in seen:
                continue
            seen.add(todo_id)
            update_todo(username, todo_id, done=done, sort=position)
            position += 1
        leftovers = [
            t for t in existing.values()
            if t["id"] not in seen and bool(t.get("done")) == done
        ]
        leftovers.sort(key=lambda t: int(t.get("sort") or 0))
        for todo in leftovers:
            seen.add(todo["id"])
            update_todo(username, todo["id"], done=done, sort=position)
            position += 1

    apply(open_ids, False)
    apply(done_ids, True)
    return list_todos(username)
