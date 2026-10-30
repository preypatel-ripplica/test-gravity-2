from __future__ import annotations
import contextvars
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile, status

from backend.tg import schemas
from backend.tg.auth import get_current_user
from backend.tg.config import settings
from backend.tg.database import (
    append_content_video_posted_url,
    append_content_video_source_url,
    fetch_channel,
    fetch_client_doc,
    fetch_user,
    list_videos_for_channel,
    merge_preserved_video_fields,
    replace_channel_videos,
    update_video_fields,
)
from backend.tg.google_oauth import get_user_google_creds
from backend.tg.services.gcs_storage import upload_bytes
from backend.tg.services.youtube_api import (
    fetch_channel_analytics,
    fit_social_caption,
    publish_platforms,
    sync_videos_from_youtube,
)

router = APIRouter(tags=["video"])

UPLOADED_VIDEOS_DIR = Path(__file__).resolve().parent.parent.parent / "social_assets" / "uploaded_videos"
VIDEO_MIME_TYPES = {"video/mp4", "video/quicktime", "video/webm"}
VIDEO_EXTS = {".mp4", ".mov", ".webm"}


def _resolve_ids(
    username: str,
    client_id: str | None,
    channel_id: str | None,
) -> tuple[str, str]:
    user = fetch_user(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    cid = client_id or user.get("active_client_id")
    chid = channel_id or user.get("active_channel_id")
    if not cid or not chid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found.")
    if not fetch_client_doc(cid, username=username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{cid}' not found.",
        )
    if not fetch_channel(chid, client_id=cid, username=username):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel '{chid}' not found.",
        )
    return cid, chid


def _is_http_url(value: str | None) -> bool:
    return bool(value) and str(value).startswith("http")


def _facebook_public_url(page_id: str, video_id: str) -> str:
    """A page video link when Graph does not return permalink_url."""
    video_id = str(video_id or "").strip()
    page_id = str(page_id or "").strip()
    if not video_id:
        return ""
    if "_" in video_id:
        return f"https://www.facebook.com/{video_id}"
    if page_id:
        return f"https://www.facebook.com/{page_id}/videos/{video_id}"
    return f"https://www.facebook.com/watch/?v={video_id}"


def _post_result(result) -> tuple[str, str]:
    """Publish helpers return an id, or (id, permalink)."""
    if isinstance(result, tuple):
        post_id = str(result[0] or "")
        permalink = str(result[1] or "") if len(result) > 1 else ""
        return post_id, permalink
    return str(result or ""), ""


def _fetch_graph_permalink(url: str, params: dict) -> str:
    import requests

    try:
        resp = requests.get(url, params=params, timeout=20)
        if not resp.ok:
            return ""
        data = resp.json() or {}
        for key in ("permalink", "permalink_url"):
            value = str(data.get(key) or "").strip()
            if _is_http_url(value):
                return value
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to fetch permalink from {url}: {exc}")
    return ""


def _append_content_video_post_urls(
    *,
    client_id: str,
    channel_id: str,
    topic_id: str | None,
    language: str | None,
    video_id: str | None,
    ig_post_id: str | None,
    fb_post_id: str | None,
    drive_link: str | None = None,
    post_to_instagram: bool = False,
    post_to_facebook: bool = False,
    social_source_url: str | None = None,
    ig_permalink: str | None = None,
    fb_permalink: str | None = None,
) -> None:
    """Record watch/permalink URLs and pasted Drive/file source URLs. Skip if topic_id is missing."""
    from datetime import datetime, timezone

    if not topic_id:
        return
    posted_at = datetime.now(timezone.utc).isoformat()
    channel = fetch_channel(channel_id, client_id=client_id) or {}
    lang = language or channel.get("language") or None
    source_url = str(drive_link or "").strip()
    try:
        if source_url:
            if video_id:
                append_content_video_source_url(
                    client_id,
                    topic_id,
                    {
                        "url": source_url,
                        "kind": "youtube",
                        "channel_id": channel_id,
                        "language": lang,
                        "posted_at": posted_at,
                    },
                )
            if post_to_instagram or post_to_facebook:
                social_url = str(social_source_url or source_url or "").strip()
                if social_url:
                    append_content_video_source_url(
                        client_id,
                        topic_id,
                        {
                            "url": social_url,
                            "kind": "social",
                            "posted_at": posted_at,
                        },
                    )
        if video_id:
            append_content_video_posted_url(
                client_id,
                topic_id,
                "youtube",
                {
                    "channel_id": channel_id,
                    "language": lang,
                    "youtube_id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "posted_at": posted_at,
                },
            )
        if ig_post_id:
            from backend.tg.database import get_instagram_connection

            conn = get_instagram_connection(client_id) or {}
            permalink = str(ig_permalink or "").strip()
            if not _is_http_url(permalink):
                permalink = _fetch_graph_permalink(
                    f"https://graph.instagram.com/{ig_post_id}",
                    {"fields": "permalink", "access_token": conn.get("access_token") or ""},
                )
            if not _is_http_url(permalink):
                print(f"[instagram] no permalink for {ig_post_id}", flush=True)
            else:
                append_content_video_posted_url(
                    client_id,
                    topic_id,
                    "instagram",
                    {
                        "url": permalink,
                        "post_id": ig_post_id,
                        "language": lang,
                        "posted_at": posted_at,
                    },
                )
        if fb_post_id:
            from backend.tg.database import get_facebook_connection

            conn = get_facebook_connection(client_id) or {}
            token = conn.get("page_access_token") or conn.get("access_token") or ""
            page_id = conn.get("selected_page_id") or conn.get("page_id") or ""
            permalink = str(fb_permalink or "").strip()
            if not _is_http_url(permalink):
                permalink = _fetch_graph_permalink(
                    f"https://graph.facebook.com/v18.0/{fb_post_id}",
                    {"fields": "permalink_url", "access_token": token},
                )
            if not _is_http_url(permalink):
                permalink = _facebook_public_url(page_id, fb_post_id)
                print(f"[facebook] using page video link {permalink}", flush=True)
            if permalink:
                append_content_video_posted_url(
                    client_id,
                    topic_id,
                    "facebook",
                    {
                        "url": permalink,
                        "post_id": fb_post_id,
                        "language": lang,
                        "posted_at": posted_at,
                    },
                )
    except Exception as exc:  # noqa: BLE001 — posting already succeeded
        print(f"Failed to append content_video URLs topic={topic_id}: {exc}")


