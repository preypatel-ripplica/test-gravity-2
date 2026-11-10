"""All-trackers sheet APIs (TG parity)."""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from backend.main.models import Domain
from backend.tg import schemas
from backend.tg.auth import get_current_user
from backend.tg.database import (
    fetch_custom_trackers_by_client_ids,
    fetch_weekly_trackers_by_ids,
    list_clients_for_user,
    list_sheet_comments_for_month,
    require_domain_for_user,
    save_sheet_comment,
    weekly_tracker_doc_id,
)
from backend.tg.services.tracker_sheet import (
    STAGE_LABELS,
    comments_map,
    flatten_weekly_rows,
    week_end_date,
    weeks_in_month,
)
from backend.trackers.crudl import _card_is_complete, _ensure_week, _now_iso, seed_default_cards
from backend.trackers.tracker_settings import (
    LEGACY_TRACKER_START,
    current_week_tuple,
    iter_weeks_inclusive,
    last_ended_week,
    slots_for_week,
    tracker_start_tuple,
    week_is_before_current,
    week_is_before_start,
)

router = APIRouter(tags=["tracker-sheet"])

NEXT_WEEK_GREEN_STAGES = {
    "audio_generated",
    "video_edited",
    "shared_with_doctor",
    "posted",
    "link_shared_with_doctor",
}
VIDEO_TYPES = {"long_video", "short"}
CUSTOM_STATUS_LABELS = {
    "todo": "To do",
    "in_progress": "In progress",
    "done": "Done",
}


def _validate_month(year: int, month: int) -> None:
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month must be 1-12")
    if year < 2000 or year > 2100:
        raise HTTPException(status_code=400, detail="Invalid year")


