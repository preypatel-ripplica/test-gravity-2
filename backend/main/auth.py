"""Password hashing and JWT auth for main APIs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import HTTPException, Request
from jose import JWTError, jwt

from .config import JWT_ALGORITHM, JWT_SECRET, TOKEN_EXPIRY_SECONDS


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_token(user: dict[str, Any]) -> str:
    expiry = datetime.now(timezone.utc) + timedelta(seconds=TOKEN_EXPIRY_SECONDS)
    return jwt.encode(
        {
            "user_id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "type": user["type"],
            "exp": expiry.timestamp(),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


def current_user(request: Request) -> dict[str, Any]:
    header = request.headers.get("Authorization") or ""
    if not header.startswith("Bearer "):
        raise HTTPException(401, "Token is missing")
    payload = decode_token(header.split(" ", 1)[1])
    if not payload:
        raise HTTPException(401, "Token is invalid or expired")
    return payload
