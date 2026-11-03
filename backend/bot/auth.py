from __future__ import annotations

import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Header, HTTPException, Query

from backend.bot.storage import get_client_by_id
from backend.bot.utils import now_utc


def require_admin(
    x_admin_secret: str = Header(default="", alias="X-Admin-Secret"),
) -> None:
    """Gate for long-lived token generation. Regular API access uses bearer
    client tokens; this shared secret is intentionally limited to issuing or
    returning the stored long-lived client token."""
    expected = os.getenv("ADMIN_SECRET")

    if not expected:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_SECRET is not configured on the server.",
        )

    if not x_admin_secret or not hmac.compare_digest(x_admin_secret, expected):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid X-Admin-Secret.",
        )


def resolve_client_from_token(token: str) -> str:
    """Validate a raw client JWT and return its client id. Shared by the header
    auth dependency and the media proxy (which receives the token as a query
    param because an <img> tag can't send an Authorization header)."""
    payload = decode_client_token(token)

    token_type = payload.get("type")
    if token_type not in ["session", "long_live"]:
        raise HTTPException(status_code=401, detail="Invalid token type.")

    client_id = payload.get("client_id")
    if not client_id:
        raise HTTPException(status_code=401, detail="Token missing client_id.")

    client = get_client_by_id(client_id)

    if not client:
        raise HTTPException(
            status_code=401,
            detail="Unknown client in token.",
        )

    if client.status != "active":
        raise HTTPException(
            status_code=403,
            detail="Client is inactive.",
        )

    if token_type == "long_live" and token != client.long_live_token:
        raise HTTPException(
            status_code=401,
            detail="Long-lived token is no longer active for this client.",
        )

    return client.id


def get_current_client_id(
    authorization: str = Header(default="", alias="Authorization"),
) -> str:
    """The single 'who is asking?' choke point.

    Client-facing endpoints authenticate with Authorization: Bearer <jwt>.
    The token carries the client_id; callers never send X-Client-Id.
    """
    token = extract_bearer_token(authorization)
    return resolve_client_from_token(token)


def get_jwt_secret() -> str:
    """Return the server-side JWT signing secret from JWT_SECRET.

    Without this value the server cannot safely create or verify client tokens,
    so callers get a 500 configuration error instead of silently accepting an
    insecure default.
    """
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="JWT_SECRET is not configured on the server.",
        )
    return secret


def get_jwt_algorithm() -> str:
    """Return the JWT signing algorithm.

    Defaults to HS256, which matches the shared-secret JWT setup used by this
    app. JWT_ALGORITHM exists so deployments can override it deliberately.
    """
    return os.getenv("JWT_ALGORITHM", "HS256")


def token_days(env_name: str, default: int) -> int:
    """Read a token lifetime, in days, from an env var.

    If the env var is absent, use the supplied default. If it is present but
    not an integer, fail with a server configuration error.
    """
    raw = os.getenv(env_name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(
            status_code=500,
            detail=f"{env_name} must be an integer number of days.",
        )


def session_token_delta() -> timedelta:
    """Return the configured lifetime for inbox login session tokens."""
    return timedelta(days=token_days("SESSION_TOKEN_DAYS", 7))


def long_live_token_delta() -> timedelta:
    """Return the configured lifetime for developer/admin long-lived tokens."""
    return timedelta(days=token_days("LONG_LIVE_TOKEN_DAYS", 365))


def create_client_token(
    client_id: str,
    token_type: str,
    expires_at: datetime,
) -> str:
    """Create a signed JWT that identifies one client.

    token_type must be "session" for inbox login tokens or "long_live" for
    developer/admin tokens. The token stores client_id, type, issued-at, and
    expiry timestamps, then signs them with JWT_SECRET.
    """
    if token_type not in ["session", "long_live"]:
        raise ValueError("token_type must be 'session' or 'long_live'.")

    issued_at = now_utc()
    payload: dict[str, Any] = {
        "type": token_type,
        "client_id": client_id,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }

    return jwt.encode(payload, get_jwt_secret(), algorithm=get_jwt_algorithm())


def decode_client_token(token: str) -> dict[str, Any]:
    """Verify and decode a client JWT.

    PyJWT checks the signature and exp timestamp. This helper maps token errors
    to 401 HTTP responses so protected endpoints fail consistently.
    """
    try:
        return jwt.decode(
            token,
            get_jwt_secret(),
            algorithms=[get_jwt_algorithm()],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")


def extract_bearer_token(authorization: str) -> str:
    """Extract the raw token from an Authorization header.

    Expected format: "Bearer <token>". Missing, malformed, or empty bearer
    headers are rejected with 401 before any endpoint logic runs.
    """
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization bearer token.",
        )
    return token.strip()


def ensure_aware_utc(value: datetime | None) -> datetime | None:
    """Normalize a datetime to timezone-aware UTC.

    Mongo can return naive datetimes. Token-expiry comparisons need aware UTC
    values to avoid Python errors and timezone mistakes.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def assert_owned(obj, client_id: str, label: str = "Resource"):
    """Object-level isolation: a caller must never learn whether another
    client's id exists, so a wrong-client hit is the same 404 as a miss."""
    if obj is None or getattr(obj, "client_id", None) != client_id:
        raise HTTPException(
            status_code=404,
            detail=f"{label} not found.",
        )

    return obj


class Pagination:
    """FastAPI dependency for common limit/offset pagination query params."""

    def __init__(
        self,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        self.limit = limit
        self.offset = offset


def page_response(total: int, pagination: "Pagination", key: str, items: list):
    """Build the standard paginated API response shape."""
    return {
        "total": total,
        "limit": pagination.limit,
        "offset": pagination.offset,
        key: items,
    }
