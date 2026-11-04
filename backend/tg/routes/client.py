from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse

from backend.tg import schemas
from backend.tg.auth import get_current_user
from backend.tg.clients import (
    analyze_client_trends,
    collect_client_channel_titles,
    collect_client_video_titles,
    create_client,
    delete_client,
    get_client_content_plan,
    get_client_script_narration_text,
    map_client_content_plan,
    persist_client_profile_fields,
    refresh_client_topics,
    run_client_content_plan,
    run_client_content_script_refine,
    run_client_content_scripts,
    save_client_recommendations,
    set_active_client,
    sync_client_channels_from_creds,
    update_client,
    update_client_content_script,
)
from backend.tg.database import (
    fetch_client_doc,
    fetch_content_video,
    fetch_user,
    hydrate_suggestions_from_content_videos,
    list_channels_meta,
    list_clients_for_user,
    list_tracker_script_placements,
    list_videos_for_channel,
    replace_content_plan,
    suggestion_item_from_plan_item,
    update_client_fields,
    upsert_content_video,
)
from backend.main.db import plan_items_col
from backend.tg.google_oauth import get_user_google_creds
from backend.tg.services.topics import generate_auto_topics, normalize_topics
from backend.tg.services.youtube_api import (
    YT_DESCRIPTION_MAX,
    YT_TAGS_TOTAL_MAX,
    YT_TITLE_MAX,
    clamp_text,
    fetch_all_channels,
    fetch_video_descriptions,
    sanitize_youtube_tags,
)
from backend.tg.services.youtube_metadata import (
    generate_reference_thumbnail,
    generate_youtube_metadata,
    generate_youtube_thumbnail,
    generate_youtube_thumbnail_prompt,
    normalize_yt_language,
    reference_thumbnail_prompt,
    refine_youtube_metadata,
    refine_youtube_thumbnail_prompt,
)
from backend.tg.clients import _require_client_bundle

router = APIRouter(tags=["client"])


def _client_to_summary(client: dict) -> schemas.ClientSummary:
    slots = client.get("tracker_deliverables") or []
    return schemas.ClientSummary(
        id=client["id"],
        name=client.get("name") or "Client",
        channel_count=int(
            client.get("channel_count")
            if client.get("channel_count") is not None
            else len(client.get("channels") or [])
        ),
        website_url=client.get("website_url"),
        specialty=client.get("specialty"),
        designation=client.get("designation"),
        description=client.get("description"),
        reference_youtube_channel=client.get("reference_youtube_channel"),
        ai_videos_started_from=client.get("ai_videos_started_from"),
        onboarding_date=client.get("onboarding_date"),
        tracker_start_year=client.get("tracker_start_year"),
        tracker_start_month=client.get("tracker_start_month"),
        tracker_start_week=client.get("tracker_start_week"),
        tracker_deliverables=[
            schemas.TrackerDeliverableSlot(**s) if isinstance(s, dict) else s
            for s in slots
            if isinstance(s, dict)
        ],
        tracker_deliverables_period=client.get("tracker_deliverables_period") or "",
        topics=[schemas.TopicItem(**t) for t in normalize_topics(client.get("topics"))],
        is_active=False if client.get("is_active") is False else True,
    )


def _client_list_response(username: str) -> schemas.ClientListResponse:
    user = fetch_user(username) or {}
    clients = [_client_to_summary(c) for c in list_clients_for_user(username)]
    return schemas.ClientListResponse(
        clients=clients,
        active_client_id=user.get("active_client_id"),
        active_channel_id=user.get("active_channel_id"),
    )


@router.post("/client.list", response_model=schemas.ClientListResponse)
def client_list(current_user: dict = Depends(get_current_user)):
    return _client_list_response(current_user["username"])


