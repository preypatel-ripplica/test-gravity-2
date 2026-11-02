from __future__ import annotations

"""Write Instagram/Facebook permalinks onto the weekly static-post card.

Social publish used to no-op here after the merge, so the post went live on
Instagram while "Where it went out" stayed empty.
"""

import uuid
from datetime import datetime, timezone

from backend.main.db import weekly_trackers_col
from backend.trackers.models import weekly_doc_id


def _new_dest_id() -> str:
    return f"dest-{uuid.uuid4().hex[:12]}"


def apply_social_permalinks_to_card(card: dict, post: dict) -> bool:
    """Fill destination URLs on a static-post card. Return True if the card changed."""
    urls = {
        "instagram": str(post.get("instagram_permalink") or "").strip(),
        "facebook": str(post.get("facebook_permalink") or "").strip(),
    }
    urls = {platform: url for platform, url in urls.items() if url}
    if not urls:
        return False

    destinations = [dict(row) for row in (card.get("destinations") or []) if isinstance(row, dict)]
    dest_ids = dict(card.get("destination_post_ids") or {})
    post_id = str(post.get("id") or "").strip()
    changed = False

    for platform, url in urls.items():
        idx = next(
            (i for i, row in enumerate(destinations) if str(row.get("platform") or "") == platform),
            -1,
        )
        if idx >= 0:
            if str(destinations[idx].get("url") or "").strip() != url:
                destinations[idx] = {**destinations[idx], "url": url}
                changed = True
        else:
            destinations.append({"id": _new_dest_id(), "platform": platform, "url": url})
            changed = True
        if post_id and dest_ids.get(platform) != post_id:
            dest_ids[platform] = post_id
            changed = True

    generated = [str(item) for item in (card.get("generated_post_ids") or []) if item]
    if post_id and post_id not in generated:
        generated.append(post_id)
        changed = True

    if not changed:
        return False

    card["destinations"] = destinations
    card["destination_post_ids"] = dest_ids
    card["generated_post_ids"] = generated
    card["stage"] = "posted"
    return True


def _card_matches_post(card: dict, post_id: str) -> bool:
    if not post_id or not isinstance(card, dict):
        return False
    if str(card.get("type") or "") != "static_post":
        return False
    generated = {str(item) for item in (card.get("generated_post_ids") or []) if item}
    dest_ids = {str(value) for value in (card.get("destination_post_ids") or {}).values() if value}
    return post_id in generated or post_id in dest_ids


def _iter_week_docs(client_id: str, year=None, month=None, week=None) -> list[dict]:
    if year and month and week:
        doc_id = weekly_doc_id(client_id, year, month, week)
        doc = weekly_trackers_col().find_one({"id": doc_id}) or weekly_trackers_col().find_one(
            {"project_id": client_id, "year": int(year), "month": int(month), "week": int(week)}
        )
        return [doc] if doc else []
    return list(weekly_trackers_col().find({"project_id": client_id}))


def _pick_cards(doc: dict, post_id: str, *, week_scoped: bool) -> list[dict]:
    cards = [card for card in (doc.get("cards") or []) if isinstance(card, dict)]
    matched = [card for card in cards if _card_matches_post(card, post_id)]
    if matched:
        return matched
    if week_scoped:
        statics = [card for card in cards if str(card.get("type") or "") == "static_post"]
        return statics[:1]
    return []


def sync_social_publish_to_tracker(client_id: str, post: dict | None = None, **kwargs) -> None:
    """Persist published IG/FB permalinks onto the matching weekly tracker card."""
    if post is None and kwargs.get("post"):
        post = kwargs["post"]
    if not client_id or not isinstance(post, dict):
        return
    if not (post.get("instagram_permalink") or post.get("facebook_permalink")):
        return

    year = kwargs.get("year")
    month = kwargs.get("month")
    week = kwargs.get("week")
    post_id = str(post.get("id") or "").strip()
    week_scoped = bool(year and month and week)
    updated = 0

    for doc in _iter_week_docs(client_id, year, month, week):
        if not doc:
            continue
        targets = _pick_cards(doc, post_id, week_scoped=week_scoped)
        changed = False
        for card in targets:
            if apply_social_permalinks_to_card(card, post):
                changed = True
        if not changed:
            continue
        weekly_trackers_col().update_one(
            {"_id": doc["_id"]} if doc.get("_id") else {"id": doc.get("id")},
            {
                "$set": {
                    "cards": doc.get("cards") or [],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "updated_by": "social.publish",
                }
            },
        )
        updated += 1
        if week_scoped:
            break

    if not updated:
        print(
            f"[tracker] no static-post card for social permalinks "
            f"client={client_id} post={post_id} week={year}/{month}/{week}",
            flush=True,
        )
