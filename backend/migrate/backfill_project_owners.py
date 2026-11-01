"""Backfill projects.owner_user_id from the earliest access grant.

For each project missing owner_user_id, assign the user with the oldest
access row. Safe to re-run.
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

from backend.main.db import access_col, projects_col  # noqa: E402
from backend.main.models import utc_now  # noqa: E402


def backfill(*, dry_run: bool) -> dict:
    scanned = 0
    already = 0
    updated = 0
    skipped = 0
    for project in projects_col().find(
        {},
        {"_id": 0, "id": 1, "owner_user_id": 1, "name": 1},
    ):
        scanned += 1
        if project.get("owner_user_id"):
            already += 1
            continue
        grant = access_col().find_one(
            {"project_id": project["id"]},
            {"_id": 0, "user_id": 1, "created_at": 1},
            sort=[("created_at", 1)],
        )
        if not grant or not grant.get("user_id"):
            skipped += 1
            continue
        if not dry_run:
            projects_col().update_one(
                {"id": project["id"]},
                {
                    "$set": {
                        "owner_user_id": grant["user_id"],
                        "updated_at": utc_now(),
                    }
                },
            )
        updated += 1
    return {
        "scanned": scanned,
        "already_owned": already,
        "updated": updated,
        "skipped_no_grants": skipped,
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing",
    )
    args = parser.parse_args()
    result = backfill(dry_run=args.dry_run)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
