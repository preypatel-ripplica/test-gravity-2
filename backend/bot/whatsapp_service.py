from __future__ import annotations

import os
from typing import Any

import requests
from fastapi import HTTPException


def get_whatsapp_access_token() -> str:
    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN")

    if not access_token:
        raise HTTPException(
            status_code=500,
            detail="WHATSAPP_ACCESS_TOKEN is not configured.",
        )

    return access_token


def get_whatsapp_api_version() -> str:
    return os.getenv("WHATSAPP_API_VERSION", "v25.0")


def build_whatsapp_messages_url(phone_number_id: str) -> str:
    api_version = get_whatsapp_api_version()

    return f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"


def _post_to_meta(
    phone_number_id: str,
    payload: dict,
    access_token: str | None,
    error_message: str,
) -> dict[str, Any]:
    """One POST to the WhatsApp Cloud /messages endpoint: attaches auth, posts
    the payload, parses the response, and raises a 502 carrying Meta's error on
    any non-2xx. Every sender shares this so the HTTP boilerplate lives once."""
    access_token = access_token or get_whatsapp_access_token()

    response = requests.post(
        build_whatsapp_messages_url(phone_number_id),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20,
    )

    try:
        response_json = response.json()
    except ValueError:
        response_json = {"raw_response": response.text}

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={
                "message": error_message,
                "meta_status_code": response.status_code,
                "meta_response": response_json,
            },
        )

    return response_json


def send_whatsapp_text_message(
    phone_number_id: str,
    to_phone: str,
    text: str,
    access_token: str | None = None,
) -> dict[str, Any]:
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": text,
        },
    }

    return _post_to_meta(
        phone_number_id, payload, access_token, "Failed to send WhatsApp text message."
    )


def build_whatsapp_media_url(media_id: str) -> str:
    api_version = get_whatsapp_api_version()

    return f"https://graph.facebook.com/{api_version}/{media_id}"


def download_whatsapp_media(
    media_id: str,
    access_token: str | None = None,
) -> tuple[bytes, str]:
    """Two-step Meta media download: resolve the media id to a short-lived
    Graph URL, then GET that URL with the same bearer token. Returns
    (raw_bytes, mime_type). Raises 502 (carrying Meta's error) on failure."""
    access_token = access_token or get_whatsapp_access_token()
    headers = {"Authorization": f"Bearer {access_token}"}

    meta_response = requests.get(
        build_whatsapp_media_url(media_id), headers=headers, timeout=20
    )
    if meta_response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Failed to resolve WhatsApp media id.",
                "meta_status_code": meta_response.status_code,
                "meta_response": meta_response.text,
            },
        )

    info = meta_response.json()
    media_url = info.get("url")
    mime_type = info.get("mime_type") or "application/octet-stream"

    if not media_url:
        raise HTTPException(
            status_code=502,
            detail={"message": "WhatsApp media metadata had no download url.", "info": info},
        )

    binary_response = requests.get(media_url, headers=headers, timeout=30)
    if binary_response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Failed to download WhatsApp media bytes.",
                "meta_status_code": binary_response.status_code,
            },
        )

    return binary_response.content, mime_type


def upload_whatsapp_media(
    phone_number_id: str,
    data: bytes,
    mime_type: str,
    filename: str,
    access_token: str | None = None,
) -> str:
    """Upload raw bytes to Meta's media store and return the media id. Used for
    audio: sending audio by link makes Meta re-fetch and re-process the file
    (unreliable), whereas an uploaded media id is stored at upload time and sends
    cleanly."""
    access_token = access_token or get_whatsapp_access_token()
    api_version = get_whatsapp_api_version()

    response = requests.post(
        f"https://graph.facebook.com/{api_version}/{phone_number_id}/media",
        headers={"Authorization": f"Bearer {access_token}"},
        data={"messaging_product": "whatsapp", "type": mime_type},
        files={"file": (filename, data, mime_type)},
        timeout=30,
    )

    try:
        response_json = response.json()
    except ValueError:
        response_json = {"raw_response": response.text}

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Failed to upload WhatsApp media.",
                "meta_status_code": response.status_code,
                "meta_response": response_json,
            },
        )

    media_id = response_json.get("id")
    if not media_id:
        raise HTTPException(
            status_code=502,
            detail={"message": "WhatsApp media upload returned no id.", "info": response_json},
        )
    return media_id


