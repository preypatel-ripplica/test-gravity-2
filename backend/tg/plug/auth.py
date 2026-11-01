from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from backend.tg.config import settings
from backend.tg.plug.database import fetch_creator

PLUG_AUD = "plug"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/plug/auth.login")


def create_plug_token(username: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": f"plug:{username}", "aud": PLUG_AUD, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


async def get_current_creator(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            audience=PLUG_AUD,
        )
        raw_sub: str | None = payload.get("sub")
        if not raw_sub or not str(raw_sub).startswith("plug:"):
            raise credentials_exception
        username = str(raw_sub)[5:]
        if not username:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    creator = fetch_creator(username, include_password=True)
    if creator is None:
        raise credentials_exception
    if not creator.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )
    return creator
