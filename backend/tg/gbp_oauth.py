"""Google Business Profile OAuth. Separate from YouTube so business.manage
is not requested when a client links a channel.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from jose import JWTError, jwt

from backend.tg.auth import create_access_token, get_current_user
from backend.tg.config import settings
from backend.tg.database import (
    fetch_client_doc,
    fetch_user,
    get_gbp_connection,
    pop_gbp_oauth_state,
    save_gbp_connection,
    save_gbp_oauth_state,
)
from backend.tg.schemas import GoogleLoginRequest
from backend.tg.services.gbp_api import GbpApiError, sync_managed_locations

router = APIRouter(tags=["gbp-oauth"])

GBP_SCOPES = ["https://www.googleapis.com/auth/business.manage"]


def _flow() -> Flow:
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(client_config=client_config, scopes=GBP_SCOPES)
    flow.redirect_uri = settings.GBP_REDIRECT_URI
    return flow


def _code_verifier(flow: Flow):
    return (
        getattr(flow, "code_verifier", None)
        or getattr(flow.oauth2session, "code_verifier", None)
        or getattr(flow.oauth2session, "_code_verifier", None)
        or getattr(getattr(flow.oauth2session, "_client", None), "code_verifier", None)
    )


def credentials_from_connection(connection: dict) -> Credentials:
    db_creds = dict(connection.get("google_credentials") or {})
    if not db_creds.get("token") and not db_creds.get("refresh_token"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Business Profile is not connected.",
        )
    return Credentials(
        token=db_creds.get("token"),
        refresh_token=db_creds.get("refresh_token"),
        token_uri=db_creds.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=db_creds.get("scopes") or GBP_SCOPES,
    )


def ensure_gbp_credentials(client_id: str) -> Credentials:
    connection = get_gbp_connection(client_id)
    if not connection:
        raise HTTPException(status_code=400, detail="Google Business Profile is not connected.")
    db_creds = dict(connection.get("google_credentials") or {})
    if not db_creds:
        raise HTTPException(status_code=400, detail="Google Business Profile is not connected.")

    needs_refresh = True
    if db_creds.get("expiry") and db_creds.get("token"):
        expiry_dt = datetime.fromisoformat(db_creds["expiry"]).replace(tzinfo=None)
        needs_refresh = (expiry_dt - datetime.utcnow()).total_seconds() < 60

    if not needs_refresh:
        return credentials_from_connection(connection)

    if not db_creds.get("refresh_token"):
        connection["status"] = "expired"
        save_gbp_connection(client_id, connection)
        raise HTTPException(
            status_code=400,
            detail="Google Business Profile session expired. Reconnect the profile.",
        )

    refresh_creds = Credentials(
        token=None,
        refresh_token=db_creds["refresh_token"],
        token_uri=db_creds.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=db_creds.get("scopes") or GBP_SCOPES,
    )
    try:
        refresh_creds.refresh(Request())
    except Exception as exc:  # noqa: BLE001
        connection["status"] = "expired"
        save_gbp_connection(client_id, connection)
        raise HTTPException(
            status_code=400,
            detail=f"Failed to refresh Google Business Profile credentials: {exc}",
        ) from exc

    db_creds["token"] = refresh_creds.token
    if refresh_creds.expiry:
        db_creds["expiry"] = refresh_creds.expiry.replace(tzinfo=None).isoformat()
    connection["google_credentials"] = db_creds
    connection["status"] = "connected"
    save_gbp_connection(client_id, connection)
    return credentials_from_connection(connection)


def _store_credentials(client_id: str, username: str, credentials: Credentials) -> None:
    existing = get_gbp_connection(client_id) or {}
    refresh = credentials.refresh_token or (existing.get("google_credentials") or {}).get("refresh_token")
    expiry = credentials.expiry.replace(tzinfo=None).isoformat() if credentials.expiry else None
    existing.update(
        {
            "username": username,
            "status": "connected",
            "connected_at": existing.get("connected_at") or datetime.now(timezone.utc).isoformat(),
            "auto_reply_mode": existing.get("auto_reply_mode") or "off",
            "skip_one_star": existing.get("skip_one_star", True),
            "skip_angry": existing.get("skip_angry", True),
            "active_location_id": existing.get("active_location_id"),
            "google_credentials": {
                "token": credentials.token,
                "refresh_token": refresh,
                "token_uri": credentials.token_uri,
                "scopes": list(credentials.scopes) if credentials.scopes else GBP_SCOPES,
                "expiry": expiry,
            },
        }
    )
    save_gbp_connection(client_id, existing)


@router.post("/gbp.login")
def gbp_login(
    body: GoogleLoginRequest,
    current_user: dict = Depends(get_current_user),
):
    if not fetch_client_doc(body.client_id, username=current_user["username"]):
        raise HTTPException(status_code=404, detail="Client not found")

    state_token = create_access_token(
        data={
            "sub": current_user["username"],
            "purpose": "gbp-oauth",
            "client_id": body.client_id,
        }
    )
    flow = _flow()
    authorization_url, _state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state_token,
    )
    verifier = _code_verifier(flow)
    save_gbp_oauth_state(
        state_token,
        {
            "client_id": body.client_id,
            "username": current_user["username"],
            "code_verifier": verifier,
        },
    )
    return {"authorization_url": authorization_url}


@router.get("/gbp.callback")
def gbp_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        username = payload.get("sub")
        purpose = payload.get("purpose")
        client_id = payload.get("client_id")
        if username is None or purpose != "gbp-oauth" or not client_id:
            raise HTTPException(status_code=400, detail="Invalid state token parameters")
    except JWTError as exc:
        raise HTTPException(status_code=400, detail="State token validation failed") from exc

    if not fetch_user(username):
        raise HTTPException(status_code=404, detail="User not found")
    if not fetch_client_doc(client_id, username=username):
        raise HTTPException(status_code=404, detail="Client not found")

    state_row = pop_gbp_oauth_state(state) or {}
    code_verifier = state_row.get("code_verifier")
    flow = _flow()
    try:
        if code_verifier:
            flow.fetch_token(code=code, code_verifier=code_verifier)
        else:
            flow.fetch_token(code=code)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to fetch token from Google: {exc}") from exc

    credentials = flow.credentials
    _store_credentials(client_id, username, credentials)
    try:
        sync_managed_locations(client_id, credentials)
    except GbpApiError as exc:
        # Tokens are stored; location list can be retried from the Locations page.
        print(f"[gbp] location sync after oauth failed: {exc}", flush=True)

    frontend = settings.FRONTEND_URL.rstrip("/")
    return RedirectResponse(
        url=f"{frontend}/clients/{client_id}/gbp/locations?gbp_auth=success"
    )