def send_whatsapp_media_message(
    phone_number_id: str,
    to_phone: str,
    media_type: str,
    link: str | None = None,
    media_id: str | None = None,
    caption: str | None = None,
    filename: str | None = None,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Send media either by uploaded `media_id` (preferred for audio) or by
    public/signed `link` (Meta fetches it itself). image/document/video accept a
    caption; document also accepts a filename."""
    if media_type not in ("image", "document", "video", "audio"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported media_type '{media_type}'.",
        )
    if not media_id and not link:
        raise HTTPException(
            status_code=400,
            detail="send_whatsapp_media_message needs either media_id or link.",
        )

    media_object: dict[str, Any] = {"id": media_id} if media_id else {"link": link}

    if caption and media_type in ("image", "document", "video"):
        media_object["caption"] = caption
    if filename and media_type == "document":
        media_object["filename"] = filename

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": media_type,
        media_type: media_object,
    }

    return _post_to_meta(
        phone_number_id, payload, access_token, "Failed to send WhatsApp media message."
    )


def send_whatsapp_button_message(
    phone_number_id: str,
    to_phone: str,
    body_text: str,
    buttons: list[dict[str, str]],
    access_token: str | None = None,
) -> dict[str, Any]:
    if not buttons:
        raise HTTPException(
            status_code=400,
            detail="Button message must have at least one button.",
        )

    if len(buttons) > 3:
        raise HTTPException(
            status_code=400,
            detail="WhatsApp reply button message supports maximum 3 buttons.",
        )

    whatsapp_buttons = []

    for button in buttons:
        button_id = button.get("id")
        button_title = button.get("title") or button.get("label")

        if not button_id or not button_title:
            raise HTTPException(
                status_code=400,
                detail="Each button must have id and title/label.",
            )

        whatsapp_buttons.append(
            {
                "type": "reply",
                "reply": {
                    "id": button_id,
                    "title": button_title,
                },
            }
        )

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": body_text,
            },
            "action": {
                "buttons": whatsapp_buttons,
            },
        },
    }

    return _post_to_meta(
        phone_number_id, payload, access_token, "Failed to send WhatsApp button message."
    )

def send_whatsapp_list_message(
    phone_number_id: str,
    to_phone: str,
    body_text: str,
    list_config: dict,
    access_token: str | None = None,
) -> dict[str, Any]:
    button_text = list_config.get("button_text") or "Choose option"
    sections = list_config.get("sections", [])

    if not sections:
        raise HTTPException(
            status_code=400,
            detail="List message must have at least one section.",
        )

    total_rows = 0
    whatsapp_sections = []

    for section in sections:
        section_title = section.get("title")
        rows_config = section.get("rows", [])

        if not section_title:
            raise HTTPException(
                status_code=400,
                detail="Each list section must have a title.",
            )

        if not rows_config:
            raise HTTPException(
                status_code=400,
                detail=f"List section '{section_title}' must have at least one row.",
            )

        whatsapp_rows = []

        for row in rows_config:
            row_id = row.get("id")
            row_label = row.get("label")
            row_description = row.get("description")

            if not row_id or not row_label:
                raise HTTPException(
                    status_code=400,
                    detail="Each list row must have id and label.",
                )

            whatsapp_row = {
                "id": row_id,
                "title": row_label,
            }

            if row_description:
                whatsapp_row["description"] = row_description

            whatsapp_rows.append(whatsapp_row)

        total_rows += len(whatsapp_rows)

        whatsapp_sections.append(
            {
                "title": section_title,
                "rows": whatsapp_rows,
            }
        )

    if total_rows > 10:
        raise HTTPException(
            status_code=400,
            detail="WhatsApp list message supports maximum 10 rows in total.",
        )

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": body_text,
            },
            "action": {
                "button": button_text,
                "sections": whatsapp_sections,
            },
        },
    }

    return _post_to_meta(
        phone_number_id, payload, access_token, "Failed to send WhatsApp list message."
    )


def mark_whatsapp_message_as_read(
    phone_number_id: str,
    meta_message_id: str,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Tells Meta we have read an incoming message, so the customer
    sees blue ticks. Callers must treat failures as non-fatal - a missed
    read receipt should never break message processing."""
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": meta_message_id,
    }

    return _post_to_meta(
        phone_number_id, payload, access_token, "Failed to mark WhatsApp message as read."
    )


