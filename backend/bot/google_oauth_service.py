"""Google OAuth 2.0 web redirect flow for connecting a Google account to a
`google_connections` record (for the Sheets node) - the automated replacement
for the manual `scripts/generate_google_refresh_token.py` desktop flow.

Works on serverless (Vercel): plain `requests`, no local browser, and a
stateless HMAC-signed `state` so the /start and /callback invocations don't need
shared memory. Requires a **Web** OAuth client in GCP whose authorized redirect
URI is GOOGLE_OAUTH_REDIRECT_URI.
"""

from __future__ import annotations


import base64
import hashlib
import hmac
import json
import os
from typing import Any
from urllib.parse import urlencode

import requests

from backend.bot.utils import now_utc, short_id


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


def _bot_google_client_id() -> str | None:
    # Prefer BOT_GOOGLE_* so YouTube / website OAuth clients in the shared .env
    # are not overwritten by the WhatsApp bot Sheets client.
    return os.getenv("BOT_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID")


def _bot_google_client_secret() -> str | None:
    return os.getenv("BOT_GOOGLE_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET")


def _state_secret() -> str:
    # Any server-only secret works for signing state; ADMIN_SECRET is always set
    # where the admin flow runs. Falls back to the OAuth client secret.
    secret = os.getenv("ADMIN_SECRET") or _bot_google_client_secret()
    if not secret:
        raise RuntimeError("No secret available to sign OAuth state.")
    return secret


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def sign_state(connection_id: str, client_id: str) -> str:
    """Opaque, tamper-proof state carrying connection_id + client_id. Stateless -
    no server-side storage needed between /start and /callback."""
    payload = {
        "connection_id": connection_id,
        "client_id": client_id,
        "nonce": short_id(),
    }
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64url(
        hmac.new(_state_secret().encode(), body.encode(), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def verify_state(state: str) -> dict[str, Any]:
    try:
        body, sig = state.split(".", 1)
    except ValueError:
        raise ValueError("Malformed OAuth state.")
    expected = _b64url(
        hmac.new(_state_secret().encode(), body.encode(), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(sig, expected):
        raise ValueError("OAuth state signature mismatch.")
    return json.loads(_b64url_decode(body))


def _redirect_uri() -> str:
    uri = (
        os.getenv("BOT_GOOGLE_OAUTH_REDIRECT_URI")
        or os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
    )
    if not uri:
        raise RuntimeError("BOT_GOOGLE_OAUTH_REDIRECT_URI is not configured.")
    return uri


def _client_id() -> str:
    cid = _bot_google_client_id()
    if not cid:
        raise RuntimeError("BOT_GOOGLE_CLIENT_ID is not configured.")
    return cid


def build_consent_url(connection_id: str, client_id: str) -> str:
    """The Google consent URL to redirect the operator's browser to. offline +
    consent guarantees a refresh_token is returned."""
    params = {
        "client_id": _client_id(),
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": sign_state(connection_id, client_id),
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_tokens(code: str) -> dict[str, Any]:
    """Authorization-code grant -> {refresh_token, access_token, ...}."""
    response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": _client_id(),
            "client_secret": _bot_google_client_secret(),
            "redirect_uri": _redirect_uri(),
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Google code exchange failed: {response.status_code} {response.text}"
        )
    return response.json()


def fetch_google_email(access_token: str) -> str | None:
    try:
        response = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        if response.status_code < 400:
            return response.json().get("email")
    except requests.RequestException:
        pass
    return None
