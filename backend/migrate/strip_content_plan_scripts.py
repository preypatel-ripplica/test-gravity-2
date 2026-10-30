"""One-shot: move scripts (+ script_* attrs) from projects.content_plan into plan_items.

projects.content_plan.items keep planning metadata + id only.
Safe to re-run.
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "backend" / ".env", override=True)

from backend.main.db import projects_col  # noqa: E402
from backend.tg.database import (  # noqa: E402
    CONTENT_PLAN_SCRIPT_FIELDS,
    _sync_plan_items,
    strip_script_fields_from_suggestions,
    _iso,
)


def _item_has_script_fields(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("script") or "").strip():
        return True
    return any(k in item for k in CONTENT_PLAN_SCRIPT_FIELDS if k != "script")


def migrate(*, dry_run: bool = False) -> dict:
    scanned = 0
    touched = 0
    items_moved = 0
    for doc in projects_col().find({}, {"_id": 0, "id": 1, "name": 1, "content_plan": 1}):
        scanned += 1
        suggestions = doc.get("content_plan")
        if not isinstance(suggestions, dict):
            continue
        items = [i for i in (suggestions.get("items") or []) if isinstance(i, dict)]
        if not any(_item_has_script_fields(i) for i in items):
            continue
        touched += 1
        items_moved += sum(1 for i in items if _item_has_script_fields(i))
        if dry_run:
            print(
                f"[dry-run] {doc.get('name')} ({doc.get('id')}): "
                f"{sum(1 for i in items if _item_has_script_fields(i))} items with script fields"
            )
            continue
        payload = copy.deepcopy(suggestions)
        _sync_plan_items(doc["id"], payload)
        strip_script_fields_from_suggestions(payload)
        projects_col().update_one(
            {"id": doc["id"]},
            {"$set": {"content_plan": payload, "updated_at": _iso()}},
        )
        print(f"[ok] {doc.get('name')} ({doc.get('id')})")
    return {"scanned": scanned, "touched": touched, "items_moved": items_moved}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = migrate(dry_run=args.dry_run)
    print(result)


if __name__ == "__main__":
    main()
