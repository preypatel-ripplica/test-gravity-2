"""TG `app.clients` ported onto Beacon (client_id == project_id, username == email).

Business logic is unchanged from test-gravity; all persistence goes through
`backend.tg.database`. AI/trend/content-plan services are imported lazily from
`backend.tg.services.*` (copied separately), so this module imports cleanly before
those services exist.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status

from .database import (
    delete_channel_owned,
    delete_client_owned,
    fetch_channel,
    fetch_client_bundle,
    fetch_client_doc,
    fetch_topics,
    fetch_user,
    fetch_video_titles,
    heal_user_pointers,
    insert_client,
    list_channel_ids,
    list_channel_summaries,
    list_channels_meta,
    list_clients_for_user,
    replace_content_plan,
    sync_tracker_scripts_for_item,
    replace_topics,
    sync_client_channels,
    update_client_fields,
    update_user_fields,
)


def normalize_topics(raw) -> list[dict]:
    """TG services.topics.normalize_topics (uses the real one when available)."""
    try:
        from .services.topics import normalize_topics as _normalize
    except ImportError:
        return _normalize_topics_fallback(raw)
    return _normalize(raw)


def _normalize_topics_fallback(raw) -> list[dict]:
    """Minimal stand-in: dedupe by text, keep id/weight/source and trend fields."""
    if not raw:
        return []
    items = raw
    if isinstance(raw, dict):
        items = []
        for weight in ("high", "medium", "low"):
            for t in raw.get(weight, []) or []:
                if isinstance(t, str):
                    items.append({"text": t, "weight": weight, "source": "auto"})
                elif isinstance(t, dict):
                    items.append({**t, "weight": t.get("weight") or weight})
    out: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or item.get("title") or "").strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        topic = {**item}
        topic["text"] = text
        topic["id"] = str(item.get("id") or f"topic:{uuid.uuid4()}")
        topic["weight"] = item.get("weight") or "medium"
        topic["source"] = item.get("source") or "manual"
        out.append(topic)
    return out


def _new_id() -> str:
    return f"project:{uuid.uuid4()}"  # Beacon id style (projects.id)


def _channel_record(info: dict, google_credentials: dict, existing: dict | None = None) -> dict:
    prev = existing or {}
    return {
        **info,
        "google_credentials": google_credentials,
        "videos": prev.get("videos", []),
        "language": info.get("language") or prev.get("language"),
    }


def migrate_user_if_needed(db: dict | None = None, username: str | None = None) -> bool:
    """Heal stale active_* pointers via collection lookups (no nested rewrite)."""
    uname = username
    if uname is None and isinstance(db, dict):
        # legacy callers passed nested db; heal all usernames present
        for key in db.get("users") or {}:
            heal_user_pointers(key)
        return False
    if uname:
        heal_user_pointers(uname)
    return False


def get_user_clients(user: dict) -> list[dict]:
    return user.get("clients", [])


def get_client_channels(user: dict, client_id: str | None = None) -> list[dict]:
    client = resolve_client(user, client_id, required=False)
    if not client:
        return []
    return client.get("channels", [])


def resolve_client(
    user: dict,
    client_id: str | None = None,
    *,
    required: bool = True,
) -> dict | None:
    clients = get_user_clients(user)
    if not clients:
        if required:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No clients yet. Create a client first.",
            )
        return None

    target_id = client_id or user.get("active_client_id")
    if not target_id:
        if required:
            target_id = clients[0]["id"]
            user["active_client_id"] = target_id
        else:
            return None

    for client in clients:
        if client["id"] == target_id:
            return client

    # Stale active_client_id: fall back instead of breaking auth.me / listings
    if client_id is None or target_id == user.get("active_client_id"):
        user["active_client_id"] = clients[0]["id"]
        return clients[0]

    if not required:
        return None

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Client '{target_id}' not found.",
    )


def resolve_channel(
    user: dict,
    client_id: str | None = None,
    channel_id: str | None = None,
) -> tuple[dict, dict]:
    client = resolve_client(user, client_id)
    channels = client.get("channels", [])
    if not channels:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No channels linked to this client. Use Link Channel to connect YouTube.",
        )

    target_id = channel_id or user.get("active_channel_id")
    if target_id:
        for channel in channels:
            if channel["id"] == target_id:
                user["active_client_id"] = client["id"]
                user["active_channel_id"] = target_id
                return client, channel

    first = channels[0]
    user["active_client_id"] = client["id"]
    user["active_channel_id"] = first["id"]
    return client, first


def create_client(username: str, name: str) -> dict:
    if not fetch_user(username):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    client = {
        "id": _new_id(),
        "name": name.strip(),
        "website_url": None,
        "specialty": None,
        "designation": None,
        "description": None,
        "reference_youtube_channel": None,
        "topics": [],
        "channels": [],
    }
    insert_client(username, client)
    return client


def update_client(
    username: str,
    client_id: str,
    *,
    name: str | None = None,
    website_url: str | None = None,
    specialty: str | None = None,
    designation: str | None = None,
    description: str | None = None,
    reference_youtube_channel: str | None = None,
    ai_videos_started_from: str | None = None,
    onboarding_date: str | None = None,
    tracker_start_year: int | None = None,
    tracker_start_month: int | None = None,
    tracker_start_week: int | None = None,
    tracker_deliverables: list | None = None,
    is_active: bool | None = None,
    topics: list | None = None,
) -> dict:
    from backend.main.models import ProjectStatus
    from backend.trackers.tracker_settings import (
        DELIVERABLES_PERIOD_MONTH,
        current_week_tuple,
        merge_week_slot_plan,
        monthly_counts_changed,
        normalize_deliverables,
        parse_onboarding_date,
        record_deliverable_change,
        remaining_week_slot_plan,
        tracker_start_tuple,
    )

    existing = fetch_client_doc(client_id, username=username)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{client_id}' not found.",
        )

    fields: dict = {}
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Client name cannot be empty.",
            )
        fields["name"] = cleaned
    if website_url is not None:
        fields["website_url"] = website_url.strip() or None
    if specialty is not None:
        fields["specialty"] = specialty.strip() or None
    if designation is not None:
        fields["designation"] = designation.strip() or None
    if description is not None:
        fields["description"] = description.strip() or None
    if reference_youtube_channel is not None:
        fields["reference_youtube_channel"] = reference_youtube_channel.strip() or None
    if ai_videos_started_from is not None:
        cleaned_ai = ai_videos_started_from.strip() or None
        if cleaned_ai:
            import re

            if not re.fullmatch(r"\d{4}-\d{2}", cleaned_ai):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="ai_videos_started_from must be YYYY-MM.",
                )
        fields["ai_videos_started_from"] = cleaned_ai
    if onboarding_date is not None:
        try:
            fields["onboarding_date"] = parse_onboarding_date(onboarding_date)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if tracker_start_year is not None or tracker_start_month is not None or tracker_start_week is not None:
        if tracker_start_year is None or tracker_start_month is None or tracker_start_week is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tracker start needs year, month, and week.",
            )
        probe = {
            "tracker_start_year": int(tracker_start_year),
            "tracker_start_month": int(tracker_start_month),
            "tracker_start_week": int(tracker_start_week),
        }
        if tracker_start_tuple(probe) is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tracker start week must be 1-4 in a valid month.",
            )
        fields.update(probe)
    sync_deliverables = False
    if tracker_deliverables is not None:
        new_slots = normalize_deliverables(tracker_deliverables)
        fields["tracker_deliverables"] = new_slots
        fields["tracker_deliverables_period"] = DELIVERABLES_PERIOD_MONTH
        fields["tracker_deliverable_history"] = record_deliverable_change(existing, new_slots)
        if monthly_counts_changed(existing, new_slots):
            fields["tracker_week_slot_plan"] = merge_week_slot_plan(
                existing.get("tracker_week_slot_plan"),
                remaining_week_slot_plan(existing, new_slots),
            )
            sync_deliverables = True
    if is_active is not None:
        fields["status"] = (
            ProjectStatus.ACTIVE.value if is_active else ProjectStatus.ARCHIVED.value
        )

    client = update_client_fields(client_id, username, fields) or {}
    if sync_deliverables:
        from backend.trackers.crudl import sync_weeks_from_deliverable_change

        start = tracker_start_tuple(client)
        from_week = current_week_tuple()
        if start and from_week < start:
            from_week = start
        sync_weeks_from_deliverable_change(client_id, username, from_week)
    if topics is not None:
        normalized = normalize_topics(topics)
        replace_topics(client_id, normalized)
        client["topics"] = normalized
    else:
        client["topics"] = fetch_topics(client_id)
    return client


def collect_linked_video_titles(client: dict) -> list[str]:
    cid = client.get("id")
    if cid:
        return fetch_video_titles(cid)
    titles: list[str] = []
    for channel in client.get("channels", []) or []:
        for video in channel.get("videos", []) or []:
            title = (video.get("title") or "").strip()
            if title:
                titles.append(title)
    return titles


def collect_client_video_titles(
    client: dict,
    *,
    fetch_reference: bool = True,
) -> list[str]:
    """Linked OAuth library titles + optional public reference-channel RSS titles."""
    from .services.youtube_public import fetch_public_channel_titles, merge_title_lists

    linked = collect_linked_video_titles(client)
    if not fetch_reference:
        return linked

    ref = (client.get("reference_youtube_channel") or "").strip()
    if not ref:
        return linked

    public = fetch_public_channel_titles(ref, limit=30)
    # Soft-fail: keep linked titles even if reference fetch fails
    return merge_title_lists(linked, public.get("titles") or [], limit=60)


def collect_client_channel_titles(client: dict) -> list[str]:
    cid = client.get("id")
    if cid:
        titles = [
            (c.get("title") or "").strip()
            for c in list_channel_summaries(cid)
            if (c.get("title") or "").strip()
        ]
    else:
        titles = []
        for channel in client.get("channels", []) or []:
            title = (channel.get("title") or "").strip()
            if title:
                titles.append(title)
    ref = (client.get("reference_youtube_channel") or "").strip()
    if ref and ref not in titles:
        titles.append(ref)
    return titles


def refresh_client_topics(
    username: str,
    client_id: str,
    *,
    website_url: str | None = None,
    specialty: str | None = None,
    description: str | None = None,
    reference_youtube_channel: str | None = None,
    topics: list | None = None,
    user_prompt: str | None = None,
) -> dict:
    """Regenerate auto topics; preserve manually added topics."""
    from .services.topics import generate_auto_topics, merge_topics
    from .services.youtube_public import fetch_public_channel_titles, merge_title_lists

    print(f"[topics] refresh START client_id={client_id}", flush=True)

    client = fetch_client_doc(client_id, username=username)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{client_id}' not found.",
        )

    # Persist profile fields immediately so they survive even if AI generation fails
    fields: dict = {}
    if website_url is not None:
        fields["website_url"] = website_url.strip() or None
    if specialty is not None:
        fields["specialty"] = specialty.strip() or None
    if description is not None:
        fields["description"] = description.strip() or None
    if reference_youtube_channel is not None:
        fields["reference_youtube_channel"] = reference_youtube_channel.strip() or None
    if fields:
        client = update_client_fields(client_id, username, fields) or client
    client["topics"] = fetch_topics(client_id)
    print(
        f"[topics] profile saved website={client.get('website_url')!r} "
        f"specialty={client.get('specialty')!r} "
        f"ref_yt={client.get('reference_youtube_channel')!r}",
        flush=True,
    )

    existing = normalize_topics(topics if topics is not None else client.get("topics"))
    manual = [t for t in existing if t.get("source") == "manual"]
    existing_auto = [t for t in existing if t.get("source") != "manual"]

    linked = fetch_video_titles(client_id)
    ref_meta = None
    ref_titles: list[str] = []
    ref = (client.get("reference_youtube_channel") or "").strip()
    if ref:
        print(f"[topics] fetching public YT titles for {ref!r} …", flush=True)
        ref_meta = fetch_public_channel_titles(ref, limit=30)
        ref_titles = list(ref_meta.get("titles") or [])
        print(
            f"[topics] public YT done channel_id={ref_meta.get('channel_id')} "
            f"titles={ref_meta.get('title_count')} error={ref_meta.get('error')}",
            flush=True,
        )
    else:
        print("[topics] no reference YT channel — skip public fetch", flush=True)

    video_titles = merge_title_lists(linked, ref_titles, limit=60)
    channel_titles = [c.get("title") or "" for c in list_channel_summaries(client_id)]
    print(
        f"[topics] title signals linked={len(linked)} ref={len(ref_titles)} "
        f"merged={len(video_titles)} manuals={len(manual)} existing_auto={len(existing_auto)} "
        f"user_prompt={bool(user_prompt)}",
        flush=True,
    )

    print("[topics] generate_auto_topics …", flush=True)
    auto, scrape_meta = generate_auto_topics(
        client_id=client.get("id"),
        client_name=client.get("name"),
        specialty=client.get("specialty"),
        description=client.get("description"),
        website_url=client.get("website_url"),
        video_titles=video_titles,
        channel_titles=channel_titles,
        manual_topics=manual,
        existing_auto_topics=existing_auto,
        user_prompt=user_prompt,
    )
    print(
        f"[topics] generate_auto_topics DONE auto={len(auto)} "
        f"generator={scrape_meta.get('generator')} "
        f"stages={scrape_meta.get('openai_stages')} "
        f"error={scrape_meta.get('openai_error')}",
        flush=True,
    )
    if ref_meta is not None:
        scrape_meta["reference_youtube"] = {
            "channel_id": ref_meta.get("channel_id"),
            "title_count": ref_meta.get("title_count") or 0,
            "error": ref_meta.get("error"),
        }

    # Re-read topics by client_id before final write (concurrent /client.update safe).
    client = fetch_client_doc(client_id, username=username) or client
    existing_now = normalize_topics(fetch_topics(client_id))
    manuals_now = [t for t in existing_now if t.get("source") == "manual"]
    client["topics"] = merge_topics(manuals_now, auto, previous=existing_now)
    print(
        f"[topics] merge done total={len(client['topics'])} "
        f"(manual={len(manuals_now)} auto={len(auto)})",
        flush=True,
    )

    # Prefer AI/scrape specialty when the client still has none
    detected = scrape_meta.get("specialty")
    if detected and not client.get("specialty"):
        client = update_client_fields(client_id, username, {"specialty": detected}) or client
        print(f"[topics] specialty set from AI: {detected!r}", flush=True)

    replace_topics(client_id, client["topics"])
    print(
        f"[topics] refresh SAVED to db topics={len(client['topics'])}",
        flush=True,
    )
    return {"client": client, "scrape_meta": scrape_meta}


async def analyze_client_trends(
    username: str,
    client_id: str,
    *,
    force: bool = False,
) -> dict:
    """Score client topics with Google Trends (India web + YouTube)."""
    from .services.trends import analyze_topics_trends

    print(
        f"[trends:client] analyze start user={username!r} client_id={client_id!r} force={force}",
        flush=True,
    )
    client = fetch_client_doc(client_id, username=username)
    if not client:
        print(f"[trends:client] ERROR client not found: {client_id!r}", flush=True)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{client_id}' not found.",
        )

    topics = normalize_topics(fetch_topics(client_id))
    print(
        f"[trends:client] client={client.get('name')!r} topics={len(topics)}",
        flush=True,
    )
    if not topics:
        print("[trends:client] ERROR no topics to analyze", flush=True)
        raise ValueError("No topics to analyze. Add or refresh topics first.")

    try:
        updated, summary = await analyze_topics_trends(topics, force=force)
    except Exception as exc:
        print(f"[trends:client] ERROR analyze failed: {exc}", flush=True)
        raise

    client["topics"] = updated
    replace_topics(client_id, updated)
    print(
        f"[trends:client] saved scored={summary.get('scored')} "
        f"tasks={summary.get('api_tasks')} cost=${float(summary.get('total_cost') or 0):.4f} "
        f"error={summary.get('error')!r}",
        flush=True,
    )
    return {"client": client, "summary": summary}


def save_client_recommendations(username: str, client_id: str) -> dict:
    """Compute combined recommendation scores and persist them on each topic."""
    from .services.topics import apply_recommendation_scores

    client = fetch_client_doc(client_id, username=username)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{client_id}' not found.",
        )
    topics = normalize_topics(fetch_topics(client_id))
    if not topics:
        raise ValueError("No topics to score. Add or refresh topics first.")

    updated = apply_recommendation_scores(topics)
    client["topics"] = updated
    replace_topics(client_id, updated)

    primary = sum(1 for t in updated if float(t.get("recommendation_score") or 0) >= 50)
    secondary = len(updated) - primary
    saved_at = updated[0].get("recommendation_saved_at") if updated else None
    return {
        "client": client,
        "primary_count": primary,
        "secondary_count": secondary,
        "saved_at": saved_at,
        "threshold": 50.0,
    }


def _require_client_bundle(
    username: str,
    client_id: str,
    *,
    with_videos: bool = True,
    domain=None,
) -> dict:
    from backend.main.models import Domain
    from backend.tg.database import require_domain_for_user

    # Content-plan / video client ops require the videos domain.
    require_domain_for_user(
        username, client_id, domain if domain is not None else Domain.VIDEOS
    )
    heal_user_pointers(username)
    client = fetch_client_bundle(
        client_id,
        username,
        with_videos=with_videos,
        with_topics=True,
        with_plan=True,
    )
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{client_id}' not found.",
        )
    return client


def run_client_content_plan(
    username: str,
    client_id: str,
    *,
    count: int = 5,
    force_remap: bool = False,
    user_prompt: str | None = None,
    regenerate: bool = False,
) -> dict:
    """Generate or regenerate next-topic content suggestions and persist on client."""
    from .services.content_plan import generate_content_plan

    client = _require_client_bundle(username, client_id, with_videos=True)
    suggestions = generate_content_plan(
        client,
        count=count,
        force_remap=force_remap,
        user_prompt=user_prompt,
        regenerate=regenerate,
    )
    replace_content_plan(client_id, client)
    return {"client": client, "suggestions": suggestions}


def map_client_content_plan(username: str, client_id: str, *, force: bool = True) -> dict:
    """1st call: map videos → keywords + Long/Short analysis only."""
    from .services.content_plan import map_content_plan_only

    client = _require_client_bundle(username, client_id, with_videos=True)
    suggestions = map_content_plan_only(client, force=force)
    replace_content_plan(client_id, client)
    return {"client": client, "suggestions": suggestions}


def get_client_content_plan(username: str, client_id: str) -> dict:
    client = _require_client_bundle(username, client_id, with_videos=False)
    suggestions = client.get("content_suggestions") or {
        "generated_at": None,
        "count": 0,
        "user_prompt": None,
        "items": [],
    }
    suggestions = {
        **suggestions,
        "coverage": suggestions.get("coverage")
        or {"total": 0, "mapped_to_keyword": 0, "out_of_keyword": 0},
        "keyword_analysis": suggestions.get("keyword_analysis") or [],
        "mapped_at": suggestions.get("mapped_at"),
    }
    return {"client": client, "suggestions": suggestions}


def _script_examples(*parts, extra=None) -> list[str]:
    out = []
    for part in list(parts) + list(extra or []):
        if part is None:
            continue
        text = str(part).strip()
        if text:
            out.append(text)
    return out


def run_client_content_scripts(
    username: str, 
    client_id: str,
    *,
    example1: str | None = None,
    example2: str | None = None,
) -> dict:
    """Generate spoken scripts for all content-plan titles and persist on client."""
    from .services.content_plan import generate_scripts_for_plan

    client = _require_client_bundle(username, client_id, with_videos=False)
    examples = _script_examples(example1, example2)
    if not examples:
        examples = _script_examples(extra=client.get("example_scripts"))
    suggestions = generate_scripts_for_plan(client, examples=examples)
    replace_content_plan(client_id, client)
    return {"client": client, "suggestions": suggestions}


def run_client_content_script_refine(
    username: str,
    client_id: str,
    *,
    item_id: str,
    user_prompt: str,
) -> dict:
    """Refine a single content-plan script with a user prompt; persist."""
    from .services.content_plan import refine_script_for_item

    client = _require_client_bundle(username, client_id, with_videos=False)
    suggestions = refine_script_for_item(
        client,
        item_id=item_id,
        user_prompt=user_prompt,
    )
    replace_content_plan(client_id, client)
    return {"client": client, "suggestions": suggestions}


def update_client_content_script(
    username: str,
    client_id: str,
    *,
    item_id: str,
    script: str,
) -> dict:
    """Overwrite one plan item's script (no AI) and sync linked tracker cards."""
    from .services.content_plan import _clean_script_text

    client = _require_client_bundle(username, client_id, with_videos=False)
    suggestions = client.get("content_suggestions") or {}
    items = suggestions.get("items") or []
    match = next((row for row in items if isinstance(row, dict) and row.get("id") == item_id), None)
    if not match:
        raise ValueError("Content plan item not found")
    cleaned = _clean_script_text(script or "")
    if not cleaned:
        raise ValueError("Script cannot be empty.")
    match["script"] = cleaned
    match["origin"] = "manual"
    client["content_suggestions"] = suggestions
    replace_content_plan(client_id, client)
    sync_tracker_scripts_for_item(client_id, item_id, cleaned)
    return {"client": client, "suggestions": suggestions}


