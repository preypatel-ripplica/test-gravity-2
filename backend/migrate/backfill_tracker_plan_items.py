"""Backfill plan_items for weekly-tracker scripts and link cards to those ids.

Tracker cards often keep script_text (and sometimes a content_plan_item_id) after
plan_items were deleted or never created. Metadata regenerate looks up plan_items
by id, so those cards break until we restore the documents.

Safe to re-run. Historical rows are written with is_latest=False so they do not
replace the current content-plan set.
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

from backend.tg.database import backfill_plan_items_from_weekly_trackers  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Limit backfill to one project/client id",
    )
    args = parser.parse_args()
    result = backfill_plan_items_from_weekly_trackers(
        project_id=args.project_id,
        dry_run=args.dry_run,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