def _get_user_videos(
    username: str,
    client_id: str | None = None,
    channel_id: str | None = None,
) -> list[dict]:
    cid, chid = _resolve_ids(username, client_id, channel_id)
    videos = list_videos_for_channel(chid, cid)
    return [v for v in videos if (v.get("privacy_status") or "public").lower() == "public"]


def _to_video_schema(raw: dict) -> schemas.YouTubeVideoInfo:
    return schemas.YouTubeVideoInfo(
        id=raw["id"],
        title=raw["title"],
        published_at=raw["published_at"],
        thumbnail_url=raw.get("thumbnail_url"),
        view_count=raw["view_count"],
        like_count=raw["like_count"],
        comment_count=raw["comment_count"],
        duration=raw.get("duration"),
        duration_seconds=raw.get("duration_seconds", 0),
        duration_type=raw.get("duration_type") or ("short" if raw.get("is_short") else "long"),
        is_short=bool(raw.get("is_short")),
        short_link=raw.get("short_link")
        or (
            f"https://www.youtube.com/shorts/{raw['id']}" if raw.get("is_short") else None
        ),
        privacy_status=(raw.get("privacy_status") or "public").lower(),
        notes=raw.get("notes", ""),
        metadata_fields=raw.get("metadata_fields", {}),
    )


def _is_public_video(raw: dict) -> bool:
    """Hide private/unlisted from the video library UI. Missing status → treat as public (legacy)."""
    status = (raw.get("privacy_status") or "public").lower()
    return status == "public"


@router.post("/video.list", response_model=schemas.YouTubeVideoListResponse)
def video_list(
    body: schemas.VideoListRequest = Body(default_factory=schemas.VideoListRequest),
    current_user: dict = Depends(get_current_user),
):
    videos = [
        _to_video_schema(v)
        for v in _get_user_videos(current_user["username"], body.client_id, body.channel_id)
        if _is_public_video(v)
    ]
    return schemas.YouTubeVideoListResponse(videos=videos)


@router.post("/video.get", response_model=schemas.YouTubeVideoInfo)
def video_get(
    body: schemas.VideoGetRequest,
    current_user: dict = Depends(get_current_user),
):
    for raw in _get_user_videos(current_user["username"], body.client_id, body.channel_id):
        if raw["id"] == body.video_id:
            return _to_video_schema(raw)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Video '{body.video_id}' not found. Sync videos first.",
    )


@router.post("/video.sync", response_model=schemas.YouTubeVideoListResponse)
def video_sync(
    body: schemas.VideoSyncRequest = Body(default_factory=schemas.VideoSyncRequest),
    current_user: dict = Depends(get_current_user),
):
    username = current_user["username"]
    client_id, channel_id = _resolve_ids(username, body.client_id, body.channel_id)

    creds = get_user_google_creds(username, client_id, channel_id)
    synced_videos = sync_videos_from_youtube(creds, channel_id)

    existing_videos_map = {
        v["id"]: v for v in list_videos_for_channel(channel_id, client_id)
    }
    rows = []
    for v in synced_videos:
        existing = existing_videos_map.get(v.id) or {}
        rows.append(merge_preserved_video_fields(v.model_dump(), existing))
        v.notes = existing.get("notes", "") or ""
        v.metadata_fields = existing.get("metadata_fields", {}) or {}
    replace_channel_videos(channel_id, client_id, rows)

    return schemas.YouTubeVideoListResponse(videos=synced_videos)


@router.post("/video.update", response_model=schemas.YouTubeVideoInfo)
def video_update(
    body: schemas.VideoUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    username = current_user["username"]
    client_id, channel_id = _resolve_ids(username, body.client_id, body.channel_id)
    fields: dict = {}
    if body.notes is not None:
        fields["notes"] = body.notes
    if body.metadata_fields is not None:
        fields["metadata_fields"] = body.metadata_fields
    if not fields:
        for raw in list_videos_for_channel(channel_id, client_id):
            if raw["id"] == body.video_id:
                return _to_video_schema(raw)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video '{body.video_id}' not found.",
        )

    updated = update_video_fields(body.video_id, client_id, fields)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video '{body.video_id}' not found.",
        )
    return _to_video_schema(updated)


