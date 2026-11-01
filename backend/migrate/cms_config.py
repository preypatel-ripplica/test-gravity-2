"""CMS_NEW → Beacon website migration env (source read-only)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

from backend.main.config import MONGODB_DB_NAME, MONGODB_URI

ROOT = Path(__file__).resolve().parents[2]  # beacon/
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent

load_dotenv(ROOT / ".env")
load_dotenv(BACKEND_ROOT / ".env")

_CMS_ENV_PATH = REPO_ROOT / "CMS_NEW copy" / ".env"
_cms_file = dotenv_values(_CMS_ENV_PATH) if _CMS_ENV_PATH.exists() else {}

# Explicit CMS_* in Beacon .env wins; else values from CMS_NEW copy/.env
CMS_MONGO_URL = (
    (os.getenv("CMS_MONGO_URL") or "").strip()
    or str(_cms_file.get("MONGO_URL") or "").strip()
)
CMS_MONGO_DB_NAME = (
    (os.getenv("CMS_MONGO_DB_NAME") or "").strip()
    or str(_cms_file.get("MONGO_DB_NAME") or "").strip()
    or "cms_platform"
)

BEACON_URI = MONGODB_URI
BEACON_DB_NAME = MONGODB_DB_NAME

BEACON_SUPERUSER_EMAIL = (
    os.getenv("BEACON_SUPERUSER_EMAIL") or "admin@plugai.com"
).strip().lower()


def require_cms_source() -> str:
    if not CMS_MONGO_URL:
        raise SystemExit(
            "CMS Mongo URI missing. Set CMS_MONGO_URL in beacon/backend/.env "
            "or keep CMS_NEW copy/.env with MONGO_URL (read-only source)."
        )
    if not BEACON_URI:
        raise SystemExit("MONGODB_URI (Beacon destination) is not set.")
    if (
        CMS_MONGO_URL.rstrip("/") == (BEACON_URI or "").rstrip("/")
        and CMS_MONGO_DB_NAME == BEACON_DB_NAME
    ):
        raise SystemExit(
            "CMS source URI/db matches Beacon destination — refusing to run."
        )
    return CMS_MONGO_URL
