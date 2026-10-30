"""CLI: python -m backend.migrate.cms_run [--dry-run] [--wipe-cms]

Read-only against CMS_NEW Mongo. Writes website CMS collections on Beacon only.
"""

from __future__ import annotations

import argparse
import json
import sys

from .cms_build import build_cms_bundle
from .cms_config import (
    BEACON_DB_NAME,
    BEACON_SUPERUSER_EMAIL,
    CMS_MONGO_DB_NAME,
    require_cms_source,
)
from .cms_load import wipe_cms_only, write_cms_bundle
from .cms_source import close_source, ping_source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate CMS_NEW Mongo → Beacon website CMS (read-only source)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read CMS + build bundle only; do not write Beacon",
    )
    parser.add_argument(
        "--wipe-cms",
        action="store_true",
        help="Clear Beacon cms_collections/entries/media/api_keys before import "
        "(does NOT wipe videos/social)",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable summary")
    args = parser.parse_args(argv)

    require_cms_source()
    source_info = ping_source()
    print(
        f"CMS source OK db={CMS_MONGO_DB_NAME} "
        f"collections={source_info['counts'].get('collections', 0)} "
        f"entries={source_info['counts'].get('entries', 0)} "
        f"media={source_info['counts'].get('media', 0)}"
    )

    bundle, stats = build_cms_bundle()
    print("Bundle counts:", json.dumps(stats["bundle_counts"], indent=2))
    print("User → project mapping:")
    for note in stats["mapping"]:
        print(" -", note)
    if stats["errors"]:
        print("Transform errors:")
        for err in stats["errors"][:30]:
            print(" -", err)

    if args.dry_run:
        summary = {
            "mode": "dry-run",
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

    wiped = None
    if args.wipe_cms:
        wiped = wipe_cms_only()
        print("Wiped CMS collections:", wiped)

    written = write_cms_bundle(bundle)
    print("Wrote:", json.dumps(written, indent=2))
    close_source()

    summary = {
        "mode": "import",
        "source": source_info,
        "stats": stats,
        "wiped": wiped,
        "written": written,
        "destination_db": BEACON_DB_NAME,
    }
    if args.json:
        print(json.dumps(summary, default=str, indent=2))
    print("CMS → Beacon website import complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