@router.post("/video.analytics", response_model=schemas.YouTubeAnalyticsResponse)
def video_analytics(
    body: schemas.YouTubeAnalyticsRequest,
    current_user: dict = Depends(get_current_user),
):
    username = current_user["username"]
    client_id, channel_id = _resolve_ids(username, body.client_id, body.channel_id)
    creds = get_user_google_creds(username, client_id, channel_id)

    try:
        column_headers, rows = fetch_channel_analytics(
            creds,
            channel_id,
            start_date=body.start_date,
            end_date=body.end_date,
            metrics=body.metrics,
            dimensions=body.dimensions,
            sort=body.sort,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    return schemas.YouTubeAnalyticsResponse(column_headers=column_headers, rows=rows)


@router.post("/video.local.upload")
async def video_local_upload(
    client_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    if not fetch_client_doc(client_id, username=current_user["username"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    content_type = file.content_type or "application/octet-stream"
    mime = content_type.split(";")[0].strip().lower()
    file_ext = Path(file.filename or "").suffix.lower()
    if mime not in VIDEO_MIME_TYPES and file_ext not in VIDEO_EXTS:
        raise HTTPException(status_code=400, detail="File must be an mp4, mov, or webm video.")

    ext = file_ext if file_ext in VIDEO_EXTS else {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
    }.get(mime, ".mp4")
    stored_type = mime if mime in VIDEO_MIME_TYPES else {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
    }.get(ext, "video/mp4")

    filename = f"{uuid.uuid4().hex}{ext}"
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        public_url = upload_bytes("uploaded_videos", filename, content, content_type=stored_type)
    except Exception as exc:  # noqa: BLE001
        print(f"GCS upload failed: {exc}. Falling back to local disk.", flush=True)
        UPLOADED_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        (UPLOADED_VIDEOS_DIR / filename).write_bytes(content)
        base_url = settings.BASE_URL.rstrip("/")
        public_url = f"{base_url}/weekly.tracker.asset/uploaded_videos/{filename}"

    return {
        "url": public_url,
        "name": file.filename or filename,
        "content_type": stored_type,
    }


def _graph_body(resp) -> str:
    text = getattr(resp, "text", None) or ""
    stripped = text.lstrip()
    if stripped[:15].lower().startswith("<!doctype") or stripped[:6].lower().startswith("<html"):
        return f"HTML error page (HTTP {getattr(resp, 'status_code', '')})"
    text = text[:800]
    return text or f"HTTP {getattr(resp, 'status_code', '')}"


def _graph_json(resp) -> dict:
    try:
        payload = resp.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


class _FacebookChunkReader:
    """Read one Facebook upload range and report a real percent."""

    def __init__(self, path: str, start: int, length: int, file_size: int, on_progress=None):
        self._fh = open(path, "rb")
        self._fh.seek(start)
        self._start = start
        self._length = length
        self._read = 0
        self._file_size = file_size
        self._on_progress = on_progress
        self._last = -1

    def __len__(self):
        return self._length

    def read(self, size=-1):
        if self._read >= self._length:
            return b""
        take = self._length - self._read if size < 0 else min(size, self._length - self._read)
        data = self._fh.read(take)
        self._read += len(data)
        if self._on_progress and self._file_size:
            percent = min(99, int((self._start + self._read) * 100 / self._file_size))
            if percent != self._last:
                self._last = percent
                self._on_progress(percent)
        return data

    def close(self):
        self._fh.close()


def _wait_instagram_reel_ready(creation_id: str, access_token: str, on_status=None) -> None:
    """Poll the reel container until Instagram finishes processing it."""
    import time

    import requests

    deadline = time.time() + 180
    last_body = ""
    while time.time() < deadline:
        status_resp = requests.get(
            f"https://graph.instagram.com/{creation_id}",
            params={"fields": "status_code,status", "access_token": access_token},
            timeout=30,
        )
        last_body = _graph_body(status_resp)
        if not status_resp.ok:
            print(f"[instagram] status failed: {last_body}", flush=True)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Instagram reel status failed: {last_body}",
            )
        payload = status_resp.json() or {}
        code = str(payload.get("status_code") or "")
        print(f"[instagram] container {creation_id} status={code or 'unknown'} body={last_body}", flush=True)
        if on_status:
            on_status(code or "waiting")
        if code == "FINISHED":
            return
        if code == "ERROR":
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Instagram reel processing failed: {last_body}",
            )
        time.sleep(5)
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Instagram reel was not ready before timeout: {last_body}",
    )


def _publish_instagram_reel(
    client_id: str,
    video_url: str,
    caption: str,
    get_connection,
    on_status=None,
    cover_url: str | None = None,
    on_cover_error=None,
) -> str:
    import requests as http

    conn = get_connection(client_id) or {}
    ig_user_id = conn.get("instagram_user_id")
    access_token = conn.get("access_token")
    if not ig_user_id or not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Instagram is not connected for this client.",
        )
    print(f"[instagram] creating reel from {video_url}", flush=True)
    payload = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "access_token": access_token,
    }
    public_cover = str(cover_url or "").strip()
    if _is_http_url(public_cover):
        payload["cover_url"] = public_cover
    media_resp = http.post(
        f"https://graph.instagram.com/{ig_user_id}/media",
        data=payload,
        timeout=60,
    )
    if not media_resp.ok and payload.get("cover_url"):
        body = _graph_body(media_resp)
        print(f"[instagram] cover failed, posting without cover: {body}", flush=True)
        if on_cover_error:
            on_cover_error(f"Instagram reel posted without the custom cover: {body}")
        payload.pop("cover_url", None)
        media_resp = http.post(
            f"https://graph.instagram.com/{ig_user_id}/media",
            data=payload,
            timeout=60,
        )
    if not media_resp.ok:
        body = _graph_body(media_resp)
        print(f"[instagram] container create failed: {body}", flush=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Instagram reel upload failed: {body}",
        )
    creation_id = (media_resp.json() or {}).get("id")
    if not creation_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Instagram reel upload failed: no creation id.",
        )
    print(f"[instagram] container id={creation_id}", flush=True)
    _wait_instagram_reel_ready(creation_id, access_token, on_status=on_status)
    publish_resp = http.post(
        f"https://graph.instagram.com/{ig_user_id}/media_publish",
        data={"creation_id": creation_id, "access_token": access_token},
        timeout=60,
    )
    if not publish_resp.ok:
        body = _graph_body(publish_resp)
        print(f"[instagram] publish failed: {body}", flush=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Instagram reel publish failed: {body}",
        )
    post_id = (publish_resp.json() or {}).get("id")
    if not post_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Instagram reel publish failed: no post id.",
        )
    live_resp = http.get(
        f"https://graph.instagram.com/{post_id}",
        params={"fields": "id,permalink", "access_token": access_token},
        timeout=30,
    )
    live = live_resp.json() or {}
    if not live_resp.ok or not live.get("id"):
        body = _graph_body(live_resp)
        print(f"[instagram] published media was not readable: {body}", flush=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Instagram did not confirm the reel is live: {body}",
        )
    permalink = str(live.get("permalink") or "").strip()
    print(f"[instagram] live id={post_id} permalink={permalink or 'missing'}", flush=True)
    return post_id, permalink