def get_client_script_narration_text(
    username: str,
    client_id: str,
    *,
    item_id: str | None = None,
    combined: bool = False,
) -> str:
    """Resolve script text for TTS (one item or combined)."""
    client = _require_client_bundle(username, client_id, with_videos=False)
    items = [
        i
        for i in ((client.get("content_suggestions") or {}).get("items") or [])
        if isinstance(i, dict) and (i.get("script") or "").strip()
    ]
    if not items:
        raise ValueError("No scripts to narrate. Generate scripts first.")

    if combined or not (item_id or "").strip():
        parts = []
        for idx, row in enumerate(items, start=1):
            title = row.get("title_hinglish") or row.get("title_en") or row.get("topic_text") or f"Video {idx}"
            parts.append(f"Video {idx}. {title}.\n{row.get('script')}")
        return "\n\n".join(parts)

    target = (item_id or "").strip()
    match = next((r for r in items if (r.get("id") or "").strip() == target), None)
    if not match:
        raise ValueError("Script item not found.")
    return (match.get("script") or "").strip()



def persist_client_profile_fields(
    username: str,
    client_id: str,
    *,
    website_url: str | None = None,
    specialty: str | None = None,
    description: str | None = None,
    reference_youtube_channel: str | None = None,
) -> dict:
    """Save website / specialty / description / reference YT without touching topics."""
    if not fetch_client_doc(client_id, username=username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{client_id}' not found.",
        )

    fields: dict = {}
    if website_url is not None:
        fields["website_url"] = website_url.strip() or None
    if specialty is not None:
        fields["specialty"] = specialty.strip() or None
    if description is not None:
        fields["description"] = description.strip() or None
    if reference_youtube_channel is not None:
        fields["reference_youtube_channel"] = reference_youtube_channel.strip() or None

    client = update_client_fields(client_id, username, fields) or {}
    client["topics"] = fetch_topics(client_id)
    return client


