"""One-shot: rename productions → yt_metadata; add plan_items.origin + yt_metadata_id.

- Renames Mongo collection `productions` → `yt_metadata` (or copies if rename blocked)
- plan_items.production_id → yt_metadata_id
- plan_items.origin = generated|manual (existing scripted items → generated)

Safe to re-run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "backend" / ".env", override=True)

from backend.main.db import get_db, plan_items_col, yt_metadata_col  # noqa: E402
from backend.tg.database import (  # noqa: E402
    PLAN_ITEM_ORIGIN_GENERATED,
    PLAN_ITEM_ORIGIN_MANUAL,
    _iso,
)
from backend.videos.models import COL_YT_METADATA  # noqa: E402


OLD_COL = "productions"


def _rename_collection(*, dry_run: bool) -> dict:
    db = get_db()
    names = set(db.list_collection_names())
    has_old = OLD_COL in names
    has_new = COL_YT_METADATA in names
    if has_new and not has_old:
        return {"action": "already_renamed", "count": yt_metadata_col().estimated_document_count()}
    if not has_old:
        return {"action": "missing_both" if not has_new else "noop", "count": 0}
    count = db[OLD_COL].estimated_document_count()
    if dry_run:
        return {"action": "would_rename", "count": count}
    if has_new:
        # Merge old into new then drop old
        docs = list(db[OLD_COL].find({}, {"_id": 0}))
        if docs:
            for doc in docs:
                db[COL_YT_METADATA].update_one(
                    {"id": doc.get("id")},
                    {"$set": doc},
                    upsert=True,
                )
        db[OLD_COL].drop()
        return {"action": "merged_and_dropped", "count": len(docs)}
    db[OLD_COL].rename(COL_YT_METADATA)
    return {"action": "renamed", "count": count}


def _migrate_plan_items(*, dry_run: bool) -> dict:
    scanned = 0
    origin_set = 0
    id_renamed = 0
    for doc in plan_items_col().find(
        {},
        {"_id": 0, "id": 1, "script": 1, "origin": 1, "production_id": 1, "yt_metadata_id": 1},
    ):
        scanned += 1
        patch: dict = {}
        unset: dict = {}
        if doc.get("origin") not in (PLAN_ITEM_ORIGIN_GENERATED, PLAN_ITEM_ORIGIN_MANUAL):
            # Existing rows default to AI-generated (historical scripts).
            patch["origin"] = PLAN_ITEM_ORIGIN_GENERATED
            origin_set += 1
        if doc.get("production_id") and not doc.get("yt_metadata_id"):
            patch["yt_metadata_id"] = doc.get("production_id")
            unset["production_id"] = ""
            id_renamed += 1
        elif "production_id" in doc:
            unset["production_id"] = ""
            id_renamed += 1
        if not patch and not unset:
            continue
        if dry_run:
            continue
        update: dict = {"$set": {**patch, "updated_at": _iso()}}
        if unset:
            update["$unset"] = unset
        plan_items_col().update_one({"id": doc["id"]}, update)
    return {"scanned": scanned, "origin_set": origin_set, "id_renamed": id_renamed, "dry_run": dry_run}


def migrate(*, dry_run: bool = False) -> dict:
    rename = _rename_collection(dry_run=dry_run)
    plan = _migrate_plan_items(dry_run=dry_run)
    return {"collection": rename, "plan_items": plan}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(migrate(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
