"""Scheduled Google Business posts. Text comes from confirmed clinic facts.

Photos use the same OpenAI image model as the rest of the app.
"""

from __future__ import annotations

import base64
import json
import uuid

import httpx
from datetime import datetime, timedelta, timezone

from backend.tg.config import settings
from backend.tg.services.gbp_api import (
    GbpApiError,
    build_local_post_body,
    create_local_post,
    fetch_search_keywords,
    get_location,
    list_local_posts,
)
from backend.tg.services.gbp_optimize import classify_keyword, keyword_month_window, locality_of, service_names

FREQUENCIES = {"off", "daily", "weekdays", "once_a_week", "twice_a_week"}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
IST = timezone(timedelta(hours=5, minutes=30))


def schedule_runs_today(schedule: dict, today: datetime) -> bool:
    freq = (schedule or {}).get("frequency")
    if freq in ("off", None, ""):
        return False
    day_name = today.strftime("%A")
    if freq == "daily":
        return True
    if freq == "weekdays" and today.weekday() < 5:
        return True
    if freq in ("once_a_week", "twice_a_week") and day_name in (schedule.get("selected_days") or []):
        return True
    return False


def should_run_schedule(schedule: dict, today: datetime) -> bool:
    if not schedule_runs_today(schedule, today):
        return False
    return (schedule or {}).get("last_run_on") != today.date().isoformat()


def normalize_schedule(payload: dict, *, previous: dict | None = None) -> dict:
    freq = (payload or {}).get("frequency") or "off"
    if freq not in FREQUENCIES:
        raise ValueError("Choose a post frequency.")
    days = [day for day in (payload.get("selected_days") or []) if day in WEEKDAYS]
    if freq == "once_a_week" and len(days) != 1:
        raise ValueError("Select exactly one day.")
    if freq == "twice_a_week" and len(days) != 2:
        raise ValueError("Select exactly two days.")
    if freq not in {"once_a_week", "twice_a_week"}:
        days = []
    try:
        count = int(payload.get("posts_per_day") or 1)
    except (TypeError, ValueError):
        count = 1
    count = min(10, max(1, count))
    prior = previous or {}
    return {
        "frequency": freq,
        "selected_days": days,
        "posts_per_day": count,
        "autopublish": bool(payload.get("autopublish")),
        "last_run_on": prior.get("last_run_on"),
    }


def public_schedule(schedule: dict | None) -> dict:
    raw = schedule or {}
    return {
        "frequency": raw.get("frequency") or "off",
        "selected_days": list(raw.get("selected_days") or []),
        "posts_per_day": raw.get("posts_per_day") or 1,
        "autopublish": bool(raw.get("autopublish")),
        "last_run_on": raw.get("last_run_on"),
    }


def build_post_prompt(*, services: list[str], description: str, keyword_themes: list[dict], recent_texts: list[str], count: int) -> str:
    themes = []
    for item in keyword_themes or []:
        keyword = (item.get("keyword") or "").strip()
        theme = item.get("theme") or ""
        if keyword:
            themes.append(f"{keyword} ({theme})")
    recent = [text.strip() for text in recent_texts or [] if text and text.strip()]
    return "\n".join(
        [
            "Write Google Business Profile updates for this clinic.",
            f"Write {max(1, count)} different posts.",
            "Use only the confirmed services, the description, and the keyword themes below.",
            "Do not invent a treatment, event, offer, coupon, or staff member.",
            "Do not repeat a recent post.",
            "Each post is a short useful update under 500 characters.",
            "Reply as JSON: {\"posts\": [\"...\"]}.",
            "",
            "Confirmed services:",
            "\n".join(f"- {name}" for name in services) or "- None listed",
            "",
            "Description:",
            description.strip() or "None",
            "",
            "Keyword themes:",
            "\n".join(f"- {line}" for line in themes) or "- None",
            "",
            "Recent post text:",
            "\n".join(f"- {text}" for text in recent[:8]) or "- None",
        ]
    )


def parse_post_texts(raw: str, count: int) -> list[str]:
    text = (raw or "").strip()
    data = {}
    if text:
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    data = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    data = {}
    posts = data.get("posts") if isinstance(data, dict) else None
    cleaned = []
    for item in posts or []:
        line = str(item or "").strip()
        if line:
            cleaned.append(line[:500])
        if len(cleaned) >= count:
            break
    return cleaned


