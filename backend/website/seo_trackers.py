"""Website SEO trackers — Google Search Console / GA4 OAuth + settings (project-scoped).

Ported from CMS_NEW trackers.py. Uses GOOGLE_OAUTH_* (not YouTube GOOGLE_CLIENT_*).
Provider key is google_seo so oauth_states rows do not collide with Instagram/Facebook.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlparse

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException, status

from backend.main.config import (
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
    GOOGLE_OAUTH_REDIRECT_URL,
    JWT_SECRET,
    TOKEN_ENCRYPTION_KEY,
)
from backend.main.db import oauth_connections_col, oauth_states_col, website_settings_col
from backend.main.models import utc_now
from backend.website.models import WebsiteOAuthConnection

GOOGLE_SEO_PROVIDER = "google_seo"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
]
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GSC_SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"
GA4_ACCOUNT_SUMMARIES_URL = "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"

DEFAULT_TRACKER_CONFIG: dict[str, Any] = {
    "site_url": "",
    "brand_name": "",  # Optional report display name (e.g. "Jain Pain Clinic")
    "gsc_property_url": "",
    "ga4_property_id": "",
    "conversion_events": {
        "appointment_bookings": "",
        "contact_form_submissions": "",
        "phone_call_clicks": "",
        "whatsapp_clicks": "",
    },
    "pagespeed_page_limit": 10,
    "pagespeed_strategy": "mobile",
    "keyword_targets": [],
    # URL path prefixes → language labels for monthly content tables
    "language_prefixes": {"hi": "Hindi", "ar": "Arabic", "ru": "Russian"},
    # Optional allow-list (e.g. ["English", "Hindi"] for sites with no AR/RU)
    "enabled_languages": [],
    # Detect romanized Hindi blog slugs (seene-mein-…, *-in-hindi) without /hi/
    "detect_hindi_slugs": False,
    # Optional Generative AI impressions by YYYY-MM (GSC UI export; API does not expose this yet)
    # Example: {"2026-10": 83000, "2026-09": 84100} or {"2026-10": {"impressions": 83000}}
    "ai_by_month": {},
    # Rank-bands page: auto | page | query (auto uses queries when few pages rank in top 3)
    "rank_bands_dimension": "auto",
}


def _dump_model(model) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if hasattr(value, "tzinfo"):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def normalize_site_url(value: Any) -> str:
    site_url = str(value or "").strip()
    if not site_url:
        return ""
    if "://" not in site_url:
        site_url = f"https://{site_url}"
    parsed = urlparse(site_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Site URL must be a valid http or https URL",
        )
    return site_url.rstrip("/")


def site_url_from_gsc_property(property_url: Any) -> str:
    """Derive an https homepage URL from a GSC property (sc-domain: or URL-prefix)."""
    prop = str(property_url or "").strip()
    if not prop:
        return ""
    if prop.startswith("sc-domain:"):
        host = prop.split(":", 1)[1].strip().lstrip(".")
        if not host:
            return ""
        return f"https://{host}"
    if prop.startswith(("http://", "https://")):
        try:
            return normalize_site_url(prop)
        except HTTPException:
            return ""
    return ""


def resolve_site_url(config: dict[str, Any] | None) -> str:
    """Prefer explicit site_url; otherwise derive from GSC property."""
    cfg = config or {}
    site = str(cfg.get("site_url") or "").strip()
    if site:
        try:
            return normalize_site_url(site)
        except HTTPException:
            pass
    return site_url_from_gsc_property(cfg.get("gsc_property_url"))


def normalize_ga4_property_id(value: Any) -> str:
    raw_value = str(value or "").strip()
    if raw_value.startswith("properties/"):
        return raw_value.split("/", 1)[1]
    return raw_value


def merge_tracker_config(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = {**DEFAULT_TRACKER_CONFIG, **(existing or {}), **(incoming or {})}
    merged["brand_name"] = str(merged.get("brand_name") or "").strip()
    merged["ga4_property_id"] = normalize_ga4_property_id(merged.get("ga4_property_id"))
    merged["gsc_property_url"] = str(merged.get("gsc_property_url") or "").strip()
    # Keep explicit site_url when provided; otherwise fill from GSC property
    explicit_site = str(merged.get("site_url") or "").strip()
    if explicit_site:
        merged["site_url"] = normalize_site_url(explicit_site)
    else:
        merged["site_url"] = site_url_from_gsc_property(merged.get("gsc_property_url"))
    conversion_events = {
        **DEFAULT_TRACKER_CONFIG["conversion_events"],
        **((existing or {}).get("conversion_events") or {}),
        **((incoming or {}).get("conversion_events") or {}),
    }
    merged["conversion_events"] = {
        key: str(value or "").strip() for key, value in conversion_events.items()
    }
    try:
        page_limit = int(merged.get("pagespeed_page_limit") or 10)
    except (TypeError, ValueError):
        page_limit = 10
    merged["pagespeed_page_limit"] = max(1, min(page_limit, 25))
    if merged.get("pagespeed_strategy") not in {"mobile", "desktop"}:
        merged["pagespeed_strategy"] = "mobile"
    if merged.get("rank_bands_dimension") not in {"auto", "page", "query"}:
        merged["rank_bands_dimension"] = "auto"
    merged["detect_hindi_slugs"] = bool(merged.get("detect_hindi_slugs"))
    enabled_languages = merged.get("enabled_languages") or []
    if isinstance(enabled_languages, str):
        enabled_languages = [part.strip() for part in enabled_languages.split(",") if part.strip()]
    if not isinstance(enabled_languages, list):
        enabled_languages = []
    merged["enabled_languages"] = [
        str(item).strip() for item in enabled_languages if str(item).strip()
    ][:12]
    # language_prefixes: keep whatever was merged (including explicit {})
    prefixes = merged.get("language_prefixes")
    if prefixes is None:
        prefixes = dict(DEFAULT_TRACKER_CONFIG["language_prefixes"])
    if not isinstance(prefixes, dict):
        prefixes = dict(DEFAULT_TRACKER_CONFIG["language_prefixes"])
    merged["language_prefixes"] = {
        str(k).strip().lower(): str(v).strip()
        for k, v in prefixes.items()
        if str(k).strip() and str(v).strip()
    }
    keyword_targets = merged.get("keyword_targets") or []
    if isinstance(keyword_targets, str):
        keyword_targets = [item.strip() for item in keyword_targets.splitlines() if item.strip()]
    if not isinstance(keyword_targets, list):
        keyword_targets = []
    merged["keyword_targets"] = [
        str(item).strip() for item in keyword_targets if str(item).strip()
    ][:250]
    ai_by_month = merged.get("ai_by_month") or {}
    if not isinstance(ai_by_month, dict):
        ai_by_month = {}
    cleaned_ai: dict[str, Any] = {}
    for month_key, value in ai_by_month.items():
        key = str(month_key or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}", key):
            continue
        cleaned_ai[key] = value
    merged["ai_by_month"] = cleaned_ai
    return merged


def tracker_config_response(config: dict[str, Any]) -> dict[str, Any]:
    return merge_tracker_config({}, config)


def get_tracker_config(project_id: str) -> dict[str, Any]:
    settings = website_settings_col().find_one({"project_id": project_id}, {"_id": 0})
    return merge_tracker_config({}, (settings or {}).get("tracker_config") or {})


def save_tracker_config(project_id: str, incoming: dict[str, Any]) -> dict[str, Any]:
    existing = get_tracker_config(project_id)
    config = merge_tracker_config(existing, incoming)
    now = utc_now()
    website_settings_col().update_one(
        {"project_id": project_id},
        {
            "$set": {"tracker_config": config, "updated_at": now},
            "$setOnInsert": {"project_id": project_id, "created_at": now},
        },
        upsert=True,
    )
    return config


def google_oauth_config() -> dict[str, str]:
    config = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URL,
    }
    if not config["client_id"] or not config["client_secret"] or not config["redirect_uri"]:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Google OAuth is not configured. Set GOOGLE_OAUTH_CLIENT_ID, "
                "GOOGLE_OAUTH_CLIENT_SECRET, and GOOGLE_OAUTH_REDIRECT_URL."
            ),
        )
    return config


def _fernet() -> Fernet:
    raw_key = TOKEN_ENCRYPTION_KEY or JWT_SECRET
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="TOKEN_ENCRYPTION_KEY is not configured",
        )
    key = base64.urlsafe_b64encode(hashlib.sha256(raw_key.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(token: str) -> str:
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def create_google_connect_url(project_id: str) -> dict[str, Any]:
    config = google_oauth_config()
    state = secrets.token_urlsafe(32)
    now = utc_now()
    # Match TG oauth_states shape: _id = "{provider}:{state}"
    oauth_states_col().update_one(
        {"_id": f"{GOOGLE_SEO_PROVIDER}:{state}"},
        {
            "$set": {
                "_id": f"{GOOGLE_SEO_PROVIDER}:{state}",
                "state": state,
                "project_id": project_id,
                "provider": GOOGLE_SEO_PROVIDER,
                "created_at": now,
                "expires_at": now + timedelta(minutes=15),
            }
        },
        upsert=True,
    )
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return {
        "auth_url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}",
        "state": state,
        "scopes": GOOGLE_SCOPES,
    }


def exchange_google_callback(code: str, state: str) -> dict[str, Any]:
    oauth_state = oauth_states_col().find_one_and_delete(
        {"_id": f"{GOOGLE_SEO_PROVIDER}:{state}"}
    )
    if not oauth_state:
        # Fallback if older docs used state field only
        oauth_state = oauth_states_col().find_one_and_delete(
            {"state": state, "provider": GOOGLE_SEO_PROVIDER}
        )
    if not oauth_state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state is invalid or expired",
        )

    project_id = oauth_state.get("project_id")
    if not project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state is missing project_id",
        )

    config = google_oauth_config()
    with httpx.Client(timeout=20) as client:
        response = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": config["redirect_uri"],
            },
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not connect Google account: {response.text[:300]}",
        )

    token_data = response.json()
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google did not return a refresh token. Reconnect and approve offline access.",
        )

    access_token = token_data.get("access_token", "")
    connected_email = fetch_google_email(access_token)
    expires_at = utc_now() + timedelta(
        seconds=max(60, int(token_data.get("expires_in") or 3600) - 60)
    )
    connection = WebsiteOAuthConnection(
        project_id=project_id,
        provider=GOOGLE_SEO_PROVIDER,
        scopes=list(GOOGLE_SCOPES),
        encrypted_refresh_token=encrypt_token(refresh_token),
        access_token=access_token,
        expires_at=expires_at,
        connected_email=connected_email or None,
    )
    document = {key: value for key, value in _dump_model(connection).items() if value is not None}
    insert_fields = {
        "connection_id": document.pop("connection_id"),
        "created_at": document.pop("created_at"),
    }
    oauth_connections_col().update_one(
        {"project_id": project_id, "provider": GOOGLE_SEO_PROVIDER},
        {"$set": document, "$setOnInsert": insert_fields},
        upsert=True,
    )
    return {
        "status": "connected",
        "project_id": project_id,
        "connected_email": connected_email,
    }


def fetch_google_email(access_token: str) -> str:
    if not access_token:
        return ""
    try:
        with httpx.Client(timeout=10) as client:
            response = client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if response.status_code < 400:
            return response.json().get("email", "") or ""
    except Exception:
        return ""
    return ""


def get_google_connection(project_id: str) -> Optional[dict[str, Any]]:
    return oauth_connections_col().find_one(
        {"project_id": project_id, "provider": GOOGLE_SEO_PROVIDER},
        {"_id": 0},
    )


def google_connection_status(project_id: str) -> dict[str, Any]:
    connection = get_google_connection(project_id)
    if not connection or connection.get("status") != "connected":
        return {
            "connected": False,
            "provider": GOOGLE_SEO_PROVIDER,
            "scopes": GOOGLE_SCOPES,
        }
    return {
        "connected": True,
        "provider": GOOGLE_SEO_PROVIDER,
        "scopes": connection.get("scopes") or [],
        "connected_email": connection.get("connected_email", ""),
        "updated_at": connection.get("updated_at"),
    }


def disconnect_google(project_id: str) -> dict[str, Any]:
    now = utc_now()
    oauth_connections_col().update_one(
        {"project_id": project_id, "provider": GOOGLE_SEO_PROVIDER},
        {
            "$set": {
                "status": "disconnected",
                "access_token": "",
                "encrypted_refresh_token": "",
                "updated_at": now,
            }
        },
    )
    return {"status": "disconnected"}


def google_access_token(project_id: str) -> str:
    connection = get_google_connection(project_id)
    if (
        not connection
        or connection.get("status") != "connected"
        or not connection.get("encrypted_refresh_token")
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Google is not connected",
        )
    expires_at = parse_datetime(connection.get("expires_at"))
    if connection.get("access_token") and expires_at and expires_at > utc_now():
        return connection["access_token"]

    config = google_oauth_config()
    refresh_token = decrypt_token(connection["encrypted_refresh_token"])
    with httpx.Client(timeout=20) as client:
        response = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if response.status_code >= 400:
        oauth_connections_col().update_one(
            {"project_id": project_id, "provider": GOOGLE_SEO_PROVIDER},
            {"$set": {"status": "error", "updated_at": utc_now()}},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Could not refresh Google token: {response.text[:300]}",
        )

    data = response.json()
    access_token = data["access_token"]
    expires_at = utc_now() + timedelta(
        seconds=max(60, int(data.get("expires_in") or 3600) - 60)
    )
    oauth_connections_col().update_one(
        {"project_id": project_id, "provider": GOOGLE_SEO_PROVIDER},
        {
            "$set": {
                "access_token": access_token,
                "expires_at": expires_at,
                "status": "connected",
                "updated_at": utc_now(),
            }
        },
    )
    return access_token


def list_google_properties(project_id: str) -> dict[str, Any]:
    token = google_access_token(project_id)
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=25) as client:
        gsc_response = client.get(GSC_SITES_URL, headers=headers)
        ga_response = client.get(GA4_ACCOUNT_SUMMARIES_URL, headers=headers)

    errors: list[dict[str, str]] = []
    gsc_sites: list[dict[str, str]] = []
    ga4_properties: list[dict[str, str]] = []

    if gsc_response.status_code >= 400:
        errors.append(
            {
                "source": "gsc",
                "message": f"Could not load Search Console properties: {gsc_response.text[:300]}",
            }
        )
    else:
        gsc_sites = [
            {
                "site_url": item.get("siteUrl", ""),
                "permission_level": item.get("permissionLevel", ""),
            }
            for item in gsc_response.json().get("siteEntry", [])
        ]

    if ga_response.status_code >= 400:
        errors.append(
            {
                "source": "ga4",
                "message": f"Could not load GA4 properties: {ga_response.text[:300]}",
            }
        )
        return {
            "gsc_sites": gsc_sites,
            "ga4_properties": ga4_properties,
            "errors": errors,
        }

    for account in ga_response.json().get("accountSummaries", []):
        for prop in account.get("propertySummaries", []):
            property_id = normalize_ga4_property_id(prop.get("property", ""))
            ga4_properties.append(
                {
                    "property_id": property_id,
                    "display_name": prop.get("displayName", property_id),
                    "account": account.get("account", ""),
                    "account_display_name": account.get("displayName", ""),
                }
            )
    return {
        "gsc_sites": gsc_sites,
        "ga4_properties": ga4_properties,
        "errors": errors,
    }


def gsc_property_candidates(config: dict[str, Any]) -> list[str]:
    """Ordered GSC property URLs to try (explicit property first, then host variants)."""
    site_url = str(config.get("site_url") or "").strip()
    property_url = str(config.get("gsc_property_url") or "").strip()
    host = ""
    try:
        host = urlparse(site_url if "://" in site_url else f"https://{site_url}").hostname or ""
        host = host.removeprefix("www.")
    except Exception:
        host = ""
    candidates: list[str] = []
    for value in [
        property_url,
        f"sc-domain:{host}" if host else "",
        site_url.rstrip("/") if site_url else "",
        f"{site_url.rstrip('/')}/" if site_url else "",
        f"https://www.{host}" if host else "",
        f"https://www.{host}/" if host else "",
        f"https://{host}" if host else "",
        f"https://{host}/" if host else "",
        f"http://{host}" if host else "",
        f"http://{host}/" if host else "",
    ]:
        if value and value not in candidates:
            candidates.append(value)
    return candidates


def default_gsc_period(*, months: int = 3) -> dict[str, str]:
    # Search Console data lags ~2–3 days.
    end = datetime.now(timezone.utc).date() - timedelta(days=3)
    start = end - timedelta(days=max(28, int(months) * 30))
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}


def _gsc_query(
    token: str,
    property_url: str,
    body: dict[str, Any],
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    encoded_site = quote(property_url, safe="")
    url = f"https://www.googleapis.com/webmasters/v3/sites/{encoded_site}/searchAnalytics/query"
    headers = {"Authorization": f"Bearer {token}"}

    def _do(http: httpx.Client) -> dict[str, Any]:
        response = http.post(url, headers=headers, json=body)
        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Search Console query failed for {property_url}: {response.text[:400]}",
            )
        return response.json()

    if client is not None:
        return _do(client)
    with httpx.Client(timeout=45) as owned:
        return _do(owned)


def fetch_gsc_performance(
    project_id: str,
    *,
    months: int = 3,
    row_limit: int = 25,
) -> dict[str, Any]:
    """GSC Performance-tab style payload: totals, daily series, top queries & pages."""
    config = get_tracker_config(project_id)
    candidates = gsc_property_candidates(config)
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set a GSC property (or site URL) in tracker settings first.",
        )

    token = google_access_token(project_id)
    period = default_gsc_period(months=months)
    last_error = "Could not query Search Console"
    used_property = ""
    totals_json: dict[str, Any] = {}
    daily_json: dict[str, Any] = {}
    query_json: dict[str, Any] = {}
    page_json: dict[str, Any] = {}

    for property_url in candidates:
        try:
            totals_json = _gsc_query(
                token,
                property_url,
                {
                    "startDate": period["start_date"],
                    "endDate": period["end_date"],
                    "rowLimit": 1,
                },
            )
            daily_json = _gsc_query(
                token,
                property_url,
                {
                    "startDate": period["start_date"],
                    "endDate": period["end_date"],
                    "dimensions": ["date"],
                    "rowLimit": 5000,
                },
            )
            query_json = _gsc_query(
                token,
                property_url,
                {
                    "startDate": period["start_date"],
                    "endDate": period["end_date"],
                    "dimensions": ["query"],
                    "rowLimit": max(1, min(int(row_limit), 250)),
                },
            )
            page_json = _gsc_query(
                token,
                property_url,
                {
                    "startDate": period["start_date"],
                    "endDate": period["end_date"],
                    "dimensions": ["page"],
                    "rowLimit": max(1, min(int(row_limit), 250)),
                },
            )
            used_property = property_url
            break
        except HTTPException as exc:
            last_error = str(exc.detail)
            continue
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=last_error)

    total_row = (totals_json.get("rows") or [{}])[0]
    daily = []
    for row in daily_json.get("rows") or []:
        daily.append(
            {
                "date": (row.get("keys") or [""])[0],
                "clicks": row.get("clicks", 0) or 0,
                "impressions": row.get("impressions", 0) or 0,
                "ctr": round((row.get("ctr") or 0) * 100, 2),
                "position": round(row.get("position") or 0, 2),
            }
        )
    daily.sort(key=lambda item: item["date"])

    def _dim_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for row in payload.get("rows") or []:
            rows.append(
                {
                    "key": ((row.get("keys") or [""])[0] or "").strip(),
                    "clicks": row.get("clicks", 0) or 0,
                    "impressions": row.get("impressions", 0) or 0,
                    "ctr": round((row.get("ctr") or 0) * 100, 2),
                    "position": round(row.get("position") or 0, 2),
                }
            )
        return rows

    return {
        "property": used_property,
        "period": period,
        "months": months,
        "totals": {
            "clicks": total_row.get("clicks", 0) or 0,
            "impressions": total_row.get("impressions", 0) or 0,
            "ctr": round((total_row.get("ctr") or 0) * 100, 2),
            "position": round(total_row.get("position") or 0, 2),
        },
        "daily": daily,
        "queries": _dim_rows(query_json),
        "pages": _dim_rows(page_json),
    }
