"""CLI: python -m backend.migrate.run [--dry-run] [--wipe]

Read-only against TG. Writes only to Beacon.
"""

from __future__ import annotations

import argparse
import json
import sys

from .build import build_bundle
from .config import (
    BEACON_DB_NAME,
    BEACON_SUPERUSER_EMAIL,
    TG_MONGODB_DB_NAME,
    require_source_uri,
)
from .fixture import build_fixture_bundle
from .load import grant_superuser_access, upsert_superuser, wipe_product_data, write_bundle
from .source import close_source, ping_source
from .verify import verify_import


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate TG Mongo → Beacon (read-only source)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read TG + build bundle only; do not write Beacon",
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Clear Beacon product collections (+ users) before import",
    )
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="Load synthetic TG-shaped fixture via same transforms (for empty source DBs)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable summary",
    )
    args = parser.parse_args(argv)

    source_info = None
    if args.fixture:
        bundle, stats = build_fixture_bundle()
        print("Using synthetic fixture bundle")
    else:
        require_source_uri()
        source_info = ping_source()
        print(
            f"Source OK db={TG_MONGODB_DB_NAME} "
            f"clients={source_info['counts'].get('clients', 0)}"
        )
        bundle, stats = build_bundle()

    print("Bundle counts:", json.dumps(stats["bundle_counts"], indent=2))
    print(f"Embedded topics: {stats['topic_embedded']}")
    if stats["errors"]:
        print("Transform errors:")
        for err in stats["errors"][:20]:
            print(" -", err)

    if args.dry_run:
        summary = {
            "mode": "dry-run",
            "fixture": bool(args.fixture),
            "source": source_info,
            "stats": stats,
            "destination_db": BEACON_DB_NAME,
            "superuser_email": BEACON_SUPERUSER_EMAIL,
        }
        if args.json:
            print(json.dumps(summary, default=str, indent=2))
        else:
            print("Dry-run complete — no Beacon writes.")
        close_source()
        return 0

    if args.wipe:
        deleted = wipe_product_data(keep_users=False)
        print("Wiped Beacon:", deleted)

    superuser = upsert_superuser(wipe=True)
    print(f"Superuser: {superuser.get('email')} id={superuser.get('id')}")

    written = write_bundle(bundle)
    print("Wrote:", written)

    access_n = grant_superuser_access(
        superuser["id"], [p["id"] for p in bundle["projects"]]
    )
    print(f"Access grants: {access_n}")

    result = verify_import(stats)
    if args.json:
        print(json.dumps({"written": written, "verify": result}, default=str, indent=2))
    else:
        print("Verify:", "OK" if result["ok"] else "FAILED")
        for m in result["mismatches"]:
            print(" !", m)
        if result.get("sample_project"):
            print("Sample:", result["sample_project"])
        print(
            f"Login: email={BEACON_SUPERUSER_EMAIL} "
            f"(password from BEACON_SUPERUSER_PASSWORD)"
        )

    if not args.fixture:
        source_after = ping_source()["counts"]
        if source_after != stats["source_counts"]:
            print("WARNING: source counts changed during migration!", file=sys.stderr)
            close_source()
            return 2

    close_source()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