def fallback_posts(*, services: list[str], description: str, count: int) -> list[str]:
    focus = ", ".join(services[:3]) or "the services listed on our profile"
    summary = description.strip()[:180]
    first = f"Our clinic provides {focus}."
    if summary:
        first = f"{first} {summary}"
    posts = [first[:500]]
    if count > 1 and services:
        posts.append(f"Patients can ask us about {services[0]}. Call or use the appointment link on our profile."[:500])
    return posts[:count]


def _chat_posts(prompt: str, count: int) -> list[str]:
    if not (settings.OPENAI_API_KEY or "").strip():
        return []
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            reasoning_effort=(settings.OPENAI_REASONING_EFFORT or "medium").strip() or "medium",
            messages=[
                {"role": "system", "content": "You reply with JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        return parse_post_texts(response.choices[0].message.content or "", count)
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] post draft text failed: {exc}", flush=True)
        return []


def absolute_public_url(url: str | None) -> str | None:
    """Store a full https URL. A bucket path is expanded to the public GCS link."""
    cleaned = (url or "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned
    from backend.tg.config import settings

    bucket = (settings.GCS_BUCKET_NAME or "").strip().strip("/")
    return f"https://storage.googleapis.com/{bucket}/{cleaned.lstrip('/')}"


def image_prompt(summary: str) -> str:
    return (
        "Create a square photo-style image for a clinic Google Business post. "
        "No fake staff names, no before-and-after photos, and no medical procedure. "
        "Bright, calm, and appropriate for a clinic. "
        f"The image should match this post: {summary}"
    )


def _reference_files(urls: list[str]) -> list[tuple]:
    files = []
    for index, url in enumerate(urls or []):
        if not url or not str(url).startswith("http"):
            continue
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
        except Exception:  # noqa: BLE001
            continue
        content_type = (response.headers.get("content-type") or "image/jpeg").split(";")[0]
        if not content_type.startswith("image/") or len(response.content) < 500:
            continue
        ext = ".png" if "png" in content_type else ".jpg"
        files.append(("image[]", (f"ref-{index}{ext}", response.content, content_type)))
    return files


def generate_post_image(summary: str, client_id: str = "shared", references: list[str] | None = None) -> tuple[str | None, str]:
    """Return (public URL, error). A failed image does not discard the text."""
    if not (settings.OPENAI_API_KEY or "").strip():
        return None, "Image generation needs an OpenAI API key."
    try:
        files = _reference_files(references or [])
        if files:
            data = {
                "model": settings.OPENAI_IMAGE_MODEL,
                "prompt": (
                    "Use the reference photos as this clinic's real look. "
                    "Create a new square photo for a Google Business post. "
                    "Do not copy words off the reference photos. "
                    f"The post says: {summary}"
                ),
                "size": "1024x1024",
                "quality": "medium",
                "n": "1",
                "output_format": "png",
            }
            with httpx.Client(timeout=180.0) as http_client:
                edited = http_client.post(
                    "https://api.openai.com/v1/images/edits",
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                    data=data,
                    files=files,
                )
                edited.raise_for_status()
                payload = edited.json()
            image_row = (payload.get("data") or [{}])[0]
            if image_row.get("b64_json"):
                image_bytes = base64.b64decode(image_row["b64_json"])
            elif image_row.get("url"):
                with httpx.Client(timeout=60.0, follow_redirects=True) as http_client:
                    downloaded = http_client.get(image_row["url"])
                    downloaded.raise_for_status()
                    image_bytes = downloaded.content
            else:
                return None, "The image model did not return a photo."
        else:
            from openai import OpenAI

            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            response = client.images.generate(
                model=settings.OPENAI_IMAGE_MODEL,
                prompt=image_prompt(summary),
                size="1024x1024",
                quality="medium",
                n=1,
            )
            image_data = response.data[0]
            if getattr(image_data, "b64_json", None):
                image_bytes = base64.b64decode(image_data.b64_json)
            elif getattr(image_data, "url", None):
                with httpx.Client(timeout=60.0, follow_redirects=True) as http_client:
                    downloaded = http_client.get(image_data.url)
                    downloaded.raise_for_status()
                    image_bytes = downloaded.content
            else:
                return None, "The image model did not return a photo."
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] post image failed: {exc}", flush=True)
        return None, "The post photo could not be created."
    try:
        from backend.tg.services.gcs_storage import upload_bytes

        url = absolute_public_url(upload_bytes(f"gbp/{client_id}", f"{uuid.uuid4().hex}.png", image_bytes, "image/png"))
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] post image upload failed: {exc}", flush=True)
        return None, "The post photo could not be stored."
    return url, ""