def _require_videos_client(username: str, client_id: str) -> dict:
    require_domain_for_user(username, client_id, Domain.VIDEOS)
    clients = {
        c["id"]: c for c in list_clients_for_user(username, with_topics=False)
    }
    client = clients.get(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _tasks_from_doc(doc: dict | None) -> list[dict]:
    if not isinstance(doc, dict):
        return []
    return [t for t in (doc.get("tasks") or []) if isinstance(t, dict)]


@router.post("/tracker.sheet.clients")
def tracker_sheet_clients(current_user: dict = Depends(get_current_user)):
    clients = list_clients_for_user(current_user["username"], with_topics=False)
    rows = sorted(
        [
            {
                "client_id": client["id"],
                "name": client.get("name") or "Untitled client",
            }
            for client in clients
        ],
        key=lambda row: (row["name"] or "").lower(),
    )
    return {"clients": rows}


def _week_start_date(year: int, month: int, week: int) -> str:
    starts = (1, 8, 15, 22)
    if week < 1 or week > 4:
        return ""
    start = starts[week - 1]
    last = monthrange(year, month)[1]
    if start > last:
        return ""
    return f"{int(year):04d}-{int(month):02d}-{int(start):02d}"


def _week_range(year: int, month: int, week: int) -> tuple[str, str]:
    return _week_start_date(year, month, week), week_end_date(year, month, week)


def _past_week_keys(
    current: tuple[int, int, int],
    last: tuple[int, int, int] | None,
    clients: list[dict],
) -> list[tuple[int, int, int]]:
    """All ended weeks from the earliest client start through last week."""
    end = last
    if not end:
        year, month, week = current
        if week <= 1:
            return []
        end = (year, month, week - 1)
    if end >= current:
        return []
    starts = [tracker_start_tuple(client) or LEGACY_TRACKER_START for client in clients]
    earliest = min(starts) if starts else end
    if earliest > end:
        return []
    return list(iter_weeks_inclusive(earliest, end))


def _next_week_tuple(today: date | None = None) -> tuple[int, int, int]:
    year, month, week = current_week_tuple(today)
    later = [item for item in weeks_in_month(year, month) if item > week]
    if later:
        return year, month, later[0]
    month += 1
    if month > 12:
        month = 1
        year += 1
    available = weeks_in_month(year, month)
    return year, month, available[0] if available else (year, month, 1)


def _custom_tone(
    due_date: str, current: tuple[str, str], last: tuple[str, str] | None, done: bool
) -> str:
    if done:
        return "completed"
    if last and due_date and due_date <= last[1]:
        return "urgent"
    return "pending"


def _pending_custom_rows(
    client_id: str,
    client_name: str,
    doc: dict | None,
    current: tuple[int, int, int],
    last: tuple[int, int, int] | None,
) -> list[dict]:
    tasks = _tasks_from_doc(doc)
    href = f"/clients/{client_id}/tracker/custom"
    current_range = _week_range(*current)
    last_range = _week_range(*last) if last else None
    rows = []
    for task in tasks:
        title = str(task.get("title") or "").strip()
        due_date = str(task.get("due_date") or "").strip()
        done = bool(task.get("done"))
        if done:
            continue
        tone = _custom_tone(due_date, current_range, last_range, done)
        year, month, week = current if tone != "urgent" else (last or current)
        rows.append(
            {
                "source": "custom",
                "client_id": client_id,
                "client_name": client_name,
                "task": title,
                "status": CUSTOM_STATUS_LABELS["done"]
                if done
                else CUSTOM_STATUS_LABELS["in_progress"],
                "status_id": "done" if done else "in_progress",
                "due_date": due_date,
                "comment": str(task.get("comment") or "").strip(),
                "href": href,
                "week": week,
                "year": year,
                "month": month,
                "completed": done,
                "tone": tone,
                "content_type": "custom",
                "task_id": str(task.get("id") or ""),
            }
        )
    return rows


def _stage_label(stage: str) -> str:
    key = str(stage or "").strip()
    return STAGE_LABELS.get(key, key.replace("_", " ").title() if key else "")


def _in_memory_week_doc(client: dict, year: int, month: int, week: int) -> dict:
    slots = slots_for_week(client, year, month, week)
    return {
        "client_id": client["id"],
        "year": year,
        "month": month,
        "week": week,
        "cards": seed_default_cards(slots),
    }


def _weekly_rows_from_doc(
    client: dict,
    doc: dict | None,
    year: int,
    month: int,
    week: int,
    *,
    include_completed: bool,
    open_tone: str,
    types: set[str] | None = None,
) -> list[dict]:
    if week_is_before_start(client, year, month, week):
        return []
    if not doc:
        if week_is_before_current(year, month, week):
            return []
        doc = _in_memory_week_doc(client, year, month, week)
    client_id = client["id"]
    client_name = client.get("name") or "Untitled client"
    skip_weeks = {w for w in weeks_in_month(year, month) if w != week}
    rows = []
    for row in flatten_weekly_rows(
        {week: doc}, year, month, skip_weeks=skip_weeks
    ):
        if types is not None and row.get("content_type") not in types:
            continue
        if row.get("marking") == "did_not_track":
            continue
        done = _card_is_complete({
            "type": row.get("content_type"),
            "stage": row.get("stage"),
        })
        if done and not include_completed:
            continue
        label = row.get("content_type_label") or row.get("content_type") or "Task"
        stage = str(row.get("stage") or "")
        if open_tone == "upcoming":
            tone = (
                "completed"
                if done or stage in NEXT_WEEK_GREEN_STAGES
                else "upcoming"
            )
        else:
            tone = "completed" if done else open_tone
        status = row.get("stage_label") or _stage_label(stage) or stage
        card_id = str(row.get("card_id") or "").strip()
        href = f"/clients/{client_id}/tracker?year={year}&month={month}&week={week}"
        if card_id:
            href += f"&card={card_id}"
        rows.append(
            {
                "source": "default",
                "client_id": client_id,
                "client_name": client_name,
                "task": f"{label}-week {week}",
                "status": status,
                "status_id": row.get("stage") or "",
                "due_date": week_end_date(year, month, week),
                "comment": "",
                "href": href,
                "week": week,
                "year": year,
                "month": month,
                "completed": done,
                "tone": tone,
                "content_type": str(row.get("content_type") or ""),
            }
        )
    return rows


@router.post("/tracker.sheet.all", response_model=schemas.TrackerSheetAllResponse)
def tracker_sheet_all(
    body: schemas.TrackerSheetAllRequest,
    current_user: dict = Depends(get_current_user),
):
    _validate_month(body.year, body.month)
    username = current_user["username"]
    today = date.today()
    current = current_week_tuple(today)
    last = last_ended_week(today)
    nxt = _next_week_tuple(today)
    if last == current:
        last = None
    clients = [
        client
        for client in list_clients_for_user(username, with_topics=False)
        if client.get("is_active") is not False
    ]
    past_weeks = _past_week_keys(current, last, clients)
    week_keys = list(dict.fromkeys([current, nxt, *past_weeks]))
    client_ids = [client["id"] for client in clients]
    weekly_docs = fetch_weekly_trackers_by_ids(
        [
            weekly_tracker_doc_id(client_id, year, month, week)
            for client_id in client_ids
            for year, month, week in week_keys
        ]
    )
    custom_docs = fetch_custom_trackers_by_client_ids(client_ids)
    rows = []
    for client in clients:
        client_id = client["id"]
        client_name = client.get("name") or "Untitled client"
        current_doc = weekly_docs.get(weekly_tracker_doc_id(client_id, *current))
        next_doc = weekly_docs.get(weekly_tracker_doc_id(client_id, *nxt))
        rows.extend(
            _weekly_rows_from_doc(
                client,
                current_doc,
                *current,
                include_completed=True,
                open_tone="pending",
            )
        )
        for past in past_weeks:
            past_doc = weekly_docs.get(weekly_tracker_doc_id(client_id, *past))
            rows.extend(
                _weekly_rows_from_doc(
                    client,
                    past_doc,
                    *past,
                    include_completed=False,
                    open_tone="urgent",
                )
            )
        rows.extend(
            _pending_custom_rows(
                client_id, client_name, custom_docs.get(client_id), current, last
            )
        )
        rows.extend(
            _weekly_rows_from_doc(
                client,
                next_doc,
                *nxt,
                include_completed=True,
                open_tone="upcoming",
                types=VIDEO_TYPES,
            )
        )
    tone_rank = {"urgent": 0, "pending": 1, "completed": 2}
    rows.sort(
        key=lambda row: (
            tone_rank.get(row.get("tone") or "pending", 9),
            (row.get("due_date") or "9999-99-99"),
            (row.get("client_name") or "").lower(),
        )
    )
    return {"year": current[0], "month": current[1], "rows": rows}


@router.post("/tracker.sheet.weekly")
def tracker_sheet_weekly(
    body: schemas.TrackerSheetWeeklyRequest,
    current_user: dict = Depends(get_current_user),
):
    _validate_month(body.year, body.month)
    client = _require_videos_client(current_user["username"], body.client_id)
    skip_weeks = {
        week
        for week in weeks_in_month(body.year, body.month)
        if week_is_before_start(client, body.year, body.month, week)
    }
    docs = {}
    for week in weeks_in_month(body.year, body.month):
        if week in skip_weeks:
            continue
        docs[week] = _ensure_week(
            body.client_id,
            body.year,
            body.month,
            week,
            current_user["username"],
        )
    rows = flatten_weekly_rows(
        docs,
        body.year,
        body.month,
        skip_weeks=skip_weeks,
    )
    comments = list_sheet_comments_for_month(
        body.client_id, body.year, body.month, tracker="weekly"
    )
    return {
        "year": body.year,
        "month": body.month,
        "rows": rows,
        "comments": comments_map(comments),
    }


@router.post("/tracker.sheet.comment.save")
def tracker_sheet_comment_save(
    body: schemas.TrackerSheetCommentSaveRequest,
    current_user: dict = Depends(get_current_user),
):
    _validate_month(body.year, body.month)
    if body.week < 1 or body.week > 4:
        raise HTTPException(status_code=400, detail="Week must be 1-4")
    _require_videos_client(current_user["username"], body.client_id)
    row_key = str(body.row_key or "").strip()
    if not row_key:
        raise HTTPException(status_code=400, detail="row_key is required")
    saved = save_sheet_comment(
        {
            "client_id": body.client_id,
            "year": body.year,
            "month": body.month,
            "week": body.week,
            "tracker": "weekly",
            "row_key": row_key,
            "comment": str(body.comment or ""),
            "updated_at": _now_iso(),
            "updated_by": current_user["username"],
        }
    )
    return {"comment": saved}
