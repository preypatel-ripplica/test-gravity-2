"""Google Business Profile routes for a client workspace."""

from __future__ import annotations

import traceback
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from backend.tg import schemas
from backend.tg.auth import get_current_user
from backend.tg.database import (
    fetch_client_doc,
    fetch_topics,
    append_gbp_apply_history,
    get_gbp_connection,
    get_gbp_location,
    get_gbp_optimize,
    merge_gbp_optimize,
    get_gbp_post_draft,
    get_gbp_review_draft,
    list_gbp_connections,
    list_gbp_locations,
    list_gbp_post_drafts,
    list_gbp_review_drafts,
    save_gbp_connection,
    save_gbp_post_draft,
    save_gbp_review_draft,
    set_gbp_location_selection,
    upsert_gbp_location,
)
from backend.tg.gbp_oauth import ensure_gbp_credentials
from backend.tg.services.gbp_api import (
    GbpApiError,
    build_local_post_body,
    build_location_patch,
    create_local_post,
    delete_local_post,
    delete_media,
    delete_review_reply,
    fetch_daily_metrics,
    fetch_search_keywords,
    format_address,
    get_location,
    list_local_posts,
    list_media,
    list_all_reviews,
    list_reviews,
    merge_metric_payloads,
    patch_local_post,
    patch_location,
    percent_change,
    previous_window,
    require_selected_location,
    rollup_labels,
    totals_between,
    appointment_link,
    list_place_action_links,
    save_appointment_link,
    search_categories,
    sync_managed_locations,
    update_review_reply,
    upload_location_media,
)
from backend.tg.services.gbp_optimize import (
    build_audit,
    drop_add_already_listed,
    keyword_month_window,
    request_profile_draft,
    soften_audit_listing,
)
from backend.tg.services.gbp_posts import (
    dequeue_gbp_draft,
    enqueue_gbp_draft,
    generate_location_drafts,
    generate_post_image,
    normalize_schedule,
    public_schedule,
    publish_gbp_draft,
    reorder_gbp_queue,
    run_scheduled_posts,
)
from backend.tg.services.gbp_replies import build_review_insights, dynamic_review_themes, handle_one_review
from backend.tg.services.gcs_storage import upload_bytes

router = APIRouter(tags=["gbp"])


def _require_client(client_id: str, username: str) -> dict:
    client = fetch_client_doc(client_id, username=username)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _google(exc: GbpApiError) -> HTTPException:
    status = exc.status_code if 400 <= exc.status_code < 500 else 502
    if status == 401:
        status = 400
    return HTTPException(status_code=status, detail=exc.message)


def _public_location(row: dict) -> dict:
    return {
        "location_id": row.get("location_id"),
        "account_id": row.get("account_id"),
        "account_name": row.get("account_name"),
        "account_title": row.get("account_title") or "",
        "location_name": row.get("location_name"),
        "title": row.get("title") or "",
        "address": row.get("address") or "",
        "store_code": row.get("store_code") or "",
        "selected": bool(row.get("selected")),
        "available": row.get("available", True),
    }


def _bundle(client_id: str) -> dict:
    connection = get_gbp_connection(client_id) or {}
    creds = connection.get("google_credentials") or {}
    connected = connection.get("status") == "connected" and bool(creds.get("refresh_token") or creds.get("token"))
    return {
        "connected": connected,
        "status": "connected" if connected else (connection.get("status") or "disconnected"),
        "auto_reply_mode": connection.get("auto_reply_mode") or "off",
        "skip_one_star": bool(connection.get("skip_one_star", True)),
        "skip_angry": bool(connection.get("skip_angry", True)),
        "agent_instructions": connection.get("agent_instructions") or "",
        "active_location_id": connection.get("active_location_id"),
        "connected_at": connection.get("connected_at"),
        "locations": [_public_location(row) for row in list_gbp_locations(client_id)],
    }


def _creds(client_id: str):
    return ensure_gbp_credentials(client_id)


def _location_or_400(client_id: str, location_id: str | None) -> dict:
    try:
        return require_selected_location(client_id, location_id)
    except GbpApiError as exc:
        raise _google(exc) from exc


def _parse_range(start_date: str, end_date: str):
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD.") from exc
    if end < start:
        raise HTTPException(status_code=400, detail="End date is before the start date.")
    return start, end


def _cache_profile(client_id: str, row: dict, location: dict) -> None:
    latlng = location.get("latlng") or {}
    metadata = location.get("metadata") or {}
    upsert_gbp_location(
        client_id,
        row["location_id"],
        {
            **row,
            "title": location.get("title") or row.get("title") or "",
            "address": format_address(location.get("storefrontAddress")) or row.get("address") or "",
            "profile": location,
            "place_id": metadata.get("placeId") or row.get("place_id") or "",
            "latitude": latlng.get("latitude", row.get("latitude")),
            "longitude": latlng.get("longitude", row.get("longitude")),
            "synced_at": datetime.now(timezone.utc).isoformat(),
        },
    )


