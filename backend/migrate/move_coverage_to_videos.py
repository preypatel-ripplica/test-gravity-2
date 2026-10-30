"""One-shot: move projects.content_topic_coverage AI map onto videos docs.

- Writes topic_id / out_of_keyword / video_type / topic_mapped_at onto matching videos
- Ensures content_plan.keyword_analysis / mapped_at / coverage exist (copy from coverage if missing)
- $unsets projects.content_topic_coverage

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

from backend.main.db import projects_col, videos_col  # noqa: E402
from backend.tg.database import VIDEO_TOPIC_MAP_FIELDS, _iso  # noqa: E402
from backend.tg.services.content_formats import coverage_summary  # noqa: E402
from pymongo import UpdateOne  # noqa: E402


def migrate(*, dry_run: bool = False) -> dict:
    scanned = 0
    projects_touched = 0
    videos_patched = 0
    plans_backfilled = 0

    cursor = projects_col().find(
        {},
        {"_id": 0, "id": 1, "name": 1, "content_plan": 1, "content_topic_coverage": 1},
    )
    for doc in cursor:
        scanned += 1
        client_id = doc.get("id")
        if not client_id:
            continue
        coverage = doc.get("content_topic_coverage")
        suggestions = doc.get("content_plan") if isinstance(doc.get("content_plan"), dict) else {}
        mapped_videos = (coverage or {}).get("videos") if isinstance(coverage, dict) else None
        has_coverage = isinstance(coverage, dict) and bool(coverage)
        # Only backfill plan fields when we actually had a coverage blob to migrate from.
        needs_analysis = (
            has_coverage
            and not (suggestions.get("keyword_analysis") or [])
            and bool((coverage or {}).get("keyword_analysis"))
        )
        needs_mapped_at = has_coverage and not suggestions.get("mapped_at") and bool(
            (coverage or {}).get("mapped_at")
        )
        needs_summary = has_coverage and not suggestions.get("coverage")

        if not has_coverage and not (needs_analysis or needs_mapped_at or needs_summary):
            continue

        projects_touched += 1
        ops: list = []
        mapped_at = (coverage or {}).get("mapped_at") if isinstance(coverage, dict) else None
        stamp = mapped_at or _iso()

        if isinstance(mapped_videos, dict):
            for vid, row in mapped_videos.items():
                if not vid or not isinstance(row, dict):
                    continue
                patch = {
                    "topic_id": row.get("topic_id"),
                    "out_of_keyword": bool(row.get("out_of_keyword")),
                    "video_type": row.get("video_type"),
                    "topic_mapped_at": stamp,
                    "updated_at": _iso(),
                }
                ops.append(
                    UpdateOne(
                        {"id": vid, "project_id": client_id},
                        {"$set": patch},
                    )
                )

        # Build lean video list for coverage summary if needed
        video_rows_for_summary: list[dict] = []
        if isinstance(mapped_videos, dict):
            for vid, row in mapped_videos.items():
                if not isinstance(row, dict):
                    continue
                video_rows_for_summary.append(
                    {
                        "id": vid,
                        "topic_id": row.get("topic_id"),
                        "out_of_keyword": row.get("out_of_keyword"),
                        "is_short": row.get("is_short"),
                    }
                )

        new_plan = copy.deepcopy(suggestions) if suggestions else {}
        plan_changed = False
        if needs_analysis:
            new_plan["keyword_analysis"] = coverage.get("keyword_analysis")
            plan_changed = True
        if needs_mapped_at and mapped_at:
            new_plan["mapped_at"] = mapped_at
            plan_changed = True
        if needs_summary:
            new_plan["coverage"] = coverage_summary(video_rows_for_summary)
            plan_changed = True

        if dry_run:
            print(
                f"[dry-run] {doc.get('name')} ({client_id}): "
                f"video_ops={len(ops)} plan_backfill={plan_changed} unset_coverage={has_coverage}"
            )
            videos_patched += len(ops)
            if plan_changed:
                plans_backfilled += 1
            continue

        if ops:
            result = videos_col().bulk_write(ops, ordered=False)
            videos_patched += result.modified_count + result.upserted_count
            # matched but unchanged still "patched intent"
            if result.modified_count == 0 and result.matched_count:
                videos_patched += result.matched_count

        update_doc: dict = {"$unset": {"content_topic_coverage": ""}, "$set": {"updated_at": _iso()}}
        if plan_changed:
            update_doc["$set"]["content_plan"] = new_plan
            plans_backfilled += 1
        projects_col().update_one({"id": client_id}, update_doc)
        print(
            f"[ok] {doc.get('name')} ({client_id}): "
            f"videos={len(ops)} plan_backfill={plan_changed}"
        )

    return {
        "scanned": scanned,
        "projects_touched": projects_touched,
        "videos_patched": videos_patched,
        "plans_backfilled": plans_backfilled,
        "map_fields": list(VIDEO_TOPIC_MAP_FIELDS),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(migrate(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
