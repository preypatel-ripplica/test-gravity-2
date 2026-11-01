"""Migration env: TG source (read-only) + Beacon dest + superuser."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from backend.main.config import MONGODB_DB_NAME, MONGODB_URI

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(BACKEND_ROOT / ".env")

TG_MONGODB_URI = (os.getenv("TG_MONGODB_URI") or "").strip()
TG_MONGODB_DB_NAME = (os.getenv("TG_MONGODB_DB_NAME") or "youtube_analytics").strip()

BEACON_URI = MONGODB_URI
BEACON_DB_NAME = MONGODB_DB_NAME

BEACON_SUPERUSER_EMAIL = (
    os.getenv("BEACON_SUPERUSER_EMAIL") or "admin@plugai.com"
).strip().lower()
BEACON_SUPERUSER_PASSWORD = (os.getenv("BEACON_SUPERUSER_PASSWORD") or "").strip()
BEACON_SUPERUSER_NAME = (os.getenv("BEACON_SUPERUSER_NAME") or "Beacon Admin").strip()


def require_source_uri() -> str:
    if not TG_MONGODB_URI:
        raise SystemExit(
            "TG_MONGODB_URI is not set. Add it to beacon/backend/.env "
            "(read-only source). Refusing to run."
        )
    if not BEACON_URI:
        raise SystemExit("MONGODB_URI (Beacon destination) is not set.")
    return TG_MONGODB_URI


def require_superuser_password(*, wipe: bool) -> str:
    if wipe and not BEACON_SUPERUSER_PASSWORD:
        raise SystemExit(
            "BEACON_SUPERUSER_PASSWORD is required when importing "
            "(set in beacon/backend/.env)."
        )
    return BEACON_SUPERUSER_PASSWORD
