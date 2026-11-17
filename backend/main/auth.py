"""Password hashing and JWT auth for main APIs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import HTTPException, Request
from jose import ExpiredSignatureError, JWTError, jwt

from .config import JWT_ALGORITHM, SECRET_KEY, TOKEN_EXPIRY_SECONDS


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_token(user: dict[str, Any]) -> str:
    expiry = datetime.now(timezone.utc) + timedelta(seconds=TOKEN_EXPIRY_SECONDS)
    payload = {
        "user_id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "type": user["type"],
        "exp": int(expiry.timestamp()),
    }
    editor_id = str(user.get("editor_id") or "").strip()
    if editor_id:
        payload["editor_id"] = editor_id
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


def current_user(request: Request) -> dict[str, Any]:
    header = request.headers.get("Authorization") or ""
    if not header.startswith("Bearer "):
        raise HTTPException(401, "Token is missing")
    raw = header.split(" ", 1)[1].strip()
    if not raw:
        raise HTTPException(401, "Token is missing")
    try:
        return jwt.decode(raw, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except ExpiredSignatureError:
        raise HTTPException(401, "Authentication token has expired") from None
    except JWTError:
        raise HTTPException(401, "Token is invalid or expired") from None