_FB_GRAPH_VIDEO = "https://graph-video.facebook.com/v18.0"


def _facebook_raise(resp, what: str) -> None:
    body = _graph_body(resp)
    print(f"[facebook] {what} failed: {body}", flush=True)
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Facebook video upload failed: {body}",
    )


def _facebook_phase_error(status_obj: dict) -> str | None:
    for key in ("processing_phase", "publishing_phase", "uploading_phase"):
        phase = status_obj.get(key) or {}
        if str(phase.get("status") or "").lower() != "error":
            continue
        errors = phase.get("errors") or []
        parts = []
        if isinstance(errors, list):
            for item in errors:
                if isinstance(item, dict):
                    parts.append(str(item.get("message") or item.get("code") or item))
                else:
                    parts.append(str(item))
        return "; ".join(part for part in parts if part) or f"Facebook {key.replace('_', ' ')} failed."
    if str(status_obj.get("video_status") or "").lower() == "error":
        return "Facebook could not process the video."
    return None


def _facebook_is_on_page(payload: dict) -> bool:
    """True only when Facebook says the video is published, not merely uploaded."""
    status_obj = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    video_status = str(status_obj.get("video_status") or "").lower()
    processing = str((status_obj.get("processing_phase") or {}).get("status") or "").lower()
    publishing = str((status_obj.get("publishing_phase") or {}).get("status") or "").lower()
    if processing in {"not_started", "in_progress"}:
        return False
    if video_status not in {"ready", "complete", "completed"} and processing not in {"complete", "completed"}:
        return False
    if publishing in {"not_started", "in_progress"}:
        return False
    if publishing in {"complete", "completed"}:
        return True
    return payload.get("published") is True


def _wait_facebook_video_published(
    video_id: str,
    access_token: str,
    on_status=None,
    pause: float = 8,
    timeout: float = 20 * 60,
) -> str:
    """Wait until Facebook finishes encoding and the video is public on the page."""
    import time

    import requests as http

    deadline = time.time() + timeout
    last = ""
    asked_publish = False
    while time.time() < deadline:
        status_resp = http.get(
            f"https://graph.facebook.com/v18.0/{video_id}",
            params={"fields": "status,published,permalink_url", "access_token": access_token},
            timeout=30,
        )
        if not status_resp.ok:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Facebook video status failed: {_graph_body(status_resp)}",
            )
        payload = _graph_json(status_resp)
        status_obj = payload.get("status") if isinstance(payload.get("status"), dict) else {}
        video_status = str(status_obj.get("video_status") or "processing")
        publishing = str((status_obj.get("publishing_phase") or {}).get("status") or "")
        progress = status_obj.get("processing_progress")
        line = f"status={video_status} publishing={publishing or 'unknown'} progress={progress} published={payload.get('published')}"
        if line != last:
            print(f"[facebook] video {video_id} {line}", flush=True)
            last = line
        if on_status:
            if progress is not None and video_status.lower() == "processing":
                on_status(f"Facebook is processing the video… {progress}%")
            else:
                on_status(f"Facebook is processing the video ({video_status})…")
        phase_error = _facebook_phase_error(status_obj)
        if phase_error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Facebook video was not posted. {phase_error}",
            )
        ready = video_status.lower() in {"ready", "complete", "completed"}
        if ready and payload.get("published") is False and not asked_publish:
            asked_publish = True
            publish_resp = http.post(
                f"https://graph.facebook.com/v18.0/{video_id}",
                data={"published": "true", "access_token": access_token},
                timeout=60,
            )
            if not publish_resp.ok:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Facebook video stayed unpublished: {_graph_body(publish_resp)}",
                )
            print(f"[facebook] set published on {video_id}", flush=True)
            time.sleep(pause)
            continue
        if _facebook_is_on_page(payload):
            return str(payload.get("permalink_url") or "").strip()
        time.sleep(pause)
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Facebook accepted the file but did not finish publishing it in time.",
    )


def _publish_facebook_video(
    client_id: str,
    video_url: str,
    caption: str,
    get_connection,
    video_path: str | None = None,
    on_progress=None,
    on_status=None,
) -> str:
    import os

    import requests as http

    conn = get_connection(client_id) or {}
    page_id = conn.get("selected_page_id") or conn.get("page_id")
    access_token = conn.get("page_access_token") or conn.get("access_token")
    if not page_id or not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Facebook is not connected for this client.",
        )
    endpoint = f"{_FB_GRAPH_VIDEO}/{page_id}/videos"
    if video_path and os.path.exists(video_path):
        return _publish_facebook_video_resumable(
            endpoint,
            access_token,
            caption,
            video_path,
            page_id,
            on_progress=on_progress,
            on_status=on_status,
        )
    print(f"[facebook] posting video to page {page_id} from {video_url}", flush=True)
    fb_resp = http.post(
        endpoint,
        data={
            "file_url": video_url,
            "description": caption,
            "access_token": access_token,
            "published": "true",
        },
        timeout=600,
    )
    if not fb_resp.ok:
        _facebook_raise(fb_resp, "upload")
    post_id = _graph_json(fb_resp).get("id")
    if not post_id:
        print(f"[facebook] upload returned no post id: {_graph_body(fb_resp)}", flush=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Facebook video upload failed: no post id.",
        )
    permalink = _facebook_public_url(page_id, str(post_id))
    print(f"[facebook] posted id={post_id} link={permalink}", flush=True)
    return str(post_id), permalink


