"""Meta WhatsApp Embedded Signup onboarding (backend).

After a client completes the Embedded Signup popup in the admin console, the
browser sends us an exchangeable `code` + the WABA/phone ids. Here we exchange
that server-to-server for the client-scoped **business (BISU) token**, subscribe
our app to the client's WABA, read the phone metadata, and (optionally) register
the number for the Cloud API.

Sync `requests` to match the rest of the codebase. The WABA subscribe reuses the
existing `whatsapp_service.subscribe_whatsapp_business_account`.
"""

from __future__ import annotations


import os
from typing import Any

import requests
from fastapi import HTTPException


def _graph_version() -> str:
    return os.getenv("META_GRAPH_VERSION") or os.getenv("WHATSAPP_API_VERSION", "v25.0")


def _graph_base() -> str:
    return f"https://graph.facebook.com/{_graph_version()}"


def _require_app_creds() -> tuple[str, str]:
    app_id = os.getenv("META_APP_ID")
    app_secret = os.getenv("META_APP_SECRET")
    if not app_id or not app_secret:
        raise HTTPException(
            status_code=500,
            detail="META_APP_ID / META_APP_SECRET are not configured.",
        )
    return app_id, app_secret


def _raise_meta(response, message: str):
    try:
        body = response.json()
    except ValueError:
        body = {"raw_response": response.text}
    raise HTTPException(
        status_code=502,
        detail={
            "message": message,
            "meta_status_code": response.status_code,
            "meta_response": body,
        },
    )


def exchange_code_for_business_token(code: str) -> dict[str, Any]:
    """Embedded Signup returns an exchangeable code; swap it (with the app
    id/secret) for the customer-scoped business/BISU token."""
    app_id, app_secret = _require_app_creds()

    response = requests.get(
        f"{_graph_base()}/oauth/access_token",
        params={
            "client_id": app_id,
            "client_secret": app_secret,
            "code": code,
        },
        timeout=30,
    )
    if response.status_code >= 400:
        _raise_meta(response, "Failed to exchange Embedded Signup code for a business token.")

    data = response.json()
    if not data.get("access_token"):
        raise HTTPException(
            status_code=502,
            detail={"message": "Meta did not return an access_token.", "meta_response": data},
        )
    return data


def get_phone_number_metadata(phone_number_id: str, access_token: str) -> dict[str, Any]:
    response = requests.get(
        f"{_graph_base()}/{phone_number_id}",
        params={"fields": "id,display_phone_number,verified_name,quality_rating"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if response.status_code >= 400:
        _raise_meta(response, "Failed to fetch phone number metadata.")
    return response.json()


def register_phone_number(phone_number_id: str, access_token: str, pin: str) -> dict[str, Any]:
    """Register the number for the Cloud API (required within 14 days of
    Embedded Signup). `pin` is the number's 6-digit two-step-verification PIN."""
    response = requests.post(
        f"{_graph_base()}/{phone_number_id}/register",
        json={"messaging_product": "whatsapp", "pin": pin},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    if response.status_code >= 400:
        _raise_meta(response, "Failed to register phone number for the Cloud API.")
    return response.json()