def check_whatsapp_credentials(
    access_token: str | None = None,
    phone_number_id: str | None = None,
) -> dict[str, Any]:
    """Health check for an account's Meta credentials. Never raises for a
    bad token - the whole point is reporting 'your token is dead' nicely."""
    access_token = access_token or os.getenv("WHATSAPP_ACCESS_TOKEN")
    api_version = get_whatsapp_api_version()

    result: dict[str, Any] = {"token_ok": False}

    if not access_token:
        result["error"] = "No access token configured for this account."
        return result

    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(
            f"https://graph.facebook.com/{api_version}/me",
            headers=headers,
            timeout=15,
        )
        result["token_ok"] = response.status_code < 400
        result["me"] = response.json()
    except (requests.RequestException, ValueError) as error:
        result["error"] = str(error)
        return result

    if result["token_ok"] and phone_number_id:
        try:
            response = requests.get(
                f"https://graph.facebook.com/{api_version}/{phone_number_id}",
                params={"fields": "display_phone_number,verified_name,quality_rating"},
                headers=headers,
                timeout=15,
            )
            result["phone_ok"] = response.status_code < 400
            result["phone"] = response.json()
        except (requests.RequestException, ValueError) as error:
            result["phone_ok"] = False
            result["phone_error"] = str(error)

    return result


def subscribe_whatsapp_business_account(
    whatsapp_business_account_id: str,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Subscribes the WABA to this app so Meta actually delivers webhooks.
    The classic onboarding gotcha: without this call the dashboard shows
    messages but your server never receives them."""
    access_token = access_token or get_whatsapp_access_token()
    api_version = get_whatsapp_api_version()

    response = requests.post(
        f"https://graph.facebook.com/{api_version}/{whatsapp_business_account_id}/subscribed_apps",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )

    try:
        response_json = response.json()
    except ValueError:
        response_json = {"raw_response": response.text}

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Failed to subscribe WhatsApp Business Account to the app.",
                "meta_status_code": response.status_code,
                "meta_response": response_json,
            },
        )

    return response_json


# =====================================================================
# Message templates: sending + WABA-level management
# =====================================================================

def send_whatsapp_template_message(
    phone_number_id: str,
    to_phone: str,
    template_name: str,
    language: str,
    body_params: list[str] | None = None,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Send an approved template. body_params fill the BODY {{1}},{{2}}… in order."""
    components: list[dict[str, Any]] = []
    if body_params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": str(p)} for p in body_params],
        })

    template: dict[str, Any] = {
        "name": template_name,
        "language": {"code": language},
    }
    if components:
        template["components"] = components

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "template",
        "template": template,
    }
    return _post_to_meta(
        phone_number_id, payload, access_token, "Failed to send WhatsApp template message."
    )


def _graph_message_templates_url(whatsapp_business_account_id: str) -> str:
    api_version = get_whatsapp_api_version()
    return (
        f"https://graph.facebook.com/{api_version}/"
        f"{whatsapp_business_account_id}/message_templates"
    )


def _graph_request(method: str, url: str, access_token: str | None, error_message: str,
                   json_body: dict | None = None, params: dict | None = None) -> dict[str, Any]:
    """Shared request/parse/raise for the WABA message_templates endpoints."""
    access_token = access_token or get_whatsapp_access_token()
    response = requests.request(
        method,
        url,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=json_body,
        params=params,
        timeout=20,
    )
    try:
        response_json = response.json()
    except ValueError:
        response_json = {"raw_response": response.text}

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={
                "message": error_message,
                "meta_status_code": response.status_code,
                "meta_response": response_json,
            },
        )
    return response_json


def create_message_template(
    whatsapp_business_account_id: str,
    name: str,
    language: str,
    category: str,
    components: list[dict[str, Any]],
    access_token: str | None = None,
) -> dict[str, Any]:
    """Submit a template to Meta for approval. Returns Meta's response (id + status)."""
    return _graph_request(
        "POST",
        _graph_message_templates_url(whatsapp_business_account_id),
        access_token,
        "Failed to create WhatsApp message template.",
        json_body={
            "name": name,
            "language": language,
            "category": category,
            "components": components,
        },
    )


def list_message_templates(
    whatsapp_business_account_id: str,
    access_token: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Fetch all templates for a WABA (follows paging)."""
    url = _graph_message_templates_url(whatsapp_business_account_id)
    out: list[dict[str, Any]] = []
    params: dict | None = {
        "fields": "name,language,status,category,id,components,rejected_reason",
        "limit": limit,
    }
    while url:
        data = _graph_request(
            "GET", url, access_token, "Failed to list WhatsApp message templates.", params=params
        )
        out.extend(data.get("data", []))
        url = (data.get("paging", {}) or {}).get("next")
        params = None  # `next` already carries the query
    return out


def delete_message_template(
    whatsapp_business_account_id: str,
    name: str,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Delete a template (all languages) by name."""
    return _graph_request(
        "DELETE",
        _graph_message_templates_url(whatsapp_business_account_id),
        access_token,
        "Failed to delete WhatsApp message template.",
        params={"name": name},
    )