def _publish_facebook_video_resumable(
    endpoint: str,
    access_token: str,
    caption: str,
    video_path: str,
    page_id: str,
    on_progress=None,
    on_status=None,
) -> tuple[str, str]:
    import os

    import requests as http

    file_size = os.path.getsize(video_path)
    print(f"[facebook] resumable upload {file_size} bytes to {endpoint}", flush=True)
    if on_progress:
        on_progress(0)

    session = http.Session()
    try:
        return _facebook_resumable_session(
            session,
            endpoint,
            access_token,
            caption,
            video_path,
            page_id,
            file_size,
            on_progress=on_progress,
            on_status=on_status,
        )
    finally:
        session.close()


def _facebook_resumable_session(
    session,
    endpoint: str,
    access_token: str,
    caption: str,
    video_path: str,
    page_id: str,
    file_size: int,
    on_progress=None,
    on_status=None,
) -> tuple[str, str]:
    start_resp = session.post(
        endpoint,
        data={
            "upload_phase": "start",
            "file_size": str(file_size),
            "published": "true",
            "access_token": access_token,
        },
        timeout=60,
    )
    if not start_resp.ok:
        _facebook_raise(start_resp, "start")
    start_payload = _graph_json(start_resp)
    session_id = start_payload.get("upload_session_id")
    video_id = start_payload.get("video_id") or start_payload.get("id")
    start_offset = int(start_payload.get("start_offset") or 0)
    end_offset = int(start_payload.get("end_offset") or 0)
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Facebook video upload failed: no upload session.",
        )

    last_start = -1
    while start_offset < end_offset:
        if start_offset <= last_start:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Facebook video upload failed: upload offsets did not advance.",
            )
        last_start = start_offset
        length = end_offset - start_offset
        reader = _FacebookChunkReader(video_path, start_offset, length, file_size, on_progress)
        try:
            transfer_resp = session.post(
                endpoint,
                data={
                    "upload_phase": "transfer",
                    "upload_session_id": session_id,
                    "start_offset": str(start_offset),
                    "access_token": access_token,
                },
                files={"video_file_chunk": ("chunk.mp4", reader, "application/octet-stream")},
                timeout=300,
            )
        finally:
            reader.close()
        if not transfer_resp.ok:
            _facebook_raise(transfer_resp, "transfer")
        transfer_payload = _graph_json(transfer_resp)
        start_offset = int(transfer_payload.get("start_offset") or end_offset)
        end_offset = int(transfer_payload.get("end_offset") or start_offset)

    if on_progress:
        on_progress(100)
    finish_resp = session.post(
        endpoint,
        data={
            "upload_phase": "finish",
            "upload_session_id": session_id,
            "description": caption,
            "published": "true",
            "access_token": access_token,
        },
        timeout=120,
    )
    if not finish_resp.ok:
        _facebook_raise(finish_resp, "finish")
    finish_payload = _graph_json(finish_resp)
    print(f"[facebook] finish body={finish_payload or _graph_body(finish_resp)}", flush=True)
    if finish_payload.get("success") is False:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Facebook video upload failed: finish was not successful.",
        )
    post_id = finish_payload.get("id") or video_id
    if not post_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Facebook video upload failed: no post id.",
        )
    permalink = _wait_facebook_video_published(str(post_id), access_token, on_status=on_status)
    if not _is_http_url(permalink):
        permalink = _facebook_public_url(page_id, str(post_id))
    print(f"[facebook] posted id={post_id} link={permalink}", flush=True)
    return str(post_id), permalink


_MIN_VIDEO_BYTES = 1024 * 1024
_INSTAGRAM_REEL_MAX_BYTES = 1000 * 1000 * 1000


def _instagram_reel_size_error(size_bytes: int) -> str | None:
    """Instagram reels stop at 1 GB. None means the file can be posted."""
    if size_bytes <= _INSTAGRAM_REEL_MAX_BYTES:
        return None
    gb = size_bytes / _INSTAGRAM_REEL_MAX_BYTES
    return (
        "Instagram reel was not posted. The video is "
        f"{gb:.2f} GB, and Instagram reels must be 1 GB or smaller."
    )


def _normalize_video_url(url: str) -> str:
    """Strip whitespace and trailing junk pasted after a Drive URL."""
    cleaned = (url or "").strip()
    if not cleaned:
        return cleaned
    if cleaned.startswith("http"):
        return cleaned.split()[0]
    return cleaned


