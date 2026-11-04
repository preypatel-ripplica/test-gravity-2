from __future__ import annotations

from calendar import monthrange


TYPE_LABELS = {
    "long_video": "Long video",
    "short": "Short",
    "static_post": "Static post",
    "blog": "Blog",
    "paid_ads": "Paid ads",
}

STAGE_LABELS = {
    "planned": "Planned",
    "script_generated": "Script generated",
    "yt_metadata_generated": "Metadata generated",
    "audio_generated": "Audio received",
    "video_edited": "Video edited",
    "shared_with_doctor": "Shared with doctor",
    "posted": "Posted",
    "published": "Published",
    "link_shared_with_doctor": "Link shared with doctor",
    "creatives_checked": "Creatives checked",
    "balance_checked": "Balance checked",
    "next_2_weeks_planned": "Next 2 weeks planned",
    "results_discussed": "Results discussed",
}


def weeks_in_month(year: int, month: int) -> list[int]:
    last = monthrange(year, month)[1]
    return [week for week, start in enumerate((1, 8, 15, 22), start=1) if start <= last]


def week_end_date(year: int, month: int, week: int) -> str:
    last = monthrange(year, month)[1]
    starts = (1, 8, 15, 22)
    if week < 1 or week > 4:
        return ""
    start = starts[week - 1]
    if start > last:
        return ""
    end = last if week == 4 else min(start + 6, last)
    return f"{int(year):04d}-{int(month):02d}-{int(end):02d}"


def card_links(card: dict) -> list[str]:
    urls = []
    for dest in card.get("destinations") or []:
        if not isinstance(dest, dict):
            continue
        url = str(dest.get("url") or "").strip()
        if url:
            urls.append(url)
    return urls


def flatten_weekly_rows(
    docs_by_week: dict[int, dict],
    year: int,
    month: int,
    allowed_types: list[str] | None = None,
    skip_weeks: set[int] | None = None,
) -> list[dict]:
    rows = []
    allowed = set(allowed_types) if allowed_types is not None else None
    skip = skip_weeks or set()
    type_order = ("long_video", "short", "static_post", "blog", "paid_ads")
    for week in weeks_in_month(year, month):
        if week in skip:
            continue
        doc = docs_by_week.get(week) or {}
        cards = sorted(
            [card for card in (doc.get("cards") or []) if isinstance(card, dict)],
            key=lambda row: (
                type_order.index(row.get("type"))
                if row.get("type") in type_order
                else len(type_order),
                int(row.get("sort_order") or 0),
            ),
        )
        for card in cards:
            card_type = str(card.get("type") or "").strip()
            if allowed is not None and card_type not in allowed:
                continue
            stage = str(card.get("stage") or "planned").strip()
            # Lazy import avoids circular import with tracker_settings.
            from backend.trackers.tracker_settings import normalize_marking

            marking = normalize_marking(card.get("marking"))
            rows.append(
                {
                    "week": week,
                    "card_id": card.get("id") or "",
                    "row_key": f"card:{card.get('id') or ''}",
                    "content_type": card_type,
                    "content_type_label": TYPE_LABELS.get(
                        card_type, card_type or "Unknown"
                    ),
                    "stage": stage,
                    "stage_label": STAGE_LABELS.get(
                        stage, stage.replace("_", " ").title()
                    ),
                    "marking": marking,
                    "links": card_links(card),
                }
            )
    return rows


def comments_map(comments: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in comments:
        if not isinstance(row, dict):
            continue
        key = str(row.get("row_key") or "").strip()
        if not key:
            continue
        out[key] = str(row.get("comment") or "")
    return out