@router.post("/gbp.connection.get")
def gbp_connection_get(body: schemas.GbpClientRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    return _bundle(body.client_id)


@router.post("/gbp.disconnect")
def gbp_disconnect(body: schemas.GbpClientRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    existing = get_gbp_connection(body.client_id) or {}
    existing["google_credentials"] = {}
    existing["status"] = "disconnected"
    save_gbp_connection(body.client_id, existing)
    return _bundle(body.client_id)


@router.post("/gbp.locations.available")
def gbp_locations_available(body: schemas.GbpClientRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    try:
        sync_managed_locations(body.client_id, _creds(body.client_id))
    except GbpApiError as exc:
        raise _google(exc) from exc
    return _bundle(body.client_id)


@router.post("/gbp.locations.select")
def gbp_locations_select(body: schemas.GbpLocationSelectRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    known = {row.get("location_id") for row in list_gbp_locations(body.client_id)}
    chosen = [item for item in body.location_ids if item in known]
    set_gbp_location_selection(body.client_id, chosen)
    connection = get_gbp_connection(body.client_id) or {"client_id": body.client_id, "status": "connected"}
    active = connection.get("active_location_id")
    if active not in chosen:
        connection["active_location_id"] = chosen[0] if chosen else None
        save_gbp_connection(body.client_id, connection)
    return _bundle(body.client_id)


@router.post("/gbp.locations.set-active")
def gbp_locations_set_active(body: schemas.GbpActiveLocationRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = get_gbp_location(body.client_id, body.location_id)
    if not row or not row.get("selected"):
        raise HTTPException(status_code=404, detail="Selected Google Business location was not found.")
    connection = get_gbp_connection(body.client_id) or {}
    connection["active_location_id"] = body.location_id
    save_gbp_connection(body.client_id, connection)
    return _bundle(body.client_id)


@router.post("/gbp.profile.get")
def gbp_profile_get(body: schemas.GbpActiveLocationRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = _location_or_400(body.client_id, body.location_id)
    try:
        location = get_location(_creds(body.client_id), row.get("location_name") or row["location_id"])
    except GbpApiError as exc:
        raise _google(exc) from exc
    _cache_profile(body.client_id, row, location)
    metadata = location.get("metadata") or {}
    appointment_uri = ""
    appointment_error = ""
    try:
        link = appointment_link(list_place_action_links(_creds(body.client_id), row["location_id"]))
        appointment_uri = (link or {}).get("uri") or ""
    except GbpApiError as exc:
        if "place actions" in exc.message.lower() or "mybusinessplaceactions" in exc.message.lower():
            appointment_error = (
                "Appointment links need the My Business Place Actions API enabled on this Google Cloud project."
            )
        else:
            appointment_error = exc.message
    return {
        "location_id": row["location_id"],
        "address_readonly": format_address(location.get("storefrontAddress")),
        "pending": bool(metadata.get("hasPendingEdits")),
        "appointment_uri": appointment_uri,
        "appointment_error": appointment_error,
        "location": location,
    }


@router.post("/gbp.profile.patch")
def gbp_profile_patch(body: schemas.GbpProfilePatchRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = _location_or_400(body.client_id, body.location_id)
    if not body.update_mask and not body.update_appointment:
        raise HTTPException(status_code=400, detail="No profile fields to update.")
    location = body.location or {}
    mask = ""
    try:
        if body.update_mask:
            mask, payload = build_location_patch(body.update_mask, location)
            location = patch_location(
                _creds(body.client_id),
                row.get("location_name") or row["location_id"],
                payload,
                mask,
            )
            _cache_profile(body.client_id, row, location)
        if body.update_appointment:
            save_appointment_link(_creds(body.client_id), row["location_id"], body.appointment_uri)
    except GbpApiError as exc:
        raise _google(exc) from exc
    metadata = location.get("metadata") or {}
    return {
        "location_id": row["location_id"],
        "update_mask": mask,
        "pending": bool(metadata.get("hasPendingEdits")),
        "appointment_uri": body.appointment_uri.strip() if body.update_appointment else "",
        "location": location,
    }


@router.post("/gbp.categories.search")
def gbp_categories_search(body: schemas.GbpCategorySearchRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    try:
        categories = search_categories(_creds(body.client_id), body.query.strip(), body.region_code or "IN")
    except GbpApiError as exc:
        raise _google(exc) from exc
    return {
        "categories": [
            {"name": item.get("name"), "display_name": item.get("displayName") or item.get("name")}
            for item in categories
        ]
    }


def _filter_reviews(payload: dict, rating: int | None, unanswered_only: bool) -> dict:
    reviews = []
    for review in payload.get("reviews") or []:
        if unanswered_only and review.get("reviewReply"):
            continue
        if rating:
            from backend.tg.services.gbp_replies import review_star

            if review_star(review) != rating:
                continue
        reviews.append(review)
    return {
        "reviews": reviews,
        "average_rating": payload.get("averageRating"),
        "total_review_count": payload.get("totalReviewCount"),
        "next_page_token": payload.get("nextPageToken"),
    }


@router.post("/gbp.reviews.list")
def gbp_reviews_list(body: schemas.GbpReviewsListRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = _location_or_400(body.client_id, body.location_id)
    try:
        payload = list_reviews(
            _creds(body.client_id),
            row["account_id"],
            row["location_id"],
            page_token=body.page_token,
        )
    except GbpApiError as exc:
        raise _google(exc) from exc
    result = _filter_reviews(payload, body.rating, body.unanswered_only)
    result["location_id"] = row["location_id"]
    return result


@router.post("/gbp.reviews.all")
def gbp_reviews_all(body: schemas.GbpReviewsListRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = _location_or_400(body.client_id, body.location_id)
    try:
        payload = list_all_reviews(_creds(body.client_id), row["account_id"], row["location_id"])
    except GbpApiError as exc:
        raise _google(exc) from exc
    result = _filter_reviews(payload, body.rating, body.unanswered_only)
    result["location_id"] = row["location_id"]
    result["complete"] = bool(payload.get("complete"))
    result["pages"] = payload.get("pages") or 1
    return result


@router.post("/gbp.reviews.reply")
def gbp_reviews_reply(body: schemas.GbpReviewReplyRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    comment = (body.comment or "").strip()
    if not comment:
        raise HTTPException(status_code=400, detail="Reply text is required.")
    try:
        reply = update_review_reply(_creds(body.client_id), body.review_name, comment)
    except GbpApiError as exc:
        raise _google(exc) from exc
    return {"review_name": body.review_name, "reply": reply}


@router.post("/gbp.reviews.reply.delete")
def gbp_reviews_reply_delete(body: schemas.GbpReviewReplyDeleteRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    try:
        delete_review_reply(_creds(body.client_id), body.review_name)
    except GbpApiError as exc:
        raise _google(exc) from exc
    return {"review_name": body.review_name, "deleted": True}


@router.post("/gbp.reviews.drafts.list")
def gbp_review_drafts_list(body: schemas.GbpClientRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    return {"drafts": list_gbp_review_drafts(body.client_id)}


@router.post("/gbp.reviews.drafts.publish")
def gbp_review_drafts_publish(body: schemas.GbpDraftPublishRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    draft = get_gbp_review_draft(body.draft_id)
    if not draft or draft.get("client_id") != body.client_id:
        raise HTTPException(status_code=404, detail="Review draft not found.")
    comment = (body.comment or draft.get("reply") or "").strip()
    if not comment:
        raise HTTPException(status_code=400, detail="Reply text is required.")
    try:
        update_review_reply(_creds(body.client_id), draft["review_name"], comment)
    except GbpApiError as exc:
        raise _google(exc) from exc
    now = datetime.now(timezone.utc).isoformat()
    saved = save_gbp_review_draft(
        body.draft_id,
        {**draft, "status": "published", "reply": comment, "published_at": now, "updated_at": now},
    )
    return saved


@router.post("/gbp.settings.save")
def gbp_settings_save(body: schemas.GbpSettingsRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    if body.auto_reply_mode not in {"off", "human_review", "fully_automatic"}:
        raise HTTPException(status_code=400, detail="Unknown auto-reply mode.")
    connection = get_gbp_connection(body.client_id) or {"client_id": body.client_id}
    connection["auto_reply_mode"] = body.auto_reply_mode
    connection["skip_one_star"] = body.skip_one_star
    connection["skip_angry"] = body.skip_angry
    connection["agent_instructions"] = (body.agent_instructions or "").strip()[:2000]
    save_gbp_connection(body.client_id, connection)
    return _bundle(body.client_id)


@router.post("/gbp.posts.list")
def gbp_posts_list(body: schemas.GbpActiveLocationRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = _location_or_400(body.client_id, body.location_id)
    try:
        posts = list_local_posts(_creds(body.client_id), row["account_id"], row["location_id"])
    except GbpApiError as exc:
        raise _google(exc) from exc
    return {"location_id": row["location_id"], "posts": posts}


@router.post("/gbp.posts.create")
def gbp_posts_create(body: schemas.GbpPostWriteRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = _location_or_400(body.client_id, body.location_id)
    from backend.tg.services.gbp_posts import ensure_gbp_summary_limit

    summary = ensure_gbp_summary_limit((body.summary or "").strip())
    if not summary:
        raise HTTPException(status_code=400, detail="Post text is required.")
    try:
        payload = build_local_post_body(
            summary=summary,
            topic_type=body.topic_type,
            source_url=body.source_url,
            cta_type=body.cta_type,
            cta_url=body.cta_url,
            event_title=body.event_title,
            event_start=body.event_start,
            event_end=body.event_end,
            coupon_code=body.coupon_code,
        )
        post = create_local_post(_creds(body.client_id), row["account_id"], row["location_id"], payload)
    except GbpApiError as exc:
        raise _google(exc) from exc
    return {"post": post}


@router.post("/gbp.posts.image")
async def gbp_posts_image(
    client_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    _require_client(client_id, current_user["username"])
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Image file is empty.")
    name = f"{uuid.uuid4().hex}-{file.filename or 'post.jpg'}"
    try:
        url = upload_bytes(f"gbp/{client_id}", name, data, file.content_type or "image/jpeg")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail=f"Could not store a public image URL for the Google post: {exc}",
        ) from exc
    return {"source_url": url}


@router.post("/gbp.posts.patch")
def gbp_posts_patch(body: schemas.GbpPostWriteRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    if not body.post_name:
        raise HTTPException(status_code=400, detail="Post name is required.")
    summary = (body.summary or "").strip()
    if not summary:
        raise HTTPException(status_code=400, detail="Post text is required.")
    try:
        post = patch_local_post(
            _creds(body.client_id),
            body.post_name,
            {"summary": summary},
            "summary",
        )
    except GbpApiError as exc:
        raise _google(exc) from exc
    return {"post": post}


@router.post("/gbp.posts.delete")
def gbp_posts_delete(body: schemas.GbpNamedDeleteRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    try:
        delete_local_post(_creds(body.client_id), body.name)
    except GbpApiError as exc:
        raise _google(exc) from exc
    return {"deleted": True}


@router.post("/gbp.media.list")
def gbp_media_list(body: schemas.GbpActiveLocationRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = _location_or_400(body.client_id, body.location_id)
    try:
        media = list_media(_creds(body.client_id), row["account_id"], row["location_id"])
    except GbpApiError as exc:
        raise _google(exc) from exc
    return {"location_id": row["location_id"], "media": media}


@router.post("/gbp.media.upload")
async def gbp_media_upload(
    client_id: str = Form(...),
    location_id: str = Form(...),
    category: str = Form("ADDITIONAL"),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    _require_client(client_id, current_user["username"])
    row = _location_or_400(client_id, location_id)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Media file is empty.")
    allowed = {
        "COVER",
        "PROFILE",
        "LOGO",
        "EXTERIOR",
        "INTERIOR",
        "PRODUCT",
        "AT_WORK",
        "FOOD_AND_DRINK",
        "MENU",
        "COMMON_AREA",
        "ROOMS",
        "TEAMS",
        "ADDITIONAL",
    }
    chosen = (category or "ADDITIONAL").upper()
    if chosen not in allowed:
        raise HTTPException(status_code=400, detail="Unknown media category.")
    try:
        item = upload_location_media(
            _creds(client_id),
            row["account_id"],
            row["location_id"],
            data,
            file.content_type or "image/jpeg",
            chosen,
        )
    except GbpApiError as exc:
        raise _google(exc) from exc
    return {"media": item}


@router.post("/gbp.media.delete")
def gbp_media_delete(body: schemas.GbpNamedDeleteRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    try:
        delete_media(_creds(body.client_id), body.name)
    except GbpApiError as exc:
        raise _google(exc) from exc
    return {"deleted": True}


def _performance_for(creds, rows: list[dict], start, end) -> dict:
    payloads = []
    errors = []
    for row in rows:
        try:
            payloads.append(fetch_daily_metrics(creds, row["location_id"], start, end))
        except GbpApiError as exc:
            errors.append({"location_id": row.get("location_id"), "detail": exc.message})
    merged = merge_metric_payloads(payloads)
    return {**merged, "summary": rollup_labels(merged.get("totals") or {}), "errors": errors}


@router.post("/gbp.performance.get")
def gbp_performance_get(body: schemas.GbpPerformanceRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    start, end = _parse_range(body.start_date, body.end_date)
    if body.location_id:
        rows = [_location_or_400(body.client_id, body.location_id)]
    else:
        rows = [row for row in list_gbp_locations(body.client_id) if row.get("selected")]
        if not rows:
            raise HTTPException(status_code=400, detail="Choose at least one Google Business location first.")
    creds = _creds(body.client_id)
    current = _performance_for(creds, rows, start, end)
    prev_start, prev_end = previous_window(start, end)
    previous = _performance_for(creds, rows, prev_start, prev_end)
    return {
        "start_date": body.start_date,
        "end_date": body.end_date,
        "previous_start_date": prev_start.isoformat(),
        "previous_end_date": prev_end.isoformat(),
        "location_ids": [row["location_id"] for row in rows],
        "current": current,
        "previous": previous,
    }


@router.post("/gbp.performance.keywords")
def gbp_performance_keywords(body: schemas.GbpPerformanceRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    start, end = _parse_range(body.start_date, body.end_date)
    if body.location_id:
        rows = [_location_or_400(body.client_id, body.location_id)]
    else:
        rows = [row for row in list_gbp_locations(body.client_id) if row.get("selected")]
    creds = _creds(body.client_id)
    combined: dict[str, float] = {}
    errors = []
    for row in rows:
        try:
            for item in fetch_search_keywords(creds, row["location_id"], start, end):
                key = item["keyword"]
                combined[key] = combined.get(key, 0) + item["impressions"]
        except GbpApiError as exc:
            errors.append({"location_id": row.get("location_id"), "detail": exc.message})
    keywords = [{"keyword": key, "impressions": value} for key, value in combined.items()]
    keywords.sort(key=lambda item: item["impressions"], reverse=True)
    return {"keywords": keywords, "errors": errors}


@router.post("/gbp.overview.get")
def gbp_overview_get(body: schemas.GbpActiveLocationRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = _location_or_400(body.client_id, body.location_id or None)
    creds = _creds(body.client_id)
    reviews = {}
    performance = {}
    try:
        reviews = list_reviews(creds, row["account_id"], row["location_id"], page_size=50)
    except GbpApiError as exc:
        reviews = {"error": exc.message}
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    start = end - timedelta(days=29)
    try:
        current = fetch_daily_metrics(creds, row["location_id"], start, end)
        prev_start, prev_end = previous_window(start, end)
        previous = fetch_daily_metrics(creds, row["location_id"], prev_start, prev_end)
        performance = {
            "current": rollup_labels(current.get("totals") or {}),
            "previous": rollup_labels(previous.get("totals") or {}),
        }
    except GbpApiError as exc:
        performance = {"error": exc.message}
    unanswered = 0
    for review in reviews.get("reviews") or []:
        if not review.get("reviewReply"):
            unanswered += 1
    cached = row.get("profile") or {}
    return {
        "location": _public_location(row),
        "title": cached.get("title") or row.get("title"),
        "average_rating": reviews.get("averageRating"),
        "total_review_count": reviews.get("totalReviewCount"),
        "unanswered_on_page": unanswered,
        "reviews_error": reviews.get("error"),
        "performance": performance,
    }


@router.post("/gbp.optimize.audit")
def gbp_optimize_audit(body: schemas.GbpActiveLocationRequest, current_user: dict = Depends(get_current_user)):
    client = _require_client(body.client_id, current_user["username"])
    row = _location_or_400(body.client_id, body.location_id)
    creds = _creds(body.client_id)
    try:
        location = get_location(creds, row.get("location_name") or row["location_id"])
        media = list_media(creds, row["account_id"], row["location_id"])
    except GbpApiError as exc:
        raise _google(exc) from exc
    _cache_profile(body.client_id, row, location)
    appointment_uri = ""
    appointment_error = ""
    try:
        link = appointment_link(list_place_action_links(creds, row["location_id"]))
        appointment_uri = (link or {}).get("uri") or ""
    except GbpApiError as exc:
        appointment_error = exc.message
    keywords = []
    keywords_error = ""
    start, end = keyword_month_window(datetime.now(timezone.utc).date())
    try:
        keywords = fetch_search_keywords(creds, row["location_id"], start, end)
    except GbpApiError as exc:
        keywords_error = exc.message
    try:
        topics = fetch_topics(body.client_id)
    except Exception:  # noqa: BLE001
        topics = []
    specialty = client.get("specialty") or ""
    try:
        hits = search_categories(creds, (specialty or location.get("title") or "").strip()[:80] or "clinic")
    except GbpApiError:
        hits = []
    model_draft, draft_error = request_profile_draft(
        location=location,
        specialty=specialty,
        client_description=client.get("description") or "",
        topics=topics,
        keywords=keywords,
        category_hits=hits,
    )
    metadata = location.get("metadata") or {}
    return build_audit(
        location=location,
        media=media,
        appointment_uri=appointment_uri,
        appointment_error=appointment_error,
        specialty=specialty,
        client_description=client.get("description") or "",
        topics=topics,
        keywords=keywords,
        keywords_error=keywords_error,
        category_hits=hits,
        model_draft=model_draft,
        draft_error=draft_error,
        pending=bool(metadata.get("hasPendingEdits")),
    )


def _public_optimize(optimize: dict) -> dict:
    keywords = []
    for row in optimize.get("keywords") or []:
        keywords.append(
            {
                "phrase": row.get("phrase") or "",
                "volume": row.get("volume"),
                "service": row.get("service") or "",
                "demand_location": row.get("demand_location") or "",
                "demand_is_country": bool(row.get("demand_is_country")),
                "sentence": row.get("sentence") or "",
                "clinic_rank": row.get("clinic_rank"),
                "points": [
                    {
                        "id": point.get("id"),
                        "km": point.get("km"),
                        "direction": point.get("direction"),
                        "lat": point.get("lat"),
                        "lng": point.get("lng"),
                        "rank": point.get("rank"),
                        "found": bool(point.get("found")),
                        "error": point.get("error") or "",
                        "competitors": point.get("competitors") or [],
                    }
                    for point in row.get("points") or []
                ],
                "competitors": row.get("competitors") or [],
                "demand_status": row.get("demand_status") or "",
                "broader_volume": row.get("broader_volume"),
                "opportunity_score": row.get("opportunity_score"),
                "weighted_gap": row.get("weighted_gap"),
            }
        )
    listing = optimize.get("listing")
    recommendations = drop_add_already_listed(
        [
            dict(item)
            for item in (optimize.get("service_recommendations") or [])
            if item.get("action") in {"ADD", "REPLACE"}
        ],
        optimize.get("listing") if isinstance(optimize.get("listing"), dict) else {},
    )
    potential = optimize.get("potential_score") or None
    if isinstance(listing, dict) and listing.get("sections"):
        from backend.tg.services.gbp_opportunities import projected_listing_score

        potential = projected_listing_score(listing, description=optimize.get("suggested_description") or "")
        for item in recommendations:
            added = [item["proposed_name"]] if item.get("action") == "ADD" and item.get("proposed_name") else []
            item_projection = projected_listing_score(listing, added_services=added)
            if item_projection:
                item["current_score"] = item_projection["current"]
                item["potential_score"] = item_projection["potential"]
            else:
                item.pop("current_score", None)
                item.pop("potential_score", None)
    if isinstance(potential, dict):
        potential = {"current": potential.get("current"), "potential": potential.get("potential")}
    if isinstance(listing, dict):
        listing = soften_audit_listing(
            {**listing, "services": {**(listing.get("services") or {}), "suggested": []}}
        )
    return {
        "listing": listing,
        "listing_checked_at": optimize.get("listing_checked_at"),
        "gaps_status": optimize.get("gaps_status") or "idle",
        "gaps_checked_at": optimize.get("gaps_checked_at"),
        "suggested_title": optimize.get("suggested_title") or "",
        "suggested_description": optimize.get("suggested_description") or "",
        "instruction": optimize.get("instruction") or "",
        "not_used": optimize.get("not_used") or [],
        "keywords": keywords,
        "service_recommendations": recommendations,
        "potential_score": potential,
        "last_error": optimize.get("last_error") or "",
    }


LISTING_FRESH_SECONDS = 30


def _listing_is_fresh(optimize: dict, *, seconds: int = LISTING_FRESH_SECONDS) -> bool:
    raw = str((optimize or {}).get("listing_checked_at") or "").strip()
    if not raw:
        return False
    try:
        checked = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - checked < timedelta(seconds=seconds)


def _collect_listing_audit(
    client: dict,
    row: dict,
    creds,
    *,
    with_draft: bool,
    include_search_keywords: bool = True,
) -> dict:
    location = get_location(creds, row.get("location_name") or row["location_id"])
    media = list_media(creds, row["account_id"], row["location_id"])
    _cache_profile(row["client_id"] if row.get("client_id") else "", row, location)
    appointment_uri = ""
    appointment_error = ""
    try:
        link = appointment_link(list_place_action_links(creds, row["location_id"]))
        appointment_uri = (link or {}).get("uri") or ""
    except GbpApiError as exc:
        appointment_error = exc.message
    keywords = []
    keywords_error = ""
    if include_search_keywords:
        start, end = keyword_month_window(datetime.now(timezone.utc).date())
        try:
            keywords = fetch_search_keywords(creds, row["location_id"], start, end)
        except GbpApiError as exc:
            keywords_error = exc.message
    topics = []
    try:
        topics = fetch_topics(row.get("client_id") or "")
    except Exception:  # noqa: BLE001
        topics = []
    specialty = client.get("specialty") or ""
    hits = []
    model_draft, draft_error = {}, ""
    if with_draft:
        try:
            hits = search_categories(creds, (specialty or location.get("title") or "").strip()[:80] or "clinic")
        except GbpApiError:
            hits = []
        model_draft, draft_error = request_profile_draft(
            location=location,
            specialty=specialty,
            client_description=client.get("description") or "",
            topics=topics,
            keywords=keywords,
            category_hits=hits,
        )
    metadata = location.get("metadata") or {}
    audit = build_audit(
        location=location,
        media=media,
        appointment_uri=appointment_uri,
        appointment_error=appointment_error,
        specialty=specialty,
        client_description=client.get("description") or "",
        topics=topics,
        keywords=keywords,
        keywords_error=keywords_error,
        category_hits=hits,
        model_draft=model_draft,
        draft_error=draft_error,
        pending=bool(metadata.get("hasPendingEdits")),
    )
    audit["title"] = location.get("title") or ""
    return {"audit": audit, "location": location, "topics": topics, "keywords": keywords}


def _sync_optimize_listing(client: dict, row: dict, *, force: bool, include_search_keywords: bool) -> dict:
    """Refresh completeness from Google unless the saved listing is still fresh."""
    client_id = row.get("client_id") or client.get("id") or ""
    location_id = row["location_id"]
    current = get_gbp_optimize(client_id, location_id)
    if not force and _listing_is_fresh(current):
        return current
    collected = _collect_listing_audit(
        client,
        row,
        _creds(client_id),
        with_draft=False,
        include_search_keywords=include_search_keywords,
    )
    merge_gbp_optimize(
        client_id,
        location_id,
        {
            "listing": collected["audit"],
            "listing_checked_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return get_gbp_optimize(client_id, location_id)


@router.post("/gbp.optimize.get")
def gbp_optimize_get(body: schemas.GbpActiveLocationRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    _location_or_400(body.client_id, body.location_id)
    return _public_optimize(get_gbp_optimize(body.client_id, body.location_id))


@router.post("/gbp.optimize.pdf")
def gbp_optimize_pdf(body: schemas.GbpActiveLocationRequest, current_user: dict = Depends(get_current_user)):
    """Client-facing Optimize proposal PDF. Current listing fields come from live Google."""
    from backend.tg.services.gbp_optimize_pdf import build_or_fetch_proposal_pdf

    client = _require_client(body.client_id, current_user["username"])
    row = {**_location_or_400(body.client_id, body.location_id), "client_id": body.client_id}
    try:
        optimize = _sync_optimize_listing(client, row, force=True, include_search_keywords=False)
        row = get_gbp_location(body.client_id, body.location_id) or row
    except GbpApiError:
        optimize = get_gbp_optimize(body.client_id, body.location_id)
    try:
        pdf_bytes, filename = build_or_fetch_proposal_pdf(
            client,
            row,
            optimize,
            client_id=body.client_id,
            location_id=body.location_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/gbp.optimize.refresh")
def gbp_optimize_refresh(body: schemas.GbpOptimizeRefreshRequest, current_user: dict = Depends(get_current_user)):
    """Reread Google and replace only the completeness snapshot."""
    client = _require_client(body.client_id, current_user["username"])
    row = {**_location_or_400(body.client_id, body.location_id), "client_id": body.client_id}
    try:
        optimize = _sync_optimize_listing(
            client,
            row,
            force=body.force,
            include_search_keywords=body.include_search_keywords,
        )
    except GbpApiError as exc:
        raise _google(exc) from exc
    return _public_optimize(optimize)


def _execute_optimize(client_id: str, location_id: str, instruction: str, latitude, longitude) -> None:
    from backend.tg.services.gbp_optimize_run import run_gap_optimize

    try:
        _execute_optimize_body(client_id, location_id, instruction, latitude, longitude, run_gap_optimize)
    except Exception as exc:  # noqa: BLE001
        message = getattr(exc, "message", None) or str(exc)
        print(f"[gbp] error {message}", flush=True)
        traceback.print_exc()
        merge_gbp_optimize(
            client_id,
            location_id,
            {
                "gaps_status": "error",
                "last_error": message,
                "gaps_checked_at": datetime.now(timezone.utc).isoformat(),
            },
        )


def _execute_optimize_body(client_id: str, location_id: str, instruction: str, latitude, longitude, run_gap_optimize) -> None:
    row = get_gbp_location(client_id, location_id) or {}
    profile = row.get("profile") if isinstance(row.get("profile"), dict) else {}
    latlng = profile.get("latlng") or {}
    lat = latitude if latitude is not None else row.get("latitude", latlng.get("latitude"))
    lng = longitude if longitude is not None else row.get("longitude", latlng.get("longitude"))
    if lat is None or lng is None:
        for keyword in (row.get("optimize") or {}).get("keywords") or []:
            for point in keyword.get("points") or []:
                if point.get("km") == 0 and point.get("lat") is not None and point.get("lng") is not None:
                    lat = float(point["lat"])
                    lng = float(point["lng"])
                    break
            if lat is not None and lng is not None:
                break
    topics = []
    try:
        topics = fetch_topics(client_id)
    except Exception:  # noqa: BLE001
        topics = []
    if row.get("location_name"):
        try:
            profile = get_location(_creds(client_id), row.get("location_name") or location_id)
            _cache_profile(client_id, {**row, "client_id": client_id}, profile)
        except GbpApiError:
            profile = profile
    latlng = profile.get("latlng") or latlng
    if latitude is None and latlng.get("latitude") is not None:
        lat = latlng.get("latitude")
    if longitude is None and latlng.get("longitude") is not None:
        lng = latlng.get("longitude")
    reported = []
    try:
        creds = _creds(client_id)
        start, end = keyword_month_window(datetime.now(timezone.utc).date())
        reported = [
            {"keyword": item.get("keyword"), "impressions": item.get("impressions") or 0}
            for item in fetch_search_keywords(creds, location_id, start, end)
            if item.get("keyword")
        ]
        listing = dict((get_gbp_optimize(client_id, location_id) or {}).get("listing") or {})
        listing["keywords"] = reported
        merge_gbp_optimize(client_id, location_id, {"listing": listing})
    except Exception:  # noqa: BLE001
        reported = []
    from backend.tg.services.gbp_opportunities import openai_json

    run_gap_optimize(
        client_id,
        location_id,
        location=profile or {"title": row.get("title") or ""},
        topics=topics,
        reported=[item for item in reported if item],
        instruction=instruction,
        lat=lat,
        lng=lng,
        place_id=row.get("place_id") or ((profile.get("metadata") or {}).get("placeId") or ""),
        phone=((profile.get("phoneNumbers") or {}).get("primaryPhone") or ""),
        completer=openai_json,
    )


@router.post("/gbp.optimize.run")
def gbp_optimize_run(
    body: schemas.GbpOptimizeRunRequest,
    background: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """Start the search-gap job. Completeness snapshot is left as it is."""
    _require_client(body.client_id, current_user["username"])
    _location_or_400(body.client_id, body.location_id)
    merge_gbp_optimize(
        body.client_id,
        body.location_id,
        {"gaps_status": "running", "last_error": "", "instruction": body.instruction or ""},
    )
    background.add_task(
        _execute_optimize,
        body.client_id,
        body.location_id,
        body.instruction or "",
        body.latitude,
        body.longitude,
    )
    return _public_optimize(get_gbp_optimize(body.client_id, body.location_id))


@router.post("/gbp.optimize.apply-score")
def gbp_optimize_apply_score(body: schemas.GbpOptimizeApplyRequest, current_user: dict = Depends(get_current_user)):
    """Save the completeness score after Apply. The number stays in our database."""
    from backend.tg.services.gbp_opportunities import apply_projection, projected_listing_score

    _require_client(body.client_id, current_user["username"])
    _location_or_400(body.client_id, body.location_id)
    optimize = get_gbp_optimize(body.client_id, body.location_id)
    listing = dict(optimize.get("listing") or {})
    projection = projected_listing_score(
        listing,
        description=body.description,
        added_services=body.added_services,
    )
    if projection:
        listing = apply_projection(listing, projection)
    if body.description:
        description = dict(listing.get("description") or {})
        description["current"] = body.description
        description["suggestion"] = ""
        listing["description"] = description
    if body.added_services:
        services = dict(listing.get("services") or {})
        current = list(services.get("current") or [])
        for name in body.added_services:
            if name and not any((item.get("displayName") or "").lower() == name.lower() for item in current):
                current.append({"displayName": name, "description": ""})
        services["current"] = current
        listing["services"] = services
    merge_gbp_optimize(
        body.client_id,
        body.location_id,
        {"listing": listing, "potential_score": None, "suggested_description": body.description or optimize.get("suggested_description") or ""},
    )
    return _public_optimize(get_gbp_optimize(body.client_id, body.location_id))


_APPLY_KINDS = {"description", "title", "service", "category"}
_IST = timezone(timedelta(hours=5, minutes=30))


def _clip(value: str, limit: int = 2000) -> str:
    return str(value or "").strip()[:limit]


@router.post("/gbp.optimize.apply-log")
def gbp_optimize_apply_log(body: schemas.GbpApplyLogRequest, current_user: dict = Depends(get_current_user)):
    """Remember an Optimize Apply. A later Optimize run does not clear this list."""
    _require_client(body.client_id, current_user["username"])
    _location_or_400(body.client_id, body.location_id)
    kind = (body.kind or "").strip().lower()
    if kind not in _APPLY_KINDS:
        raise HTTPException(status_code=400, detail="Unknown apply type.")
    now = datetime.now(_IST)
    item = {
        "applied_on": now.date().isoformat(),
        "applied_at": now.isoformat(),
        "kind": kind,
        "before": _clip(body.before),
        "after": _clip(body.after),
        "summary": _clip(body.summary, 240) or f"Updated the {kind}",
    }
    history = append_gbp_apply_history(body.client_id, body.location_id, item)
    return {"apply_history": history}


def _optional_range(start_date: str, end_date: str):
    if not (start_date or "").strip() and not (end_date or "").strip():
        return None
    start, end = _parse_range(start_date, end_date)
    if (end - start).days + 1 > 540:
        raise HTTPException(status_code=400, detail="Pick a range of 18 months or less.")
    return start, end


def _metric_rows(summary_a: dict, summary_b: dict, days_a: int, days_b: int) -> list[dict]:
    specs = [
        ("search_views", "Search views", "search_impressions"),
        ("maps_views", "Maps views", "maps_impressions"),
        ("calls", "Calls", "calls"),
        ("website_clicks", "Website clicks", "website_clicks"),
        ("directions", "Direction requests", "direction_requests"),
    ]
    rows = []
    for row_id, label, key in specs:
        change = percent_change(summary_a.get(key) or 0, summary_b.get(key) or 0, days_a, days_b)
        rows.append({"id": row_id, "label": label, "a": summary_a.get(key) or 0, "b": summary_b.get(key) or 0, **change})
    for row_id, label, key in (("bookings", "Bookings", "bookings"), ("chat", "Chat clicks", "chat_clicks")):
        left = summary_a.get(key) or 0
        right = summary_b.get(key) or 0
        if left or right:
            change = percent_change(left, right, days_a, days_b)
            rows.append({"id": row_id, "label": label, "a": left, "b": right, **change})
    views_a = (summary_a.get("search_impressions") or 0) + (summary_a.get("maps_impressions") or 0)
    views_b = (summary_b.get("search_impressions") or 0) + (summary_b.get("maps_impressions") or 0)
    if views_a and views_b:
        actions = ("website_clicks", "calls", "direction_requests", "chat_clicks", "bookings")
        rate_a = sum(summary_a.get(key) or 0 for key in actions) / views_a
        rate_b = sum(summary_b.get(key) or 0 for key in actions) / views_b
        change = percent_change(rate_a, rate_b, days_a, days_a)
        rows.append({
            "id": "action_rate",
            "label": "Views that led to a call, click, or direction",
            "a": round(rate_a * 100, 1),
            "b": round(rate_b * 100, 1),
            "percent": change["percent"],
            "basis": "rate",
            "days_a": days_a,
            "days_b": days_b,
            "unit": "percent",
        })
    return rows


@router.post("/gbp.results.get")
def gbp_results_get(body: schemas.GbpResultsRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = _location_or_400(body.client_id, body.location_id)
    history = [item for item in (row.get("apply_history") or []) if isinstance(item, dict)]
    range_a = _optional_range(body.range_a_start, body.range_a_end)
    range_b = _optional_range(body.range_b_start, body.range_b_end)
    payload = {
        "location_id": row["location_id"],
        "apply_history": history,
        "range_a": None,
        "range_b": None,
        "rows": [],
        "error": "",
    }
    if not range_a or not range_b:
        return payload
    start = min(range_a[0], range_b[0])
    end = max(range_a[1], range_b[1])
    try:
        fetched = fetch_daily_metrics(_creds(body.client_id), row["location_id"], start, end)
    except GbpApiError as exc:
        payload["error"] = exc.message
        return payload
    series = fetched.get("series") or {}
    summary_a = rollup_labels(totals_between(series, range_a[0], range_a[1]))
    summary_b = rollup_labels(totals_between(series, range_b[0], range_b[1]))
    days_a = (range_a[1] - range_a[0]).days + 1
    days_b = (range_b[1] - range_b[0]).days + 1
    payload["range_a"] = {"start": range_a[0].isoformat(), "end": range_a[1].isoformat(), "days": days_a}
    payload["range_b"] = {"start": range_b[0].isoformat(), "end": range_b[1].isoformat(), "days": days_b}
    payload["rows"] = _metric_rows(summary_a, summary_b, days_a, days_b)
    return payload


@router.post("/gbp.reviews.themes")
def gbp_reviews_themes(body: schemas.GbpReviewThemesRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    reviews = []
    for item in (body.reviews or [])[:200]:
        if not isinstance(item, dict):
            continue
        reviews.append(
            {
                "starRating": item.get("star_rating") or item.get("starRating"),
                "comment": item.get("comment") or "",
            }
        )
    grouped = dynamic_review_themes(reviews)
    if isinstance(grouped, dict):
        return grouped
    return {"summary": "", "themes": grouped}


@router.post("/gbp.reviews.insights")
def gbp_reviews_insights(body: schemas.GbpActiveLocationRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = _location_or_400(body.client_id, body.location_id)
    try:
        payload = list_reviews(_creds(body.client_id), row["account_id"], row["location_id"], page_size=50)
    except GbpApiError as exc:
        raise _google(exc) from exc
    reviews = payload.get("reviews") or []
    skipped = [
        draft
        for draft in list_gbp_review_drafts(body.client_id, status="skipped")
        if draft.get("location_id") in {None, row["location_id"]}
    ]
    grouped = dynamic_review_themes(reviews)
    themes = grouped.get("themes") if isinstance(grouped, dict) else grouped
    insights = build_review_insights(reviews, skipped, themes)
    insights["location_id"] = row["location_id"]
    return insights


def _schedule_row(client_id: str, location_id: str) -> dict:
    return _location_or_400(client_id, location_id)


@router.post("/gbp.posts.schedule.get")
def gbp_posts_schedule_get(body: schemas.GbpActiveLocationRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = _schedule_row(body.client_id, body.location_id)
    return {"location_id": row["location_id"], "schedule": public_schedule(row.get("post_schedule"))}


@router.post("/gbp.posts.schedule.save")
def gbp_posts_schedule_save(body: schemas.GbpPostScheduleRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = _schedule_row(body.client_id, body.location_id)
    try:
        schedule = normalize_schedule(
            {
                "frequency": body.frequency,
                "selected_days": body.selected_days,
                "posts_per_day": body.posts_per_day,
                "autopublish": body.autopublish,
            },
            previous=row.get("post_schedule") or {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    upsert_gbp_location(body.client_id, row["location_id"], {**row, "post_schedule": schedule})
    return {"location_id": row["location_id"], "schedule": public_schedule(schedule)}


@router.post("/gbp.posts.drafts.list")
def gbp_posts_drafts_list(body: schemas.GbpActiveLocationRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = _schedule_row(body.client_id, body.location_id)
    rows = list_gbp_post_drafts(body.client_id, row["location_id"])
    drafts = [draft for draft in rows if draft.get("status") == "pending"]
    queue = [draft for draft in rows if draft.get("status") == "queued"]
    drafts.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    queue.sort(key=lambda item: (item.get("queue_order") if item.get("queue_order") is not None else 10**9, item.get("created_at") or ""))
    return {"location_id": row["location_id"], "drafts": drafts, "queue": queue}


@router.post("/gbp.posts.queue.add")
def gbp_posts_queue_add(body: schemas.GbpPostDraftRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    draft = get_gbp_post_draft(body.draft_id)
    if not draft or draft.get("client_id") != body.client_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    try:
        saved = enqueue_gbp_draft(body.client_id, draft, body.summary)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"draft": saved}


@router.post("/gbp.posts.queue.remove")
def gbp_posts_queue_remove(body: schemas.GbpPostDraftRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    draft = get_gbp_post_draft(body.draft_id)
    if not draft or draft.get("client_id") != body.client_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"draft": dequeue_gbp_draft(draft)}


@router.post("/gbp.posts.queue.reorder")
def gbp_posts_queue_reorder(body: schemas.GbpPostDraftRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = _schedule_row(body.client_id, body.location_id)
    saved = reorder_gbp_queue(body.client_id, row["location_id"], body.draft_ids or [])
    saved.sort(key=lambda item: item.get("queue_order") or 0)
    return {"queue": saved}


@router.post("/gbp.posts.drafts.generate")
def gbp_posts_drafts_generate(body: schemas.GbpActiveLocationRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    row = _schedule_row(body.client_id, body.location_id)
    count = body.posts_per_day or (row.get("post_schedule") or {}).get("posts_per_day") or 1
    try:
        kind = (body.topic_type or "STANDARD").upper()
        if kind in {"EVENT", "OFFER"} and not (body.event_start or "").strip():
            raise HTTPException(status_code=400, detail="Event and offer posts need a start date.")
        drafts = generate_location_drafts(
            body.client_id,
            row,
            _creds(body.client_id),
            count,
            references=body.reference_urls,
            topic_type=kind,
            event_title=body.event_title or "",
            event_start=body.event_start or "",
            event_end=body.event_end or "",
            coupon_code=body.coupon_code or "",
        )
    except GbpApiError as exc:
        raise _google(exc) from exc
    return {"drafts": drafts}


@router.post("/gbp.posts.drafts.save")
def gbp_posts_drafts_save(body: schemas.GbpPostDraftRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    draft = get_gbp_post_draft(body.draft_id)
    if not draft or draft.get("client_id") != body.client_id:
        raise HTTPException(status_code=404, detail="Post draft not found.")
    text = (body.summary if body.summary is not None else draft.get("summary") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Post text is required.")
    now = datetime.now(timezone.utc).isoformat()
    saved = save_gbp_post_draft(body.draft_id, {**draft, "summary": text, "updated_at": now})
    return {"draft": saved, "over_limit": len(text) > 500}


@router.post("/gbp.posts.drafts.publish")
def gbp_posts_drafts_publish(body: schemas.GbpPostDraftRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    draft = get_gbp_post_draft(body.draft_id)
    if not draft or draft.get("client_id") != body.client_id:
        raise HTTPException(status_code=404, detail="Post draft not found.")
    row = _schedule_row(body.client_id, draft.get("location_id") or body.location_id)
    try:
        saved = publish_gbp_draft(body.client_id, row, _creds(body.client_id), draft, body.summary)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GbpApiError as exc:
        raise _google(exc) from exc
    return saved


@router.post("/gbp.posts.drafts.discard")
def gbp_posts_drafts_discard(body: schemas.GbpPostDraftRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    draft = get_gbp_post_draft(body.draft_id)
    if not draft or draft.get("client_id") != body.client_id:
        raise HTTPException(status_code=404, detail="Post draft not found.")
    now = datetime.now(timezone.utc).isoformat()
    saved = save_gbp_post_draft(body.draft_id, {**draft, "status": "discarded", "updated_at": now})
    return saved


@router.post("/gbp.posts.drafts.retry-image")
def gbp_posts_drafts_retry_image(body: schemas.GbpPostDraftRequest, current_user: dict = Depends(get_current_user)):
    _require_client(body.client_id, current_user["username"])
    draft = get_gbp_post_draft(body.draft_id)
    if not draft or draft.get("client_id") != body.client_id:
        raise HTTPException(status_code=404, detail="Post draft not found.")
    url, error = generate_post_image(draft.get("summary") or "", body.client_id)
    now = datetime.now(timezone.utc).isoformat()
    saved = save_gbp_post_draft(
        body.draft_id,
        {**draft, "source_url": url, "image_error": error, "updated_at": now},
    )
    return saved


def run_gbp_auto_replies() -> dict:
    processed = []
    for connection in list_gbp_connections():
        mode = connection.get("auto_reply_mode") or "off"
        client_id = connection.get("client_id")
        if not client_id or mode == "off" or connection.get("status") != "connected":
            continue
        try:
            creds = ensure_gbp_credentials(client_id)
        except HTTPException as exc:
            processed.append({"client_id": client_id, "error": exc.detail})
            continue
        for location in list_gbp_locations(client_id):
            if not location.get("selected"):
                continue
            try:
                page = list_all_reviews(creds, location["account_id"], location["location_id"])
            except GbpApiError as exc:
                processed.append(
                    {"client_id": client_id, "location_id": location.get("location_id"), "error": exc.message}
                )
                continue
            for review in page.get("reviews") or []:
                if review.get("reviewReply"):
                    continue
                try:
                    outcome = handle_one_review(client_id, location, connection, review, creds)
                except GbpApiError as exc:
                    outcome = {
                        "client_id": client_id,
                        "location_id": location.get("location_id"),
                        "error": exc.message,
                    }
                processed.append({"client_id": client_id, **outcome})
    return {"processed": processed}


@router.post("/cron/gbp.reviews.auto-reply")
def cron_gbp_auto_reply(request: Request):
    secret = request.headers.get("X-Cron-Secret")
    if not secret or secret != "gravity-cron-secret":
        raise HTTPException(status_code=401, detail="Unauthorized cron trigger")
    return run_gbp_auto_replies()


@router.post("/cron/gbp.posts.run")
def cron_gbp_posts(request: Request):
    secret = request.headers.get("X-Cron-Secret")
    if not secret or secret != "gravity-cron-secret":
        raise HTTPException(status_code=401, detail="Unauthorized cron trigger")
    return run_scheduled_posts()