def set_active_client(username: str, client_id: str) -> None:
    if not fetch_client_doc(client_id, username=username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{client_id}' not found.",
        )
    user = fetch_user(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    channel_ids = list_channel_ids(client_id)
    active_channel_id = user.get("active_channel_id")
    if channel_ids:
        if not active_channel_id or active_channel_id not in channel_ids:
            active_channel_id = channel_ids[0]
    else:
        active_channel_id = None
    update_user_fields(
        username,
        active_client_id=client_id,
        active_channel_id=active_channel_id,
    )


def find_client_id_for_channel(user: dict, channel_id: str) -> str:
    for client in get_user_clients(user):
        if any(c["id"] == channel_id for c in client.get("channels", [])):
            return client["id"]
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Channel '{channel_id}' not found.",
    )


def set_active_channel(username: str, client_id: str, channel_id: str) -> None:
    if not fetch_client_doc(client_id, username=username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{client_id}' not found.",
        )
    channel_ids = list_channel_ids(client_id)
    if channel_id not in channel_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel '{channel_id}' not found.",
        )
    update_user_fields(
        username,
        active_client_id=client_id,
        active_channel_id=channel_id,
    )


def link_channels_to_client(
    username: str,
    client_id: str,
    channel_infos: list[dict],
    google_credentials: dict,
) -> dict:
    if not fetch_client_doc(client_id, username=username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{client_id}' not found.",
        )

    existing_by_id = {c["id"]: c for c in list_channels_meta(client_id)}
    linked: list[dict] = []
    for info in channel_infos:
        prev = existing_by_id.get(info["id"])
        creds = google_credentials
        if prev and not creds.get("refresh_token"):
            prev_creds = prev.get("google_credentials") or {}
            if prev_creds.get("refresh_token"):
                creds = {**creds, "refresh_token": prev_creds["refresh_token"]}
        linked.append(_channel_record(info, creds, prev))

    new_ids = {c["id"] for c in linked}
    for old in existing_by_id.values():
        if old["id"] not in new_ids:
            linked.append(old)

    sync_client_channels(username, client_id, linked, drop_missing=False)
    update_user_fields(
        username,
        active_client_id=client_id,
        active_channel_id=linked[0]["id"] if linked else None,
    )
    return fetch_client_bundle(client_id, username, with_videos=False) or {
        "id": client_id,
        "channels": linked,
    }