@router.post("/client.create", response_model=schemas.ClientListResponse, status_code=201)
def client_create(
    body: schemas.ClientCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    create_client(current_user["username"], body.name)
    return _client_list_response(current_user["username"])


@router.post("/client.update", response_model=schemas.ClientListResponse)
def client_update(
    body: schemas.ClientUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    topics = [t.model_dump() for t in body.topics] if body.topics is not None else None
    deliverables = (
        [s.model_dump() for s in body.tracker_deliverables]
        if body.tracker_deliverables is not None
        else None
    )
    update_client(
        current_user["username"],
        body.client_id,
        name=body.name,
        website_url=body.website_url,
        specialty=body.specialty,
        designation=body.designation,
        description=body.description,
        reference_youtube_channel=body.reference_youtube_channel,
        ai_videos_started_from=body.ai_videos_started_from,
        onboarding_date=body.onboarding_date,
        tracker_start_year=body.tracker_start_year,
        tracker_start_month=body.tracker_start_month,
        tracker_start_week=body.tracker_start_week,
        tracker_deliverables=deliverables,
        is_active=body.is_active,
        topics=topics,
    )
    return _client_list_response(current_user["username"])


@router.post("/client.scrape-profile", response_model=schemas.ClientScrapeResponse)
def client_scrape_profile(
    body: schemas.ClientScrapeRequest,
    current_user: dict = Depends(get_current_user),
):
    """Deep-scrape the doctor's website, persist website/specialty, suggest topics."""
    print(
        f"[topics:route] scrape-profile START client={body.client_id} "
        f"website={bool(body.website_url)} specialty={bool(body.specialty)} "
        f"ref_yt={bool(body.reference_youtube_channel)}",
        flush=True,
    )
    website_url = (body.website_url or "").strip() or None
    specialty = (body.specialty or "").strip() or None
    reference_youtube_channel = (
        (body.reference_youtube_channel or "").strip() or None
        if body.reference_youtube_channel is not None
        else None
    )

    # Always store profile fields from the form before scraping
    client = persist_client_profile_fields(
        current_user["username"],
        body.client_id,
        website_url=website_url if body.website_url is not None else None,
        specialty=specialty if body.specialty is not None else None,
        reference_youtube_channel=reference_youtube_channel,
    )

    website_url = (website_url or client.get("website_url") or "").strip()
    specialty = specialty or client.get("specialty")
    has_ref = bool((client.get("reference_youtube_channel") or "").strip())
    if (
        not website_url
        and not specialty
        and not collect_client_video_titles(client)
        and not has_ref
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add a website URL, specialty, or reference YouTube channel before scraping topics.",
        )

    try:
        print("[topics:route] scrape-profile → generate_auto_topics …", flush=True)
        auto_topics, meta = generate_auto_topics(
            client_id=client.get("id"),
            client_name=client.get("name"),
            specialty=specialty,
            description=client.get("description"),
            website_url=website_url or None,
            video_titles=collect_client_video_titles(client),
            channel_titles=collect_client_channel_titles(client),
            manual_topics=[
                t for t in normalize_topics(client.get("topics")) if t.get("source") == "manual"
            ],
        )
    except ValueError as exc:
        print(f"[topics:route] scrape-profile 400: {exc}", flush=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    detected = meta.get("specialty") or specialty
    if detected and detected != client.get("specialty"):
        client = persist_client_profile_fields(
            current_user["username"],
            body.client_id,
            specialty=detected,
        )

    user = fetch_user(current_user["username"]) or {}
    clients = [_client_to_summary(c) for c in list_clients_for_user(current_user["username"])]
    print(
        f"[topics:route] scrape-profile DONE suggested={len(auto_topics)} "
        f"generator={meta.get('generator')} error={meta.get('openai_error')}",
        flush=True,
    )
    return schemas.ClientScrapeResponse(
        specialty=client.get("specialty") or detected,
        website_url=client.get("website_url"),
        suggested_topics=[schemas.TopicItem(**t) for t in auto_topics],
        page_title=meta.get("page_title"),
        page_snippet=meta.get("page_snippet") or meta.get("openai_rationale"),
        pages_scraped=meta.get("pages_scraped") or 0,
        clients=clients,
        active_client_id=user.get("active_client_id"),
        active_channel_id=user.get("active_channel_id"),
        generator=meta.get("generator"),
        openai_rationale=meta.get("openai_rationale"),
        openai_error=meta.get("openai_error"),
    )


@router.post("/client.refresh-topics", response_model=schemas.ClientRefreshTopicsResponse)
def client_refresh_topics(
    body: schemas.ClientRefreshTopicsRequest,
    current_user: dict = Depends(get_current_user),
):
    """Regenerate auto topics from website + specialty + YouTube history. Manual topics kept."""
    print(
        f"[topics:route] refresh-topics START client={body.client_id} "
        f"website={bool(body.website_url)} specialty={bool(body.specialty)} "
        f"ref_yt={bool(body.reference_youtube_channel)} "
        f"prompt={bool(body.user_prompt)}",
        flush=True,
    )
    current_topics = [t.model_dump() for t in body.topics] if body.topics is not None else None
    try:
        result = refresh_client_topics(
            current_user["username"],
            body.client_id,
            website_url=body.website_url,
            specialty=body.specialty,
            description=body.description,
            reference_youtube_channel=body.reference_youtube_channel,
            topics=current_topics,
            user_prompt=body.user_prompt,
        )
    except ValueError as exc:
        print(f"[topics:route] refresh-topics 400: {exc}", flush=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        print(f"[topics:route] refresh-topics ERROR {type(exc).__name__}: {exc}", flush=True)
        raise

    user = fetch_user(current_user["username"]) or {}
    clients = [_client_to_summary(c) for c in list_clients_for_user(current_user["username"])]
    client = result["client"]
    meta = result.get("scrape_meta") or {}
    print(
        f"[topics:route] refresh-topics DONE topics={len(client.get('topics') or [])} "
        f"generator={meta.get('generator')} stages={meta.get('openai_stages')} "
        f"ref={meta.get('reference_youtube')}",
        flush=True,
    )
    return schemas.ClientRefreshTopicsResponse(
        clients=clients,
        active_client_id=user.get("active_client_id"),
        active_channel_id=user.get("active_channel_id"),
        topics=[schemas.TopicItem(**t) for t in normalize_topics(client.get("topics"))],
        specialty=client.get("specialty"),
        page_title=meta.get("page_title"),
        page_snippet=meta.get("page_snippet"),
        pages_scraped=meta.get("pages_scraped") or 0,
        generator=meta.get("generator"),
        openai_rationale=meta.get("openai_rationale"),
        openai_error=meta.get("openai_error"),
    )


@router.post("/client.analyze-trends", response_model=schemas.ClientAnalyzeTrendsResponse)
async def client_analyze_trends(
    body: schemas.ClientAnalyzeTrendsRequest,
    current_user: dict = Depends(get_current_user),
):
    """Score topics with Google Search + YouTube Trends for India; persist on client."""
    print(
        f"[trends:route] POST /client.analyze-trends "
        f"user={current_user.get('username')!r} client_id={body.client_id!r} force={body.force}",
        flush=True,
    )
    try:
        result = await analyze_client_trends(
            current_user["username"],
            body.client_id,
            force=body.force,
        )
    except ValueError as exc:
        print(f"[trends:route] 400 {exc}", flush=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        print(f"[trends:route] ERROR {type(exc).__name__}: {exc}", flush=True)
        raise

    user = fetch_user(current_user["username"]) or {}
    clients = [_client_to_summary(c) for c in list_clients_for_user(current_user["username"])]
    client = result["client"]
    summary = result.get("summary") or {}
    print(
        f"[trends:route] OK scored={summary.get('scored')} "
        f"tasks={summary.get('api_tasks')} cost=${float(summary.get('total_cost') or 0):.4f} "
        f"cached_skip={summary.get('skipped_cached')} error={summary.get('error')!r}",
        flush=True,
    )
    return schemas.ClientAnalyzeTrendsResponse(
        clients=clients,
        active_client_id=user.get("active_client_id"),
        active_channel_id=user.get("active_channel_id"),
        topics=[schemas.TopicItem(**t) for t in normalize_topics(client.get("topics"))],
        geo=summary.get("geo") or "IN",
        scored=summary.get("scored") or 0,
        insufficient_data=summary.get("insufficient_data") or 0,
        skipped_cached=summary.get("skipped_cached") or 0,
        fetched_at=summary.get("fetched_at"),
        error=summary.get("error"),
        api_tasks=summary.get("api_tasks") or 0,
        total_cost=float(summary.get("total_cost") or 0),
    )


@router.post(
    "/client.save-recommendations",
    response_model=schemas.ClientSaveRecommendationsResponse,
)
def client_save_recommendations(
    body: schemas.ClientSaveRecommendationsRequest,
    current_user: dict = Depends(get_current_user),
):
    """Compute and persist combined recommendation scores on client topics."""
    try:
        result = save_client_recommendations(
            current_user["username"],
            body.client_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    user = fetch_user(current_user["username"]) or {}
    clients = [_client_to_summary(c) for c in list_clients_for_user(current_user["username"])]
    client = result["client"]
    return schemas.ClientSaveRecommendationsResponse(
        clients=clients,
        active_client_id=user.get("active_client_id"),
        active_channel_id=user.get("active_channel_id"),
        topics=[schemas.TopicItem(**t) for t in normalize_topics(client.get("topics"))],
        primary_count=result.get("primary_count") or 0,
        secondary_count=result.get("secondary_count") or 0,
        saved_at=result.get("saved_at"),
        threshold=float(result.get("threshold") or 50),
    )


def _content_plan_response(username: str, result: dict) -> schemas.ClientContentPlanResponse:
    user = fetch_user(username) or {}
    clients = [_client_to_summary(c) for c in list_clients_for_user(username)]
    raw = result.get("suggestions") or {}
    client = result.get("client") or {}
    client_id = client.get("id")
    if client_id:
        raw = hydrate_suggestions_from_content_videos(client_id, raw)
    placements_by_item: dict[str, list] = {}
    if client_id:
        for placement in list_tracker_script_placements(client_id):
            placements_by_item.setdefault(placement["item_id"], []).append(placement)
    coverage = raw.get("coverage")
    items = []
    for item in raw.get("items") or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        title_en = (row.get("title_en") or "").strip()
        title_hi = (row.get("title_hinglish") or "").strip()
        legacy = (row.get("working_title") or "").strip()
        if not title_en:
            title_en = legacy or title_hi or row.get("topic_text") or ""
        if not title_hi:
            title_hi = legacy or title_en
        row["title_en"] = title_en
        row["title_hinglish"] = title_hi
        row["working_title"] = legacy or title_hi or title_en
        row["tracker_placements"] = placements_by_item.get(row.get("id") or "", [])
        items.append(schemas.ContentSuggestionItem(**row))

    analysis_items = []
    for row in raw.get("keyword_analysis") or []:
        if not isinstance(row, dict):
            continue
        analysis_items.append(
            schemas.ContentKeywordAnalysisItem(
                topic_id=row.get("topic_id") or "",
                topic_text=row.get("topic_text") or "",
                recommendation_score=float(row.get("recommendation_score") or 0),
                weight=row.get("weight") or "medium",
                covered_long=bool(row.get("covered_long")),
                covered_short=bool(row.get("covered_short")),
                pending_long=bool(row.get("pending_long", not row.get("covered_long"))),
                pending_short=bool(row.get("pending_short", not row.get("covered_short"))),
                long_videos=[
                    schemas.ContentKeywordVideoRef(**v)
                    for v in (row.get("long_videos") or [])
                    if isinstance(v, dict) and v.get("video_id")
                ],
                short_videos=[
                    schemas.ContentKeywordVideoRef(**v)
                    for v in (row.get("short_videos") or [])
                    if isinstance(v, dict) and v.get("video_id")
                ],
                yt_title=row.get("yt_title"),
                yt_description=row.get("yt_description"),
                yt_tags=row.get("yt_tags"),
                yt_thumbnail_url=row.get("yt_thumbnail_url"),
                yt_thumbnail_prompt=row.get("yt_thumbnail_prompt"),
                yt_locales=row.get("yt_locales") or None,
            )
        )

    return schemas.ClientContentPlanResponse(
        clients=clients,
        active_client_id=user.get("active_client_id"),
        active_channel_id=user.get("active_channel_id"),
        suggestions=schemas.ContentSuggestionsPayload(
            generated_at=raw.get("generated_at"),
            mapped_at=raw.get("mapped_at"),
            scripts_generated_at=raw.get("scripts_generated_at"),
            count=int(raw.get("count") or 0),
            user_prompt=raw.get("user_prompt"),
            items=items,
            coverage=schemas.ContentCoverageSummary(**coverage) if coverage else None,
            keyword_analysis=analysis_items,
            recent_video_types=list(raw.get("recent_video_types") or []),
        ),
    )


@router.post("/client.content-plan.get", response_model=schemas.ClientContentPlanResponse)
def client_content_plan_get(
    body: schemas.ClientContentPlanGetRequest,
    current_user: dict = Depends(get_current_user),
):
    result = get_client_content_plan(current_user["username"], body.client_id)
    return _content_plan_response(current_user["username"], result)


@router.post("/client.content-plan.map", response_model=schemas.ClientContentPlanResponse)
def client_content_plan_map(
    body: schemas.ClientContentPlanMapRequest,
    current_user: dict = Depends(get_current_user),
):
    """1st call: map library videos → keywords and persist Long/Short analysis."""
    try:
        result = map_client_content_plan(
            current_user["username"],
            body.client_id,
            force=body.force,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _content_plan_response(current_user["username"], result)


@router.post("/client.content-plan.generate", response_model=schemas.ClientContentPlanResponse)
def client_content_plan_generate(
    body: schemas.ClientContentPlanGenerateRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        result = run_client_content_plan(
            current_user["username"],
            body.client_id,
            count=body.count,
            force_remap=body.force_remap,
            regenerate=False,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _content_plan_response(current_user["username"], result)


@router.post("/client.content-plan.regenerate", response_model=schemas.ClientContentPlanResponse)
def client_content_plan_regenerate(
    body: schemas.ClientContentPlanRegenerateRequest,
    current_user: dict = Depends(get_current_user),
):
    prompt = (body.user_prompt or "").strip()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_prompt is required to regenerate.",
        )
    try:
        # Prefer previous count when not specified
        count = body.count
        if count is None:
            existing = get_client_content_plan(current_user["username"], body.client_id)
            count = int((existing.get("suggestions") or {}).get("count") or 5)
        result = run_client_content_plan(
            current_user["username"],
            body.client_id,
            count=count,
            force_remap=body.force_remap,
            user_prompt=prompt,
            regenerate=True,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _content_plan_response(current_user["username"], result)


@router.post(
    "/client.content-plan.generate-scripts",
    response_model=schemas.ClientContentPlanResponse,
)
def client_content_plan_generate_scripts(
    body: schemas.ClientContentPlanScriptsRequest,
    current_user: dict = Depends(get_current_user),
):
    """3rd call: generate spoken Hinglish scripts for all content-plan titles."""
    try:
        result = run_client_content_scripts(
            current_user["username"],
            body.client_id,
            example1=body.example1,
            example2=body.example2,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _content_plan_response(current_user["username"], result)


def _clean_example_scripts(raw) -> list[str]:
    out = []
    for row in raw or []:
        if row is None:
            continue
        text = str(row).strip()
        if text:
            out.append(text)
    return out


@router.post("/client.example-scripts.get", response_model=schemas.ClientExampleScriptsResponse)
def get_client_example_scripts(
    body: schemas.ClientExampleScriptsGetRequest,
    current_user: dict = Depends(get_current_user),
):
    client = fetch_client_doc(body.client_id, username=current_user["username"])
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return schemas.ClientExampleScriptsResponse(scripts=_clean_example_scripts(client.get("example_scripts")))


@router.post("/client.example-scripts.save", response_model=schemas.ClientExampleScriptsResponse)
def save_client_example_scripts(
    body: schemas.ClientExampleScriptsSaveRequest,
    current_user: dict = Depends(get_current_user),
):
    username = current_user["username"]
    if not fetch_client_doc(body.client_id, username=username):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    scripts = _clean_example_scripts(body.scripts)
    saved = update_client_fields(body.client_id, username, {"example_scripts": scripts})
    if not saved:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return schemas.ClientExampleScriptsResponse(scripts=_clean_example_scripts(saved.get("example_scripts")))


@router.post(
    "/client.content-plan.refine-script",
    response_model=schemas.ClientContentPlanResponse,
)
def client_content_plan_refine_script(
    body: schemas.ClientContentPlanRefineScriptRequest,
    current_user: dict = Depends(get_current_user),
):
    """Refine one item's script with a user prompt (single-script AI call)."""
    prompt = (body.user_prompt or "").strip()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_prompt is required to refine a script.",
        )
    if not (body.item_id or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="item_id is required.",
        )
    try:
        result = run_client_content_script_refine(
            current_user["username"],
            body.client_id,
            item_id=body.item_id,
            user_prompt=prompt,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _content_plan_response(current_user["username"], result)


@router.post(
    "/client.content-plan.update-script",
    response_model=schemas.ClientContentPlanResponse,
)
def client_content_plan_update_script(
    body: schemas.ClientContentPlanUpdateScriptRequest,
    current_user: dict = Depends(get_current_user),
):
    """Overwrite one item's script from tracker (no AI)."""
    if not (body.item_id or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="item_id is required.")
    try:
        result = update_client_content_script(
            current_user["username"],
            body.client_id,
            item_id=body.item_id,
            script=body.script,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _content_plan_response(current_user["username"], result)


@router.post("/client.content-plan.narrate-script")
def client_content_plan_narrate_script(
    body: schemas.ClientContentPlanNarrateScriptRequest,
    current_user: dict = Depends(get_current_user),
):
    """Stream narration audio/mpeg as OpenAI synthesizes (chunked transfer).

    Cached scripts stream from disk immediately. Fresh TTS is piped through
    while the mp3 is saved for later replay (unless force=true).
    """
    from backend.tg.services.openai_content_plan import stream_narrate_script_audio

    try:
        text = get_client_script_narration_text(
            current_user["username"],
            body.client_id,
            item_id=body.item_id,
            combined=bool(body.combined),
        )
        # Peek first chunk so validation / cache-hit errors happen before headers
        stream = stream_narrate_script_audio(text=text, force=bool(body.force))
        first_chunk, from_cache = next(stream)
    except StopIteration as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Narration returned no audio.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Narration failed: {exc}",
        ) from exc

    def byte_iter():
        try:
            if first_chunk:
                yield first_chunk
            for chunk, _cached in stream:
                if chunk:
                    yield chunk
        except Exception as exc:
            print(f"[content-plan:tts] stream error mid-flight: {exc}", flush=True)
            raise

    headers = {
        "Content-Disposition": 'inline; filename="script-narration.mp3"',
        "Cache-Control": "private, max-age=86400" if from_cache else "no-store",
        "X-Narration-Cached": "1" if from_cache else "0",
        "X-Accel-Buffering": "no",
    }
    if from_cache and first_chunk:
        headers["Content-Length"] = str(len(first_chunk))

    return StreamingResponse(
        byte_iter(),
        media_type="audio/mpeg",
        headers=headers,
    )


def _is_short_video(video: dict) -> bool:
    return bool(video.get("is_short") or video.get("duration_type") == "short")


def _newest_videos(videos: list[dict], limit: int, *, shorts: bool | None) -> list[dict]:
    ordered = sorted(videos, key=lambda v: str(v.get("published_at") or ""), reverse=True)
    if shorts is True:
        matched = [v for v in ordered if _is_short_video(v)]
    elif shorts is False:
        matched = [v for v in ordered if not _is_short_video(v)]
    else:
        matched = list(ordered)
    if shorts is not None and len(matched) < limit:
        seen = {v.get("id") for v in matched}
        for video in ordered:
            if video.get("id") not in seen:
                matched.append(video)
            if len(matched) >= limit:
                break
    return matched[:limit]


def _description_examples(
    item: dict,
    videos: list[dict],
    reference_ids: list[str],
    descriptions: dict,
) -> list[dict]:
    if reference_ids:
        wanted = set(reference_ids)
        chosen = [v for v in videos if v.get("id") in wanted][:3]
    else:
        chosen = _newest_videos(videos, 3, shorts=(item.get("format") == "Short"))
    examples = []
    for video in chosen:
        row = descriptions.get(video.get("id")) or {}
        text = str(row.get("description") or "").strip()
        if not text:
            continue
        examples.append({
            "title": row.get("title") or video.get("title") or "",
            "description": text,
        })
    return examples[:3]


def _locale_payload(metadata_res: dict, thumbnail_prompt: str, thumbnail_url: str | None) -> dict:
    locale = {}
    if metadata_res.get("yt_title"):
        locale["yt_title"] = metadata_res["yt_title"]
    if metadata_res.get("yt_description"):
        locale["yt_description"] = clamp_text(metadata_res["yt_description"], YT_DESCRIPTION_MAX)
    if metadata_res.get("yt_tags"):
        locale["yt_tags"] = sanitize_youtube_tags(metadata_res["yt_tags"])
    if thumbnail_prompt:
        locale["yt_thumbnail_prompt"] = thumbnail_prompt
    if thumbnail_url:
        locale["yt_thumbnail_url"] = thumbnail_url
    return locale


def _mirror_legacy_yt_fields(target: dict) -> None:
    locales = target.get("yt_locales") or {}
    preferred = locales.get("hinglish") if isinstance(locales, dict) else None
    if not preferred and isinstance(locales, dict):
        preferred = next((v for v in locales.values() if isinstance(v, dict) and v.get("yt_title")), None)
    if not isinstance(preferred, dict):
        return
    for key in ("yt_title", "yt_description", "yt_tags", "yt_thumbnail_url", "yt_thumbnail_prompt"):
        if preferred.get(key) is not None:
            target[key] = preferred[key]


def _apply_locale_metadata(target: dict, language: str, locale: dict) -> None:
    locales = dict(target.get("yt_locales") or {})
    previous = locales.get(language) if isinstance(locales.get(language), dict) else {}
    locales[language] = {**previous, **locale}
    target["yt_locales"] = locales
    _mirror_legacy_yt_fields(target)


def _metadata_error_text(exc: Exception) -> str:
    if isinstance(exc, HTTPException) and exc.detail:
        text = str(exc.detail)
    else:
        text = str(exc or "")
        if text.startswith("500: "):
            text = text[5:]
    lower = text.lower()
    if "no credits remaining" in lower or "insufficient_quota" in lower:
        return (
            "OpenAI has no credits remaining. Add credits at "
            "https://platform.openai.com/settings/organization/billing/ and try again."
        )
    return text.strip() or "YouTube metadata generation failed."


class _RecentThumbnailUnresolved(Exception):
    """Newest-3 reference edit failed before a text-only thumbnail was allowed."""


def _thumbnail_strategy(*, has_refs: bool, user_picked: bool, allow_unreferenced: bool) -> str:
    """reference: edit channel thumbs. text: generate with no reference photo."""
    if has_refs and not (allow_unreferenced and not user_picked):
        return "reference"
    return "text"


def _raise_metadata_failures(failures: list[str], generated: dict) -> None:
    if generated:
        return
    messages: list[str] = []
    for row in failures:
        msg = row.split(": ", 1)[1] if ": " in row else row
        if msg not in messages:
            messages.append(msg)
    detail = messages[0] if messages else "YouTube metadata generation failed for the selected items."
    if len(messages) > 1:
        detail = " ".join(messages)
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)


@router.post("/client.content-plan-generate-metadata", response_model=schemas.ClientContentPlanMetadataResponse)
def client_content_plan_generate_metadata(
    body: schemas.ClientContentPlanGenerateMetadataRequest,
    current_user: dict = Depends(get_current_user),
):
    username = current_user["username"]
    user = fetch_user(username)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    client_id = body.client_id
    languages = []
    for raw in (body.languages or ["hinglish"]):
        lang = normalize_yt_language(raw)
        if lang not in languages:
            languages.append(lang)
    if not languages:
        raise HTTPException(status_code=400, detail="Select at least one language.")

    print(
        f"[yt-metadata] START generate client={client_id} items={body.item_ids} "
        f"languages={languages}",
        flush=True,
    )

    channel_id = user.get("active_channel_id")
    if not channel_id:
        linked = list_channels_meta(client_id)
        channel_id = linked[0]["id"] if linked else None
        print(
            f"[yt-metadata] no active channel; using {channel_id!r} for reference thumbs",
            flush=True,
        )
        
    client_bundle = _require_client_bundle(username, client_id, with_videos=False)
    client_summary = {
        "name": client_bundle.get("name", "N/A"),
        "specialty": client_bundle.get("specialty", "N/A"),
    }
    suggestions = client_bundle.get("content_suggestions", {})
    items = suggestions.get("items", [])
    
    # Reference thumbnails, plus description examples from the same channel.
    videos = []
    picked_refs = None
    descriptions: dict = {}
    if channel_id:
        videos = list_videos_for_channel(channel_id, client_id)
        videos = sorted(videos, key=lambda v: v.get("published_at", ""), reverse=True)
        if body.reference_video_ids:
            selected = [v for v in videos if v.get("id") in body.reference_video_ids]
            picked_refs = [v for v in selected if v.get("thumbnail_url") or v.get("id")][:3]
            example_rows = picked_refs
        else:
            example_rows = _newest_videos(videos, 3, shorts=False) + _newest_videos(videos, 3, shorts=True)
        example_ids = []
        for row in example_rows:
            vid = row.get("id")
            if vid and vid not in example_ids:
                example_ids.append(vid)
        if example_ids:
            try:
                creds = get_user_google_creds(username, client_id, channel_id)
                descriptions = fetch_video_descriptions(creds, example_ids)
            except Exception as exc:  # noqa: BLE001
                print(f"[yt-metadata] description examples skipped: {exc}", flush=True)

    def _refs_for(portrait: bool) -> list:
        if picked_refs:
            return picked_refs
        if not videos:
            return []
        preferred = _newest_videos(videos, 3, shorts=portrait)
        return [v for v in preferred if v.get("thumbnail_url") or v.get("id")][:3]

    script_override = (body.script_override or "").strip()
    use_script_override = bool(script_override) and len(body.item_ids) == 1
        
    # Build a lookup from topic_id -> content plan item (for script reuse)
    topic_id_to_item = {}
    for item in items:
        tid = item.get("topic_id")
        if tid:
            topic_id_to_item[tid] = item

    keyword_analysis = suggestions.get("keyword_analysis", [])

    def _persist_locale(topic_id, locale, language, *, topic_text, source, item_id):
        if not topic_id:
            return
        upsert_content_video(
            client_id,
            topic_id,
            topic_text=topic_text or "",
            source=source,
            content_plan_item_id=item_id,
            locales={language: locale},
            replace_locales=True,
        )

    def _script_title_for(topic):
        if not isinstance(topic, dict):
            return ""
        return (
            str(topic.get("title_hinglish") or "").strip()
            or str(topic.get("working_title") or "").strip()
            or str(topic.get("title_en") or "").strip()
        )

    def _script_for(item_script):
        if use_script_override:
            return script_override
        return item_script

    def _portrait(topic) -> bool:
        fmt = str(body.format or (topic or {}).get("format") or "").strip().lower()
        return fmt == "short"

    def _generate_locale(topic, script, language, examples=None):
        metadata_res = generate_youtube_metadata(
            client_summary=client_summary,
            topic=topic,
            script=script,
            user_prompt=body.user_prompt,
            language=language,
            script_title=_script_title_for(topic) if script else None,
            examples=examples,
        )
        portrait = _portrait(topic)
        headline = str(metadata_res.get("yt_title") or "")
        description = str(metadata_res.get("yt_description") or "")
        thumbnail_prompt = ""
        thumbnail_url = None
        refs = _refs_for(portrait)
        strategy = _thumbnail_strategy(
            has_refs=bool(refs),
            user_picked=bool(picked_refs),
            allow_unreferenced=bool(body.allow_unreferenced_thumbnail),
        )
        if strategy == "reference":
            thumbnail_prompt = reference_thumbnail_prompt(
                client_summary=client_summary,
                topic=topic,
                script=script,
                user_prompt=body.user_prompt,
                language=language,
                headline=headline,
                description=description,
                portrait=portrait,
            )
            thumbnail_url = generate_reference_thumbnail(
                thumbnail_prompt, refs, portrait=portrait
            )
            if not thumbnail_url and not picked_refs:
                print(
                    f"[yt-thumbnail] newest 3 reference edit failed for language={language}",
                    flush=True,
                )
                raise _RecentThumbnailUnresolved()
            if not thumbnail_url:
                print(
                    f"[yt-thumbnail] chosen reference edit produced no image for language={language}",
                    flush=True,
                )
        else:
            thumbnail_prompt = generate_youtube_thumbnail_prompt(
                client_summary=client_summary,
                topic=topic,
                script=script,
                user_prompt=body.user_prompt,
                reference_image_urls=[],
                language=language,
                headline=headline,
                description=description,
                portrait=portrait,
            )
            if thumbnail_prompt:
                try:
                    thumbnail_url = generate_youtube_thumbnail(thumbnail_prompt, portrait=portrait)
                except Exception as e:
                    print(f"Failed to generate thumbnail for language={language}: {e}")
        return _locale_payload(metadata_res, thumbnail_prompt, thumbnail_url)

    # Track which topic_ids we've already processed to avoid duplicate generation
    processed_topic_ids = set()
    generated_locales: dict = {}
    failures: list[str] = []
    pending_locales: list[dict] = []

    def _fail_language(label: str, language: str, exc: Exception) -> None:
        msg = _metadata_error_text(exc)
        print(f"[yt-metadata] failed language={language} {label}: {msg}", flush=True)
        failures.append(f"{language}: {msg}")

    def _remember_locale(topic_id, locale, language, *, topic_text, source, item_id):
        pending_locales.append({
            "topic_id": topic_id,
            "locale": locale,
            "language": language,
            "topic_text": topic_text,
            "source": source,
            "item_id": item_id,
        })
        generated_locales[language] = locale

    def _unresolved_thumbnail_response():
        print("[yt-thumbnail] newest 3 reference edit failed; metadata was not saved", flush=True)
        plan = client_content_plan_get(
            schemas.ClientContentPlanGetRequest(client_id=client_id),
            current_user=current_user,
        )
        return schemas.ClientContentPlanMetadataResponse(
            **plan.model_dump(),
            yt_locales=None,
            thumbnail_reference_failed=True,
        )

    # Resolve item_ids from latest content-plan suggestions OR historical plan_items
    # (weekly trackers often keep older content_plan_item_id values).
    items_by_id = {
        str(item.get("id")): item
        for item in items
        if isinstance(item, dict) and item.get("id")
    }
    requested_ids = [str(x) for x in (body.item_ids or []) if str(x or "").strip()]
    missing_ids = [iid for iid in requested_ids if iid not in items_by_id]
    if missing_ids:
        for pi in plan_items_col().find(
            {"project_id": client_id, "id": {"$in": missing_ids}},
            {"_id": 0},
        ):
            shaped = suggestion_item_from_plan_item(pi)
            if shaped:
                items_by_id[str(shaped["id"])] = shaped

    # --- Pass 1: Content Plan / plan_items (From Script) ---
    for item_id in requested_ids:
        item = items_by_id.get(item_id)
        if not item:
            continue
        topic_id = item.get("topic_id")
        processed_topic_ids.add(topic_id)
        source = "script" if item.get("script") else "manual"
        topic_text = item.get("topic") or item.get("topic_text") or item.get("working_title") or ""
        for language in languages:
            try:
                locale = _generate_locale(
                    item,
                    _script_for(item.get("script")),
                    language,
                    _description_examples(item, videos, body.reference_video_ids, descriptions),
                )
            except _RecentThumbnailUnresolved:
                return _unresolved_thumbnail_response()
            except Exception as exc:  # noqa: BLE001
                _fail_language(f"item={item.get('id')}", language, exc)
                continue
            _remember_locale(
                topic_id,
                locale,
                language,
                topic_text=topic_text,
                source=source,
                item_id=item.get("id"),
            )

    # --- Pass 2: Keyword Analysis items (Manual Pick) ---
    str_item_ids = [str(x) for x in body.item_ids]
    for kw in keyword_analysis:
        if not isinstance(kw, dict):
            continue
        kw_topic_id = str(kw.get("topic_id"))
        if kw_topic_id not in str_item_ids:
            continue
        # Skip if already processed via content plan item
        if kw.get("topic_id") in processed_topic_ids:
            continue

        matching_item = topic_id_to_item.get(kw.get("topic_id"))
        plan_script = matching_item.get("script") if matching_item else None
        script_to_use = _script_for(plan_script)
        topic_for_prompt = matching_item if matching_item else {"topic_text": kw.get("topic_text")}
        source = "script" if plan_script else "manual"
        item_id = matching_item.get("id") if matching_item else None
        topic_text = (
            (matching_item.get("topic") if matching_item else None)
            or kw.get("topic_text")
            or ""
        )

        for language in languages:
            try:
                locale = _generate_locale(
                    topic_for_prompt,
                    script_to_use,
                    language,
                    _description_examples(topic_for_prompt, videos, body.reference_video_ids, descriptions),
                )
            except _RecentThumbnailUnresolved:
                return _unresolved_thumbnail_response()
            except Exception as exc:  # noqa: BLE001
                _fail_language(f"topic={kw.get('topic_id')}", language, exc)
                continue
            _remember_locale(
                kw.get("topic_id"),
                locale,
                language,
                topic_text=topic_text,
                source=source,
                item_id=item_id,
            )

    standalone_topic_id = str(body.topic_id or "").strip()
    if standalone_topic_id and standalone_topic_id not in {str(tid) for tid in processed_topic_ids}:
        standalone_title = (body.topic_title or "").strip() or standalone_topic_id
        standalone_topic = {
            "topic_text": standalone_title,
            "title_hinglish": standalone_title,
            "format": body.format or "",
        }
        standalone_script = (body.script_override or "").strip()
        for language in languages:
            try:
                locale = _generate_locale(
                    standalone_topic,
                    standalone_script,
                    language,
                    _description_examples(standalone_topic, videos, body.reference_video_ids, descriptions),
                )
            except _RecentThumbnailUnresolved:
                return _unresolved_thumbnail_response()
            except Exception as exc:  # noqa: BLE001
                _fail_language(f"topic={standalone_topic_id}", language, exc)
                continue
            _remember_locale(
                standalone_topic_id,
                locale,
                language,
                topic_text=standalone_title,
                source="manual",
                item_id=None,
            )

    _raise_metadata_failures(failures, generated_locales)
    for row in pending_locales:
        _persist_locale(
            row["topic_id"],
            row["locale"],
            row["language"],
            topic_text=row["topic_text"],
            source=row["source"],
            item_id=row["item_id"],
        )

    client_bundle["content_suggestions"] = suggestions
    replace_content_plan(client_id, client_bundle)
    plan = client_content_plan_get(schemas.ClientContentPlanGetRequest(client_id=client_id), current_user=current_user)
    return schemas.ClientContentPlanMetadataResponse(
        **plan.model_dump(),
        yt_locales=generated_locales or None,
    )


@router.post("/client.content-plan-refine-metadata", response_model=schemas.ClientContentPlanMetadataResponse)
def client_content_plan_refine_metadata(
    body: schemas.ClientContentPlanRefineMetadataRequest,
    current_user: dict = Depends(get_current_user),
):
    username = current_user["username"]
    user = fetch_user(username)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
        
    client_id = body.client_id
    channel_id = user.get("active_channel_id")
    
    client_bundle = _require_client_bundle(username, client_id, with_videos=False)
    suggestions = client_bundle.get("content_suggestions", {})
    items = suggestions.get("items", [])
    keyword_analysis = suggestions.get("keyword_analysis", [])
    
    # Try latest content-plan items, then historical plan_items, then keyword_analysis
    target_item = next((i for i in items if i.get("id") == body.item_id), None)
    if not target_item and body.item_id:
        pi = plan_items_col().find_one(
            {"id": body.item_id, "project_id": client_id},
            {"_id": 0},
        )
        target_item = suggestion_item_from_plan_item(pi)
    target_kw = None
    if not target_item:
        # Search keyword_analysis by topic_id
        target_kw = next((k for k in keyword_analysis if isinstance(k, dict) and str(k.get("topic_id")) == str(body.item_id)), None)
    
    if not target_item and not target_kw and str(body.topic_id or "").strip():
        target_kw = {
            "topic_id": str(body.topic_id).strip(),
            "topic_text": (body.topic_title or "").strip(),
        }
    if not target_item and not target_kw:
        raise HTTPException(status_code=404, detail="Topic item not found")
    
    target = target_item or target_kw
    language = normalize_yt_language(body.language or "hinglish")
    topic_id = target.get("topic_id")
    matching_item = target_item or next((i for i in items if i.get("topic_id") == topic_id), None)
    matching_kw = target_kw or next((k for k in keyword_analysis if isinstance(k, dict) and k.get("topic_id") == topic_id), None)
    source = "script" if matching_item and matching_item.get("script") else "manual"
    topic_text = (
        (matching_item.get("topic") if matching_item else None)
        or (matching_item.get("topic_text") if matching_item else None)
        or (matching_kw.get("topic_text") if matching_kw else None)
        or ""
    )
    package = fetch_content_video(client_id, topic_id) if topic_id else None
        
    portrait = str(body.format or (matching_item or {}).get("format") or "").strip().lower() == "short"
    reference_rows = []
    if channel_id:
        videos = list_videos_for_channel(channel_id, client_id)
        if body.reference_video_ids:
            selected = [v for v in videos if v.get("id") in body.reference_video_ids]
            reference_rows = [v for v in selected if v.get("thumbnail_url") or v.get("id")][:3]
        else:
            preferred = _newest_videos(videos, 3, shorts=portrait)
            reference_rows = [v for v in preferred if v.get("thumbnail_url") or v.get("id")][:3]

    locales = dict((package or {}).get("yt_locales") or target.get("yt_locales") or {})
    current_locale = locales.get(language) if isinstance(locales.get(language), dict) else {}
    if not current_locale and language == "hinglish":
        current_locale = {
            "yt_title": target.get("yt_title"),
            "yt_description": target.get("yt_description"),
            "yt_tags": target.get("yt_tags"),
            "yt_thumbnail_prompt": target.get("yt_thumbnail_prompt"),
            "yt_thumbnail_url": target.get("yt_thumbnail_url"),
        }
        
    current_meta = {
        "yt_title": current_locale.get("yt_title"),
        "yt_description": current_locale.get("yt_description"),
        "yt_tags": current_locale.get("yt_tags"),
    }
    
    try:
        metadata_res = refine_youtube_metadata(
            current_metadata=current_meta,
            user_prompt=body.user_prompt,
            language=language,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_metadata_error_text(exc),
        ) from exc
    
    current_thumbnail_prompt = current_locale.get("yt_thumbnail_prompt") or ""
    thumbnail_prompt = refine_youtube_thumbnail_prompt(
        current_thumbnail_prompt=current_thumbnail_prompt,
        user_prompt=body.user_prompt,
        language=language,
    )
    
    locale = _locale_payload(metadata_res, thumbnail_prompt, None)
    if thumbnail_prompt and thumbnail_prompt != current_thumbnail_prompt:
        thumbnail_url = None
        if reference_rows:
            thumbnail_url = generate_reference_thumbnail(
                thumbnail_prompt, reference_rows, portrait=portrait
            )
            if not thumbnail_url:
                print(
                    "[yt-thumbnail] reference edit produced no image during refine; "
                    "skipping text-only generation so the doctor is not replaced",
                    flush=True,
                )
        else:
            try:
                thumbnail_url = generate_youtube_thumbnail(thumbnail_prompt, portrait=portrait)
            except Exception as e:
                print(f"Failed to generate thumbnail during refine: {e}")
        if thumbnail_url:
            locale["yt_thumbnail_url"] = thumbnail_url
    elif current_locale.get("yt_thumbnail_url"):
        locale["yt_thumbnail_url"] = current_locale.get("yt_thumbnail_url")

    saved_locales = {language: locale}
    if topic_id:
        saved = upsert_content_video(
            client_id,
            topic_id,
            topic_text=topic_text,
            source=source,
            content_plan_item_id=(matching_item or {}).get("id") if matching_item else None,
            locales={language: locale},
            replace_locales=True,
        )
        saved_locales = saved.get("yt_locales") or saved_locales
            
    client_bundle["content_suggestions"] = suggestions
    replace_content_plan(client_id, client_bundle)
    plan = client_content_plan_get(schemas.ClientContentPlanGetRequest(client_id=client_id), current_user=current_user)
    return schemas.ClientContentPlanMetadataResponse(
        **plan.model_dump(),
        yt_locales=saved_locales,
    )


@router.post("/client.content-video.update-description")
def client_content_video_update_description(
    body: schemas.ContentVideoUpdateDescriptionRequest,
    current_user: dict = Depends(get_current_user),
):
    username = current_user["username"]
    _require_client_bundle(username, body.client_id, with_videos=False)
    language = normalize_yt_language(body.language)
    package = fetch_content_video(body.client_id, body.topic_id)
    if not package:
        raise HTTPException(status_code=404, detail="No YouTube metadata for this topic yet.")
    locales = dict(package.get("yt_locales") or {})
    current = locales.get(language) if isinstance(locales.get(language), dict) else {}
    if not str(current.get("yt_title") or "").strip():
        raise HTTPException(status_code=400, detail="Generate metadata for this language first.")
    title = (body.yt_title or "").strip()
    description = body.yt_description or ""
    tags = [str(tag).strip() for tag in (body.yt_tags or []) if str(tag).strip()]
    joined_tags = ",".join(tags)
    if not title:
        raise HTTPException(status_code=400, detail="Title is required.")
    if len(title) > YT_TITLE_MAX:
        raise HTTPException(status_code=400, detail=f"Title must be {YT_TITLE_MAX} characters or fewer.")
    if len(description) > YT_DESCRIPTION_MAX:
        raise HTTPException(status_code=400, detail=f"Description must be {YT_DESCRIPTION_MAX} characters or fewer.")
    if len(joined_tags) > YT_TAGS_TOTAL_MAX:
        raise HTTPException(status_code=400, detail=f"Tags must be {YT_TAGS_TOTAL_MAX} characters or fewer.")
    if any(len(tag) > 100 or any(ch in tag for ch in "<>#") for tag in tags):
        raise HTTPException(status_code=400, detail="Each tag must be 100 characters or fewer and cannot contain #, <, or >.")
    merged = {**current, "yt_title": title, "yt_description": description, "yt_tags": tags}
    saved = upsert_content_video(
        body.client_id,
        body.topic_id,
        locales={language: merged},
        replace_locales=True,
    )
    return {
        "topic_id": body.topic_id,
        "language": language,
        "yt_locales": saved.get("yt_locales") or {},
    }


@router.post("/client.select", response_model=schemas.ClientListResponse)
def client_select(
    body: schemas.ClientSelectRequest,
    current_user: dict = Depends(get_current_user),
):
    set_active_client(current_user["username"], body.client_id)
    return _client_list_response(current_user["username"])


@router.post("/client.sync-channels", response_model=schemas.YouTubeChannelListResponse)
def client_sync_channels(
    body: schemas.ClientSyncChannelsRequest,
    current_user: dict = Depends(get_current_user),
):
    """Re-discover YouTube channels using a linked channel's Google credentials."""
    username = current_user["username"]
    target_client_id = body.client_id
    source_channel_id = body.channel_id

    creds = get_user_google_creds(username, target_client_id, source_channel_id)
    channel_infos = fetch_all_channels(creds)
    sync_client_channels_from_creds(
        username, target_client_id, source_channel_id, channel_infos
    )

    user = fetch_user(username) or {}
    channels = [
        schemas.YouTubeChannelInfo(
            id=c["id"],
            title=c.get("title", ""),
            description=c.get("description", ""),
            custom_url=c.get("custom_url"),
            published_at=c.get("published_at") or "",
            view_count=c.get("view_count", 0),
            subscriber_count=c.get("subscriber_count", 0),
            video_count=c.get("video_count", 0),
            language=c.get("language"),
        )
        for c in list_channels_meta(target_client_id)
    ]
    return schemas.YouTubeChannelListResponse(
        channels=channels,
        active_client_id=user.get("active_client_id"),
        active_channel_id=user.get("active_channel_id"),
    )


@router.post("/client.delete", response_model=schemas.ClientListResponse)
def client_delete(
    body: schemas.ClientDeleteRequest,
    current_user: dict = Depends(get_current_user),
):
    delete_client(current_user["username"], body.client_id)
    return _client_list_response(current_user["username"])
