"""Which connected accounts need a manual reconnect."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.tg.database import (
    get_facebook_connection,
    get_instagram_connection,
    list_channels_meta,
)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _past(value: str | None) -> bool:
    parsed = _parse_dt(value)
    if not parsed:
        return False
    return parsed <= datetime.now(timezone.utc)


def connection_health(client_id: str) -> list[dict]:
    expired: list[dict] = []
    base = f"/clients/{client_id}/profile/connections"

    ig = get_instagram_connection(client_id)
    if ig and ig.get("access_token") and _past(ig.get("token_expires_at")):
        expired.append(
            {
                "platform": "instagram",
                "label": "Instagram",
                "message": "Instagram token expired.",
                "reconnect_path": f"{base}/instagram",
            }
        )

    fb = get_facebook_connection(client_id)
    if fb and (fb.get("access_token") or fb.get("page_access_token")) and _past(fb.get("token_expires_at")):
        expired.append(
            {
                "platform": "facebook",
                "label": "Facebook",
                "message": "Facebook token expired.",
                "reconnect_path": f"{base}/facebook",
            }
        )

    for channel in list_channels_meta(client_id):
        creds = channel.get("google_credentials") or {}
        if not creds:
            continue
        expiry = creds.get("expiry")
        has_refresh = bool(creds.get("refresh_token"))
        past = True if not expiry else _past(expiry)
        if past and not has_refresh:
            title = channel.get("title") or "YouTube"
            expired.append(
                {
                    "platform": "youtube",
                    "label": "YouTube",
                    "message": f"YouTube session expired for {title}.",
                    "reconnect_path": f"{base}/youtube",
                    "channel_id": channel.get("id"),
                }
            )
            break

    return expired