def sync_client_channels_from_creds(
    username: str,
    client_id: str,
    channel_id: str,
    channel_infos: list[dict],
) -> dict:
    if not fetch_client_doc(client_id, username=username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{client_id}' not found.",
        )
    source = fetch_channel(channel_id, client_id=client_id, username=username)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel '{channel_id}' not found.",
        )
    creds = source.get("google_credentials")
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected channel has no linked Google credentials.",
        )

    existing_by_id = {c["id"]: c for c in list_channels_meta(client_id)}
    merged: list[dict] = []
    for info in channel_infos:
        prev = existing_by_id.get(info["id"], {})
        channel_creds = prev.get("google_credentials") or creds
        merged.append(_channel_record(info, channel_creds, prev))

    merged_ids = {m["id"] for m in merged}
    other = [c for c in existing_by_id.values() if c["id"] not in merged_ids]
    channels = merged + other

    sync_client_channels(username, client_id, channels, drop_missing=False)

    user = fetch_user(username) or {}
    keep_ids = {c["id"] for c in channels}
    if user.get("active_channel_id") not in keep_ids:
        update_user_fields(
            username,
            active_channel_id=channels[0]["id"] if channels else None,
        )

    return fetch_client_bundle(client_id, username, with_videos=False) or {
        "id": client_id,
        "channels": channels,
    }


def delete_client(username: str, client_id: str) -> None:
    if not delete_client_owned(client_id, username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{client_id}' not found.",
        )


def disconnect_channel(username: str, client_id: str, channel_id: str) -> None:
    if not delete_channel_owned(channel_id, client_id, username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel '{channel_id}' not found.",
        )
    user = fetch_user(username) or {}
    if user.get("active_channel_id") == channel_id:
        remaining = list_channel_ids(client_id)
        update_user_fields(
            username,
            active_channel_id=remaining[0] if remaining else None,
        )