def _download_video_file(url: str, dest: str) -> None:
    import os

    import gdown
    import requests

    url = _normalize_video_url(url)
    if not url:
        raise ValueError("Video URL is empty.")

    if "drive.google.com" in url:
        gdown.download(url, dest, quiet=False)
    else:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        with requests.get(url, stream=True, headers=headers) as response:
            response.raise_for_status()
            with open(dest, "wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
    if not os.path.exists(dest) or os.path.getsize(dest) == 0:
        raise ValueError("Failed to download video.")
    size = os.path.getsize(dest)
    if size < _MIN_VIDEO_BYTES:
        raise ValueError(
            f"Downloaded file is too small ({size} bytes). "
            "Check the Drive link — it may be a preview page, not the video file."
        )


def _download_thumbnail_file(url: str) -> str | None:
    """Return a local thumbnail path. None when the channel has no thumbnail."""
    import os
    import uuid

    import requests

    if not url:
        return None
    if url.startswith("/social.asset/"):
        from pathlib import Path

        assets_dir = Path(__file__).resolve().parent.parent.parent / "social_assets"
        local_file = assets_dir / url.replace("/social.asset/", "", 1)
        if not local_file.exists():
            raise FileNotFoundError(f"Thumbnail not found locally: {url}")
        return str(local_file)
    dest = f"/tmp/{uuid.uuid4()}.jpg"
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    with open(dest, "wb") as handle:
        handle.write(response.content)
    if not os.path.exists(dest):
        raise ValueError(f"Failed to download thumbnail: {url}")
    return dest


def _public_image_url(url: str | None, local_path: str | None = None) -> str:
    """Instagram cover_url must be a public https image Meta can fetch."""
    value = str(url or "").strip()
    if _is_http_url(value):
        return value
    path = str(local_path or "").strip()
    if not path:
        return ""
    from pathlib import Path

    data = Path(path).read_bytes()
    if not data:
        return ""
    suffix = Path(path).suffix or ".png"
    try:
        return upload_bytes("thumbnails", f"{uuid.uuid4()}{suffix}", data)
    except Exception as exc:  # noqa: BLE001
        print(f"[publish] could not publish thumbnail URL: {exc}", flush=True)
        return ""


def _set_facebook_video_thumbnail(video_id: str, access_token: str, thumbnail_path: str | None) -> str | None:
    """Set the preferred Page-video cover. Return error text, or None if skipped/ok."""
    import os

    import requests as http

    video_id = str(video_id or "").strip()
    path = str(thumbnail_path or "").strip()
    if not video_id or not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as handle:
            resp = http.post(
                f"https://graph.facebook.com/v18.0/{video_id}/thumbnails",
                data={"is_preferred": "true", "access_token": access_token},
                files={"source": ("thumb.jpg", handle, "image/jpeg")},
                timeout=60,
            )
        if not resp.ok:
            body = _graph_body(resp)
            print(f"[facebook] thumbnail failed: {body}", flush=True)
            return f"Facebook thumbnail was not set: {body}"
        print(f"[facebook] thumbnail set on {video_id}", flush=True)
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"[facebook] thumbnail failed: {exc}", flush=True)
        return f"Facebook thumbnail was not set: {exc}"


_publish_stage: contextvars.ContextVar = contextvars.ContextVar("publish_stage", default=None)


def _emit_stage(message: str) -> None:
    """Tell the publish UI the current step, including real upload percent when we have it."""
    print(f"[publish] {message}", flush=True)
    hook = _publish_stage.get()
    if hook:
        hook(message)


def _upload_jobs(body: schemas.VideoUploadRequest) -> list[dict]:
    if body.channels:
        return [row.model_dump() for row in body.channels]
    if body.post_to_youtube and body.channel_id and body.drive_link:
        return [{
            "channel_id": body.channel_id,
            "drive_link": body.drive_link,
            "title": body.title,
            "description": body.description,
            "tags": body.tags,
            "thumbnail_url": body.thumbnail_url,
            "language": body.language,
        }]
    return []


@router.post("/video.upload")
def video_upload(
    body: schemas.VideoUploadRequest,
    current_user: dict = Depends(get_current_user),
):
    if body.stream_progress:
        return _stream_video_upload(body, current_user)
    return _execute_video_upload(body, current_user)


def _stream_video_upload(body: schemas.VideoUploadRequest, current_user: dict):
    import json
    import queue
    import threading

    from fastapi.responses import StreamingResponse

    events: queue.Queue = queue.Queue()

    def on_stage(message: str) -> None:
        events.put({"event": "stage", "stage": message})

    def worker() -> None:
        token = _publish_stage.set(on_stage)
        try:
            result = _execute_video_upload(body, current_user)
            events.put({"event": "done", "result": result})
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            events.put({"event": "error", "detail": detail})
        except Exception as exc:  # noqa: BLE001
            events.put({"event": "error", "detail": str(exc)})
        finally:
            _publish_stage.reset(token)
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def generate():
        while True:
            item = events.get()
            if item is None:
                break
            yield json.dumps(item) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


