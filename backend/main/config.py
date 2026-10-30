"""Shared settings for Beacon — TG-compatible env names for live product."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# beacon/          -> ROOT
# beacon/backend/  -> BACKEND_ROOT
ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
# Prefer .env files over stale shell exports (same idea as TG)
load_dotenv(ROOT / ".env")
load_dotenv(BACKEND_ROOT / ".env", override=True)
load_dotenv(override=True)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


# --- Mongo (same names as TG) ---
MONGODB_URI = _env("MONGODB_URI")
MONGODB_DB_NAME = _env("MONGODB_DB_NAME", "beacon")

# --- Auth: prefer TG SECRET_KEY; fall back to legacy Beacon JWT_SECRET ---
SECRET_KEY = _env("SECRET_KEY") or _env("JWT_SECRET") or "dev-change-me"
JWT_SECRET = SECRET_KEY  # alias used by existing Beacon auth
JWT_ALGORITHM = _env("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = _env_int("ACCESS_TOKEN_EXPIRE_MINUTES", 180)
# Legacy Beacon seconds; if only TOKEN_EXPIRY_SECONDS set, honour it
_legacy_secs = os.getenv("TOKEN_EXPIRY_SECONDS")
if _legacy_secs and not os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES"):
    TOKEN_EXPIRY_SECONDS = int(_legacy_secs)
else:
    TOKEN_EXPIRY_SECONDS = ACCESS_TOKEN_EXPIRE_MINUTES * 60

# --- App URLs ---
BASE_URL = _env("BASE_URL", "http://localhost:8000")
FRONTEND_URL = _env("FRONTEND_URL", "http://localhost:5173")
CORS_ORIGINS = _env(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:5174,http://localhost:5175,https://app.xyz",
)


def cors_origin_list() -> list[str]:
    return [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]


# --- Google OAuth / YouTube ---
GOOGLE_CLIENT_ID = _env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _env("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = _env(
    "GOOGLE_REDIRECT_URI", "http://localhost:8000/google.callback"
)

# --- GCS ---
GCS_BUCKET_NAME = _env("GCS_BUCKET_NAME")
GCS_KEY_JSON = _env("GCS_KEY_JSON")

# --- OpenAI ---
OPENAI_API_KEY = _env("OPENAI_API_KEY")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-6.1-sol")
OPENAI_REASONING_EFFORT = _env("OPENAI_REASONING_EFFORT", "medium")
OPENAI_CONTENT_PLAN_MODEL = _env("OPENAI_CONTENT_PLAN_MODEL", "gpt-6.1-sol")
OPENAI_CONTENT_PLAN_MAP_EFFORT = _env("OPENAI_CONTENT_PLAN_MAP_EFFORT", "low")
OPENAI_IMAGE_MODEL = _env("OPENAI_IMAGE_MODEL", "gpt-image-2")
THUMBNAIL_MODEL = _env("THUMBNAIL_MODEL", "gpt-image-2")
YT_METADATA_MODEL = _env("YT_METADATA_MODEL", "gpt-6.1-sol")
YT_METADATA_EFFORT = _env("YT_METADATA_EFFORT", "medium")
OPENAI_TTS_MODEL = _env("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = _env("OPENAI_TTS_VOICE", "onyx")
OPENAI_TTS_INSTRUCTIONS = _env(
    "OPENAI_TTS_INSTRUCTIONS",
    (
        "Speak in natural Hindi for an Indian audience. "
        "Use a clear Hinglish delivery: Hindi sentence rhythm with English medical terms "
        "pronounced the way Indian doctors say them (e.g. MRI, nerve, diabetes). "
        "Calm, respectful male physician tone — not rushed, not theatrical. "
        "Do not read stage directions or timing labels."
    ),
)
OPENAI_LOG_PATH = _env("OPENAI_LOG_PATH", "log.txt")
SCRAPE_LOG_PATH = _env("SCRAPE_LOG_PATH", "scrape_log.txt")

# --- DataForSEO / Trends ---
DATAFORSEO_LOGIN = _env("DATAFORSEO_LOGIN")
DATAFORSEO_PASSWORD = _env("DATAFORSEO_PASSWORD")
TRENDS_GEO = _env("TRENDS_GEO", "IN")
TRENDS_LOCATION_NAME = _env("TRENDS_LOCATION_NAME", "India")
TRENDS_TTL_DAYS = _env_int("TRENDS_TTL_DAYS", 7)

# --- Instagram / Facebook (redirects + scopes; app id/secret per project) ---
INSTAGRAM_GRAPH_VERSION = _env("INSTAGRAM_GRAPH_VERSION", "v24.0")
INSTAGRAM_REDIRECT_URI = _env(
    "INSTAGRAM_REDIRECT_URI", "http://localhost:8000/social.instagram.callback"
)
PLUG_INSTA_REDIRECT_URI = _env(
    "PLUG_INSTA_REDIRECT_URI", "http://localhost:8000/social.instagram.callback"
)
INSTAGRAM_OAUTH_SCOPES = _env(
    "INSTAGRAM_OAUTH_SCOPES",
    "instagram_business_basic,instagram_business_content_publish,instagram_business_manage_insights",
)
FACEBOOK_REDIRECT_URI = _env(
    "FACEBOOK_REDIRECT_URI", "http://localhost:8000/social.facebook.callback"
)
FACEBOOK_OAUTH_SCOPES = _env(
    "FACEBOOK_OAUTH_SCOPES",
    "pages_manage_posts,pages_read_engagement,pages_show_list",
)


def require_google_oauth() -> None:
    from fastapi import HTTPException

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            400,
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET "
            "(same as test-gravity .env).",
        )


def require_openai() -> None:
    from fastapi import HTTPException

    if not OPENAI_API_KEY:
        raise HTTPException(
            400,
            "OpenAI is not configured. Set OPENAI_API_KEY (same as test-gravity .env).",
        )


# TG-style `settings.X` access: a real object whose attributes are copied from the
# module-level values above (snapshot at import time, like TG's pydantic Settings).
_SETTINGS_NAMES = (
    "SECRET_KEY",
    "JWT_ALGORITHM",
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
    "FRONTEND_URL",
    "BASE_URL",
    "CORS_ORIGINS",
    "MONGODB_URI",
    "MONGODB_DB_NAME",
    "GCS_BUCKET_NAME",
    "GCS_KEY_JSON",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_REASONING_EFFORT",
    "OPENAI_CONTENT_PLAN_MODEL",
    "OPENAI_CONTENT_PLAN_MAP_EFFORT",
    "OPENAI_IMAGE_MODEL",
    "THUMBNAIL_MODEL",
    "YT_METADATA_MODEL",
    "YT_METADATA_EFFORT",
    "OPENAI_TTS_MODEL",
    "OPENAI_TTS_VOICE",
    "OPENAI_TTS_INSTRUCTIONS",
    "OPENAI_LOG_PATH",
    "SCRAPE_LOG_PATH",
    "DATAFORSEO_LOGIN",
    "DATAFORSEO_PASSWORD",
    "TRENDS_GEO",
    "TRENDS_LOCATION_NAME",
    "TRENDS_TTL_DAYS",
    "INSTAGRAM_GRAPH_VERSION",
    "INSTAGRAM_REDIRECT_URI",
    "PLUG_INSTA_REDIRECT_URI",
    "INSTAGRAM_OAUTH_SCOPES",
    "FACEBOOK_REDIRECT_URI",
    "FACEBOOK_OAUTH_SCOPES",
)


class _Settings:
    """Plain attribute container; every name in _SETTINGS_NAMES is set from module globals."""

    def __init__(self) -> None:
        g = globals()
        for name in _SETTINGS_NAMES:
            setattr(self, name, g[name])

    @property
    def cors_origin_list(self) -> list[str]:
        return cors_origin_list()

    def __repr__(self) -> str:  # never dump secrets
        return "<beacon Settings>"


settings = _Settings()
