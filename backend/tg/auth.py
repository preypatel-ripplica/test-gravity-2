"""TG-compatible auth on top of Beacon JWTs.

TG route code does:
    current_user: dict = Depends(get_current_user)
    username = current_user["username"]

Here `username` is the user's email. Tokens are Beacon tokens
(`backend.main.auth.create_token`); legacy TG tokens carrying `sub=<email>`
are also accepted so OAuth-state style tokens can be reused.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt

from backend.main.auth import (  # noqa: F401  (re-exported for TG callers)
    decode_token,
    hash_password as get_password_hash,
    verify_password as _verify_password,
)
from backend.main.db import users_col

from .config import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_ALGORITHM, SECRET_KEY, settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return _verify_password(plain_password, hashed_password)
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Same contract as TG: encode `data` + exp with SECRET_KEY / JWT_ALGORITHM."""
    to_encode = dict(data)
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES or ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=JWT_ALGORITHM)


def tg_user_from_doc(doc: dict) -> dict:
    """Shape a users-collection doc like TG's fetch_user() / get_current_user() result."""
    email = doc.get("email") or ""
    return {
        "username": email,
        "email": email,
        "user_id": doc.get("id"),
        "id": doc.get("id"),
        "name": doc.get("name") or email,
        "type": doc.get("type") or "client",
        "is_active": bool(doc.get("is_active", True)),
        "active_client_id": doc.get("active_client_id"),
        "active_channel_id": doc.get("active_channel_id"),
        "clients": [],
    }


def _token_from_request(request: Request) -> str:
    header = request.headers.get("Authorization") or ""
    if not header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return header.split(" ", 1)[1].strip()


def get_current_user(request: Request) -> dict[str, Any]:
    """FastAPI dependency: Beacon JWT -> TG-shaped user dict (username == email)."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = _token_from_request(request)
    payload = decode_token(token)
    if not payload:
        raise unauthorized

    doc = None
    user_id = payload.get("user_id")
    if user_id:
        doc = users_col().find_one({"id": user_id}, {"_id": 0})
    if doc is None and payload.get("sub"):  # TG-style token
        doc = users_col().find_one({"email": str(payload["sub"]).lower()}, {"_id": 0})
    if doc is None and payload.get("email"):
        doc = users_col().find_one({"email": str(payload["email"]).lower()}, {"_id": 0})
    if doc is None:
        raise unauthorized
    if not doc.get("is_active", True):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    return tg_user_from_doc(doc)


# Convenience for routes that want the dependency spelled out.
CurrentUser = Depends(get_current_user)


def decode_access_token(token: str) -> dict | None:
    """Decode an OAuth-state style token made by create_access_token (None if invalid)."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