def _execute_video_upload(
    body: schemas.VideoUploadRequest,
    current_user: dict,
):
    import os
    import threading
    import uuid
    from concurrent.futures import ThreadPoolExecutor

    from backend.tg.services.youtube_api import upload_video_to_youtube

    username = current_user["username"]
    client_id, _channel_id = _resolve_ids(username, body.client_id, body.channel_id or None)
    post_to_youtube, post_to_instagram, post_to_facebook = publish_platforms(
        post_to_youtube=body.post_to_youtube,
        post_to_instagram=body.post_to_instagram,
        post_to_facebook=body.post_to_facebook,
    )
    jobs = _upload_jobs(body) if post_to_youtube else []
    for job in jobs:
        _resolve_ids(username, client_id, job.get("channel_id"))

    social_file_url = ""
    if post_to_instagram or post_to_facebook:
        social_file_url = str(body.social_drive_link or "").strip()
        if not social_file_url:
            hinglish = next(
                (job for job in jobs if str(job.get("language") or "").strip().lower() == "hinglish"),
                None,
            )
            social_file_url = _normalize_video_url(
                str((hinglish or (jobs[0] if jobs else {})).get("drive_link") or body.drive_link or "")
            )
    social_file_url = _normalize_video_url(social_file_url) if social_file_url else ""
    if not jobs and not social_file_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add a video URL to publish.")

    urls: list[str] = []
    for job in jobs:
        link = _normalize_video_url(str(job.get("drive_link") or ""))
        if link and link not in urls:
            urls.append(link)
    if social_file_url and social_file_url not in urls:
        urls.append(social_file_url)

    downloaded: dict[str, str] = {}
    thumbnail_paths: dict[str, str | None] = {}
    temp_paths: list[str] = []
    errors: list[str] = []
    posted_video_ids: list[dict] = []
    ig_post_id = None
    fb_post_id = None
    record_lock = threading.Lock()

    def _record(**kwargs) -> None:
        with record_lock:
            _append_content_video_post_urls(**kwargs)

    try:
        if urls:
            _emit_stage("Downloading video…")

        def _fetch_video(url: str) -> tuple[str, str | None, str | None]:
            dest = f"/tmp/{uuid.uuid4()}.mp4"
            try:
                _download_video_file(url, dest)
                return url, dest, None
            except Exception as exc:  # noqa: BLE001
                if os.path.exists(dest):
                    os.remove(dest)
                return url, None, str(exc)

        with ThreadPoolExecutor(max_workers=max(1, min(4, len(urls)))) as pool:
            for url, dest, error in pool.map(_fetch_video, urls):
                if dest:
                    downloaded[url] = dest
                    temp_paths.append(dest)
                elif error:
                    errors.append(f"Download failed: {error}")

        for job in jobs:
            channel_id = str(job.get("channel_id") or "")
            try:
                thumb = _download_thumbnail_file(str(job.get("thumbnail_url") or ""))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{job.get('language') or channel_id}: thumbnail download failed: {exc}")
                thumbnail_paths[channel_id] = None
                job["skip"] = True
                continue
            thumbnail_paths[channel_id] = thumb
            if thumb and thumb.startswith("/tmp/"):
                temp_paths.append(thumb)

        def _post_youtube(job: dict) -> dict:
            language = str(job.get("language") or "").strip()
            label = language or job.get("channel_id") or "YouTube"
            link = _normalize_video_url(str(job.get("drive_link") or ""))
            video_path = downloaded.get(link)
            if job.get("skip"):
                return {"error": None, "video_id": None, "language": language, "channel_id": job.get("channel_id")}
            _emit_stage(f"Uploading to YouTube ({label})…")
            if not video_path:
                return {
                    "error": f"{label}: video file was not downloaded.",
                    "video_id": None,
                    "language": language,
                    "channel_id": job.get("channel_id"),
                }
            try:
                creds = get_user_google_creds(username, client_id, job["channel_id"])
                video_id = upload_video_to_youtube(
                    creds=creds,
                    channel_id=job["channel_id"],
                    video_path=video_path,
                    title=job.get("title") or "",
                    description=job.get("description") or "",
                    tags=list(job.get("tags") or []),
                    thumbnail_path=thumbnail_paths.get(job["channel_id"]),
                    on_progress=lambda percent, name=label: _emit_stage(
                        f"Uploading to YouTube ({name})… {percent}%"
                    ),
                    on_status=lambda _line, name=label: _emit_stage(
                        f"YouTube is processing the video ({name})…"
                    ),
                )
                _emit_stage(f"YouTube video is live ({label}).")
                _record(
                    client_id=client_id,
                    channel_id=job["channel_id"],
                    topic_id=body.topic_id,
                    language=language,
                    video_id=video_id,
                    ig_post_id=None,
                    fb_post_id=None,
                    drive_link=link,
                    post_to_instagram=False,
                    post_to_facebook=False,
                )
                return {
                    "error": None,
                    "video_id": video_id,
                    "language": language,
                    "channel_id": job.get("channel_id"),
                }
            except HTTPException as exc:
                return {"error": f"{label}: {exc.detail}", "video_id": None, "language": language, "channel_id": job.get("channel_id")}
            except Exception as exc:  # noqa: BLE001
                text = str(exc)
                if "timeout" in text.lower() or "timed out" in text.lower():
                    text = f"YouTube upload timed out. {text}"
                return {"error": f"{label}: {text}", "video_id": None, "language": language, "channel_id": job.get("channel_id")}

        def _copy_to_storage() -> tuple[str | None, str | None]:
            from backend.tg.services.gcs_storage import upload_file

            video_path = downloaded.get(social_file_url)
            if not video_path:
                return None, "Could not prepare the video for Instagram: video file was not downloaded."
            try:
                return upload_file(
                    "social_post_videos",
                    video_path,
                    content_type="video/mp4",
                    on_progress=lambda percent: _emit_stage(
                        f"Copying video for Instagram… {percent}%"
                    ),
                ), None
            except TimeoutError as exc:
                return None, str(exc)
            except Exception as exc:  # noqa: BLE001
                text = str(exc)
                if "timeout" in text.lower() or "timed out" in text.lower():
                    return None, (
                        "Storage upload timed out after 1 hour. "
                        "The video was not copied for Instagram."
                    )
                return None, f"Storage upload failed, so Instagram was not posted: {exc}"

        def _social_caption() -> tuple[str | None, str | None]:
            from backend.tg.services.youtube_metadata import generate_social_caption

            source = next((job for job in jobs if str(job.get("language") or "").lower() == "hinglish"), None)
            source = source or (jobs[0] if jobs else None) or {
                "title": body.title,
                "description": body.description,
                "tags": body.tags,
            }
            try:
                caption = fit_social_caption(
                    generate_social_caption(
                        source.get("title") or body.title,
                        source.get("description") or body.description,
                        list(source.get("tags") or body.tags or []),
                    )
                )
                return caption, None
            except Exception as exc:  # noqa: BLE001
                fallback = str(source.get("title") or body.title or "").strip()
                print(f"[publish] social caption failed, using title: {exc}", flush=True)
                if fallback:
                    return fit_social_caption(fallback), None
                return None, f"Could not write the social caption: {exc}"

        gcs_url = None
        social_caption = None
        social_path = downloaded.get(social_file_url) if social_file_url else None
        social_bytes = os.path.getsize(social_path) if social_path and os.path.exists(social_path) else 0
        instagram_size_error = _instagram_reel_size_error(social_bytes) if post_to_instagram else None
        can_post_instagram = bool(post_to_instagram and social_path and not instagram_size_error)
        can_post_facebook = bool(post_to_facebook and social_path)

        if instagram_size_error:
            print(f"[instagram] {instagram_size_error}", flush=True)
            _emit_stage(instagram_size_error)
            errors.append(instagram_size_error)

        with ThreadPoolExecutor(max_workers=1) as caption_pool:
            caption_future = caption_pool.submit(_social_caption) if (can_post_facebook or can_post_instagram) else None

            for job in jobs:
                result = _post_youtube(job)
                if result.get("video_id"):
                    posted_video_ids.append(result)
                if result.get("error"):
                    errors.append(result["error"])

            if caption_future:
                social_caption, caption_error = caption_future.result()
                if caption_error:
                    errors.append(caption_error)

        social_language = body.language
        social_channel_id = body.channel_id
        hinglish_job = next(
            (job for job in jobs if str(job.get("language") or "").lower() == "hinglish"),
            None,
        )
        if hinglish_job:
            social_language = hinglish_job.get("language") or social_language
        social_channel_id = (hinglish_job or (jobs[0] if jobs else {})).get("channel_id") or body.channel_id
        social_thumb_url = str(
            (hinglish_job or {}).get("thumbnail_url")
            or (jobs[0].get("thumbnail_url") if jobs else "")
            or body.thumbnail_url
            or ""
        ).strip()
        social_thumb_path = None
        social_cover_url = ""
        if (can_post_facebook or can_post_instagram) and social_thumb_url:
            try:
                social_thumb_path = _download_thumbnail_file(social_thumb_url)
                if social_thumb_path and str(social_thumb_path).startswith("/tmp/"):
                    temp_paths.append(social_thumb_path)
            except Exception as exc:  # noqa: BLE001
                print(f"[publish] social thumbnail download failed: {exc}", flush=True)
                errors.append(f"Social thumbnail download failed: {exc}")
            social_cover_url = _public_image_url(social_thumb_url, social_thumb_path)

        def _save_social(*, ig_id=None, fb_id=None, ig_link="", fb_link="") -> None:
            _record(
                client_id=client_id,
                channel_id=social_channel_id,
                topic_id=body.topic_id,
                language=social_language,
                video_id=None,
                ig_post_id=ig_id,
                fb_post_id=fb_id,
                drive_link=social_file_url,
                post_to_instagram=bool(ig_id),
                post_to_facebook=bool(fb_id),
                social_source_url=body.social_source_url or social_file_url,
                ig_permalink=ig_link,
                fb_permalink=fb_link,
            )

        if can_post_facebook:
            if not social_caption:
                errors.append("Facebook was not posted. Could not write the social caption.")
            else:
                from backend.tg.database import get_facebook_connection

                _emit_stage("Posting to Facebook…")
                try:
                    post_id, permalink = _post_result(_publish_facebook_video(
                        client_id,
                        "",
                        social_caption,
                        get_facebook_connection,
                        video_path=social_path,
                        on_progress=lambda percent: _emit_stage(
                            f"Posting to Facebook… {percent}%"
                        ),
                        on_status=lambda message: _emit_stage(message),
                    ))
                    fb_post_id = post_id
                    _save_social(fb_id=post_id, fb_link=permalink)
                    conn = get_facebook_connection(client_id) or {}
                    thumb_error = _set_facebook_video_thumbnail(
                        post_id,
                        conn.get("page_access_token") or conn.get("access_token") or "",
                        social_thumb_path,
                    )
                    if thumb_error:
                        errors.append(thumb_error)
                    _emit_stage("Facebook video posted.")
                except HTTPException as exc:
                    print(f"[facebook] failed: {exc.detail}", flush=True)
                    errors.append(f"Facebook: {exc.detail}")
                except Exception as exc:  # noqa: BLE001
                    print(f"[facebook] failed: {exc}", flush=True)
                    errors.append(f"Facebook: {exc}")

        if can_post_instagram:
            _emit_stage("Copying video for Instagram…")
            gcs_url, storage_error = _copy_to_storage()
            if storage_error:
                errors.append(storage_error)
            elif not social_caption:
                errors.append("Instagram was not posted. Could not write the social caption.")
            elif not gcs_url:
                errors.append("Instagram was not posted. The video copy for social did not finish.")
            else:
                try:
                    from backend.tg.database import get_instagram_connection

                    post_id, permalink = _post_result(_publish_instagram_reel(
                        client_id,
                        gcs_url,
                        social_caption,
                        get_instagram_connection,
                        on_status=lambda code: _emit_stage(
                            f"Instagram is processing the reel ({code})…"
                        ),
                        cover_url=social_cover_url,
                        on_cover_error=errors.append,
                    ))
                    ig_post_id = post_id
                    _save_social(ig_id=post_id, ig_link=permalink)
                    print(f"[instagram] posted id={post_id}", flush=True)
                    _emit_stage("Instagram reel posted.")
                except HTTPException as exc:
                    print(f"[instagram] failed: {exc.detail}", flush=True)
                    errors.append(f"Instagram: {exc.detail}")
                except Exception as exc:  # noqa: BLE001
                    print(f"[instagram] failed: {exc}", flush=True)
                    errors.append(f"Instagram: {exc}")
    finally:
        for path in temp_paths:
            if path and path.startswith("/tmp/") and os.path.exists(path):
                os.remove(path)

    return {
        "status": "partial" if errors else "success",
        "errors": errors,
        "video_id": posted_video_ids[0]["video_id"] if posted_video_ids else None,
        "video_ids": [
            {"channel_id": row.get("channel_id"), "language": row.get("language"), "video_id": row.get("video_id")}
            for row in posted_video_ids
        ],
        "ig_post_id": ig_post_id,
        "fb_post_id": fb_post_id,
    }