def _theme_rows(keywords: list[dict], business_name: str, locality: str) -> list[dict]:
    rows = []
    for item in keywords or []:
        keyword = (item.get("keyword") or "").strip()
        if not keyword:
            continue
        rows.append({"keyword": keyword, "theme": classify_keyword(keyword, business_name, locality)})
    return rows


def recent_post_text(posts: list[dict]) -> list[str]:
    texts = []
    for post in posts or []:
        summary = (post.get("summary") or "").strip()
        if summary:
            texts.append(summary)
    return texts


def compose_drafts(
    client_id: str,
    location_id: str,
    summaries: list[str],
    references: list[str] | None = None,
    *,
    topic_type: str = "STANDARD",
    event_title: str = "",
    event_start: str = "",
    event_end: str = "",
    coupon_code: str = "",
) -> list[dict]:
    from backend.tg.database import save_gbp_post_draft

    kind = (topic_type or "STANDARD").upper()
    if kind not in {"STANDARD", "EVENT", "OFFER", "ALERT"}:
        kind = "STANDARD"
    saved = []
    now = datetime.now(timezone.utc).isoformat()
    for summary in summaries:
        url, error = generate_post_image(summary, client_id, references)
        url = absolute_public_url(url)
        draft_id = f"{client_id}:{location_id}:{uuid.uuid4().hex}"
        saved.append(
            save_gbp_post_draft(
                draft_id,
                {
                    "client_id": client_id,
                    "location_id": location_id,
                    "summary": summary,
                    "source_url": url,
                    "image_error": error,
                    "status": "pending",
                    "topic_type": kind,
                    "event_title": event_title or "",
                    "event_start": event_start or "",
                    "event_end": event_end or "",
                    "coupon_code": coupon_code or "",
                    "created_at": now,
                    "updated_at": now,
                },
            )
        )
    return saved


def generate_location_drafts(
    client_id: str,
    location: dict,
    creds,
    count: int,
    references: list[str] | None = None,
    *,
    topic_type: str = "STANDARD",
    event_title: str = "",
    event_start: str = "",
    event_end: str = "",
    coupon_code: str = "",
) -> list[dict]:
    profile = location.get("profile") if isinstance(location.get("profile"), dict) else None
    if profile is None or "serviceItems" not in profile:
        try:
            profile = get_location(creds, location.get("location_name") or location["location_id"])
        except GbpApiError:
            profile = profile or {}
    services = service_names(profile or {})
    description = ((profile or {}).get("profile") or {}).get("description") or ""
    start, end = keyword_month_window(datetime.now(IST).date())
    try:
        keywords = fetch_search_keywords(creds, location["location_id"], start, end)
    except GbpApiError:
        keywords = []
    try:
        posts = list_local_posts(creds, location.get("account_id") or "", location["location_id"])
    except GbpApiError:
        posts = []
    count = min(10, max(1, int(count or 1)))
    prompt = build_post_prompt(
        services=services,
        description=description,
        keyword_themes=_theme_rows(keywords, (profile or {}).get("title") or location.get("title") or "", locality_of(profile or {})),
        recent_texts=recent_post_text(posts),
        count=count,
    )
    summaries = _chat_posts(prompt, count)
    if not summaries:
        summaries = fallback_posts(services=services, description=description, count=count)
    return compose_drafts(
        client_id,
        location["location_id"],
        summaries,
        references,
        topic_type=topic_type,
        event_title=event_title,
        event_start=event_start,
        event_end=event_end,
        coupon_code=coupon_code,
    )


def publish_gbp_draft(client_id: str, location: dict, creds, draft: dict, summary: str | None = None) -> dict:
    from backend.tg.database import save_gbp_post_draft

    text = (summary if summary is not None else draft.get("summary") or "").strip()
    if not text:
        raise ValueError("Post text is required.")
    source = absolute_public_url(draft.get("source_url"))
    body = build_local_post_body(
        summary=text,
        topic_type=draft.get("topic_type") or "STANDARD",
        source_url=source,
        event_title=draft.get("event_title") or None,
        event_start=draft.get("event_start") or None,
        event_end=draft.get("event_end") or None,
        coupon_code=draft.get("coupon_code") or None,
    )
    created = create_local_post(creds, location["account_id"], location["location_id"], body)
    now = datetime.now(timezone.utc).isoformat()
    return save_gbp_post_draft(
        draft["id"],
        {**draft, "summary": text, "status": "published", "published_at": now, "updated_at": now, "google_post": created.get("name")},
    )


def _drafts_for_location(client_id: str, location_id: str, status: str) -> list[dict]:
    from backend.tg.database import list_gbp_post_drafts

    rows = [
        draft
        for draft in list_gbp_post_drafts(client_id, location_id)
        if draft.get("status") == status
    ]
    if status == "queued":
        rows.sort(key=lambda draft: (draft.get("queue_order") if draft.get("queue_order") is not None else 10**9, draft.get("created_at") or ""))
    else:
        rows.sort(key=lambda draft: draft.get("created_at") or "", reverse=True)
    return rows


def enqueue_gbp_draft(client_id: str, draft: dict, summary: str | None = None) -> dict:
    from backend.tg.database import save_gbp_post_draft

    if draft.get("status") == "published":
        raise ValueError("This post is already on Google.")
    queued = _drafts_for_location(client_id, draft.get("location_id") or "", "queued")
    order = max([int(item.get("queue_order") or 0) for item in queued] + [0]) + 1
    text = (summary if summary is not None else draft.get("summary") or "").strip()
    now = datetime.now(timezone.utc).isoformat()
    return save_gbp_post_draft(
        draft["id"],
        {**draft, "summary": text or draft.get("summary") or "", "status": "queued", "queue_order": order, "updated_at": now},
    )


def dequeue_gbp_draft(draft: dict) -> dict:
    from backend.tg.database import save_gbp_post_draft

    now = datetime.now(timezone.utc).isoformat()
    return save_gbp_post_draft(
        draft["id"],
        {**draft, "status": "pending", "queue_order": None, "updated_at": now},
    )


def reorder_gbp_queue(client_id: str, location_id: str, draft_ids: list[str]) -> list[dict]:
    from backend.tg.database import get_gbp_post_draft, save_gbp_post_draft

    saved = []
    now = datetime.now(timezone.utc).isoformat()
    for index, draft_id in enumerate(draft_ids, start=1):
        draft = get_gbp_post_draft(draft_id)
        if not draft or draft.get("client_id") != client_id or draft.get("location_id") != location_id:
            continue
        if draft.get("status") != "queued":
            continue
        saved.append(save_gbp_post_draft(draft_id, {**draft, "queue_order": index, "updated_at": now}))
    return saved


def posts_due_for_publish(client_id: str, location_id: str, schedule: dict) -> list[dict]:
    """Queue first, like Instagram. Autopublish only fills the rest from the newest generated drafts."""
    count = min(10, max(1, int(schedule.get("posts_per_day") or 1)))
    chosen = _drafts_for_location(client_id, location_id, "queued")[:count]
    if len(chosen) < count and schedule.get("autopublish"):
        chosen.extend(_drafts_for_location(client_id, location_id, "pending")[: count - len(chosen)])
    return chosen


def run_scheduled_posts(today: datetime | None = None) -> dict:
    from backend.tg.database import list_gbp_connections, list_gbp_locations, upsert_gbp_location
    from backend.tg.gbp_oauth import ensure_gbp_credentials

    moment = today or datetime.now(IST)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=IST)
    processed = []
    for connection in list_gbp_connections():
        client_id = connection.get("client_id")
        if not client_id or connection.get("status") != "connected":
            continue
        try:
            creds = ensure_gbp_credentials(client_id)
        except Exception as exc:  # noqa: BLE001
            processed.append({"client_id": client_id, "error": str(exc)})
            continue
        for location in list_gbp_locations(client_id):
            if not location.get("selected"):
                continue
            schedule = dict(location.get("post_schedule") or {})
            if not should_run_schedule(schedule, moment):
                continue
            location_id = location.get("location_id")
            try:
                due = posts_due_for_publish(client_id, location_id, schedule)
                publish_error = ""
                published = 0
                for draft in due:
                    try:
                        publish_gbp_draft(client_id, location, creds, draft)
                        published += 1
                    except Exception as exc:  # noqa: BLE001
                        publish_error = str(exc)
                schedule["last_run_on"] = moment.date().isoformat()
                upsert_gbp_location(client_id, location_id, {**location, "post_schedule": schedule})
                processed.append(
                    {
                        "client_id": client_id,
                        "location_id": location_id,
                        "drafts": published,
                        "queued": sum(1 for item in due if item.get("status") == "queued"),
                        "autopublish": bool(schedule.get("autopublish")),
                        "publish_error": publish_error,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                processed.append({"client_id": client_id, "location_id": location_id, "error": str(exc)})
    return {"processed": processed}
