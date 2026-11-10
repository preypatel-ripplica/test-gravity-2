"""Edit-tracker assigner: daily long/short video work for editors."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.main.access_guards import (
    editor_id_from_auth,
    is_editor,
    require_editor_roster,
    require_internal,
)
from backend.main.auth import current_user
from backend.main.db import projects_col, weekly_trackers_col
from backend.main.models import ProjectStatus
from backend.trackers.crudl import STAGES, _ensure_week, _now_iso, _stage_index
from backend.trackers.editors import (
    EDITOR_FIELD_ID,
    EDITOR_FIELD_LABEL,
    VIDEO_TYPES,
    _hours_int,
    calendar_week_dates,
    default_editor_id,
    default_working_days,
    default_working_weekdays,
    edit_hours_for,
    editor_by_id,
    editor_list,
    editor_value_from_sections,
    ensure_editor_sections,
    hours_values_from_sections,
    late_editor_id,
    normalize_working_weekdays,
    working_dates,
)
from backend.trackers.models import weekly_doc_id
from backend.trackers.tracker_card_history import apply_card_history
from backend.trackers.tracker_settings import (
    current_week_tuple,
    is_did_not_track,
    last_ended_week,
    tracker_start_tuple,
    week_is_before_current,
    week_is_before_start,
)
from fastapi import Depends

router = APIRouter(tags=["edit-tracker"])


class EditBoardBody(BaseModel):
    week_offset: int = 0
    working_days: Optional[int] = None
    working_weekdays: list[int] = Field(default_factory=list)


class EditAssignBody(EditBoardBody):
    pass


class EditCardPatchBody(BaseModel):
    client_id: str
    year: int
    month: int
    week: int
    card_id: str
    editor_id: Optional[str] = None
    planned_edit_date: Optional[str] = None


class EditClientPrefsBody(BaseModel):
    client_id: str
    video_editor_id: Optional[str] = None
    long_video_hours: Optional[float] = None
    short_video_hours: Optional[float] = None


def _iso(day: date) -> str:
    return day.isoformat()


def _parse_iso(raw) -> date | None:
    text = str(raw or "").strip()[:10]
    if len(text) < 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _is_video(card: dict) -> bool:
    return str(card.get("type") or "") in VIDEO_TYPES


# Editor board keeps work through video_edited. shared_with_doctor and later drop off.
_EDIT_BOARD_LAST_STAGE = "video_edited"


def _open_video(card: dict) -> bool:
    if not isinstance(card, dict) or not _is_video(card):
        return False
    if is_did_not_track(card.get("marking")):
        return False
    card_type = str(card.get("type") or "")
    stages = STAGES.get(card_type) or []
    if _EDIT_BOARD_LAST_STAGE not in stages:
        return True
    stage = str(card.get("stage") or "planned").strip() or "planned"
    return _stage_index(card_type, stage) <= _stage_index(card_type, _EDIT_BOARD_LAST_STAGE)


def _hydrate_card(card: dict, project: dict, late: bool, *, fill_editor: bool = True) -> dict:
    next_card = dict(card)
    overridden = bool(next_card.get("editor_overridden"))
    editor_id = str(next_card.get("editor_id") or "").strip()
    if fill_editor and not overridden:
        next_card["editor_id"] = default_editor_id(project, late=late)
    elif editor_id and not editor_by_id(editor_id):
        next_card["editor_id"] = default_editor_id(project, late=late)
    next_card["edit_hours"] = edit_hours_for(project, next_card.get("type"))
    next_card.setdefault("planned_edit_date", "")
    return next_card


def _active_projects() -> list[dict]:
    return list(
        projects_col().find(
            {"status": {"$ne": ProjectStatus.ARCHIVED.value}},
            {"_id": 0},
        )
    )


def _shift_week(year: int, month: int, week: int, delta: int = 1) -> tuple[int, int, int]:
    week = int(week) + int(delta)
    year = int(year)
    month = int(month)
    while week > 4:
        week -= 4
        month += 1
        if month > 12:
            month = 1
            year += 1
    while week < 1:
        week += 4
        month -= 1
        if month < 1:
            month = 12
            year -= 1
    return year, month, week


def _clamp_week_offset(raw) -> int:
    try:
        offset = int(raw or 0)
    except (TypeError, ValueError):
        offset = 0
    return 1 if offset >= 1 else 0


def _target_week(today: date, week_offset: int) -> tuple[int, int, int]:
    current = current_week_tuple(today)
    if week_offset:
        return _shift_week(*current, week_offset)
    return current


def _week_meta(offset: int, today: date) -> dict:
    days = calendar_week_dates(today, offset)
    year, month, week = _target_week(today, offset)
    start, end = days[0], days[-1]
    return {
        "offset": offset,
        "year": year,
        "month": month,
        "week": week,
        "label": "This week" if offset == 0 else "Next week",
        "range_label": f"{start.day} {start.strftime('%b')} – {end.day} {end.strftime('%b')}",
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def _append_open_cards(items: list[dict], project: dict, doc: dict, late: bool, actor: str) -> None:
    del actor
    for card in doc.get("cards") or []:
        if not _open_video(card):
            continue
        hydrated = _hydrate_card(card, project, late)
        items.append(_item_from_card(project, doc, hydrated, late))


def _ensure_open_week(
    items: list[dict],
    project: dict,
    target: tuple[int, int, int],
    actor: str,
    *,
    create_missing: bool,
) -> None:
    if week_is_before_start(project, *target):
        return
    already = any(
        row.get("client_id") == project.get("id")
        and (row.get("year"), row.get("month"), row.get("week")) == target
        for row in items
    )
    if already:
        return
    doc_id = weekly_doc_id(project["id"], *target)
    doc = weekly_trackers_col().find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        if not create_missing:
            return
        doc = _ensure_week(project["id"], *target, actor)
    _append_open_cards(items, project, doc, False, actor)


def _collect_items(actor: str, week_offset: int = 0, *, create_missing: bool = False) -> list[dict]:
    today = date.today()
    week_offset = _clamp_week_offset(week_offset)
    current = current_week_tuple(today)
    target = _target_week(today, week_offset)
    include_late = week_offset == 0
    last = last_ended_week(today) if include_late else None
    items = []
    for project in _active_projects():
        project_id = project.get("id")
        if not project_id:
            continue
        if include_late:
            for doc in weekly_trackers_col().find({"project_id": project_id}, {"_id": 0}):
                try:
                    year = int(doc.get("year"))
                    month = int(doc.get("month"))
                    week = int(doc.get("week"))
                except (TypeError, ValueError):
                    continue
                if week_is_before_start(project, year, month, week):
                    continue
                late = week_is_before_current(year, month, week, today)
                current_week = (year, month, week) == current
                if not late and not current_week:
                    continue
                if late and last and (year, month, week) > last:
                    continue
                _append_open_cards(items, project, doc, late, actor)
            _ensure_open_week(items, project, target, actor, create_missing=create_missing)
        else:
            _ensure_open_week(items, project, target, actor, create_missing=create_missing)
    items.sort(key=lambda row: (
        0 if row["late"] else 1,
        row.get("due_date") or "",
        (row.get("client_name") or "").lower(),
        row.get("type") or "",
    ))
    return items


def _note_preview(notes: list | None, *, limit: int = 2) -> list[dict]:
    out = []
    for note in notes or []:
        if not isinstance(note, dict):
            continue
        text = str(note.get("text") or "").strip()
        if not text and not (note.get("attachments") or []):
            continue
        out.append(
            {
                "id": note.get("id") or "",
                "text": text[:240],
                "created_by": note.get("created_by") or "",
                "created_at": note.get("created_at") or "",
            }
        )
        if len(out) >= limit:
            break
    return out


def _item_from_card(project: dict, doc: dict, card: dict, late: bool) -> dict:
    editor = editor_by_id(card.get("editor_id")) or {}
    feedback = list(card.get("feedback_notes") or [])
    editor_notes = list(card.get("editor_notes") or [])
    return {
        "client_id": project.get("id"),
        "client_name": project.get("name") or "Untitled",
        "year": doc.get("year"),
        "month": doc.get("month"),
        "week": doc.get("week"),
        "card_id": card.get("id"),
        "title": card.get("title") or "",
        "type": card.get("type"),
        "stage": card.get("stage") or "planned",
        "late": late,
        "editor_id": card.get("editor_id") or "",
        "editor_name": editor.get("name") or card.get("editor_id") or "",
        "edit_hours": float(card.get("edit_hours") or edit_hours_for(project, card.get("type"))),
        "planned_edit_date": str(card.get("planned_edit_date") or "").strip()[:10],
        "feedback_note_count": len(feedback),
        "editor_note_count": len(editor_notes),
        "feedback_notes_preview": _note_preview(feedback[-2:]),
        "editor_notes_preview": _note_preview(editor_notes[-2:]),
        "href": (
            f"/clients/{project.get('id')}/tracker"
            f"?year={doc.get('year')}&month={doc.get('month')}"
            f"&week={doc.get('week')}&card={card.get('id')}"
        ),
    }


def _filter_items_for_auth(items: list[dict], auth: dict) -> list[dict]:
    if not is_editor(auth):
        return items
    editor_id = editor_id_from_auth(auth)
    return [item for item in items if str(item.get("editor_id") or "").strip() == editor_id]


def _item_hours(item: dict) -> float:
    try:
        return float(item.get("edit_hours") or 0)
    except (TypeError, ValueError):
        return 0.0


def _fits(load: float, hours: float, cap: float) -> bool:
    return load + hours <= cap + 1e-9


def _assign_sort_key(row: dict) -> tuple:
    return (
        0 if row.get("late") else 1,
        1 if _script_pending(row) else 0,
        -_item_hours(row),
    )


def _day_hours(items: list[dict], week_dates: list[str]) -> dict[str, dict[str, float]]:
    allowed = set(week_dates)
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for item in items:
        day = item.get("planned_edit_date") or ""
        editor_id = item.get("editor_id") or ""
        if not editor_id or day not in allowed:
            continue
        totals[editor_id][day] += _item_hours(item)
    return totals


def _annotate_spill(items: list[dict], week_dates: list[str]) -> list[dict]:
    week_set = set(week_dates)
    caps = {row["id"]: int(row.get("max_hours_per_day") or 0) for row in editor_list()}
    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, item in enumerate(items):
        day = str(item.get("planned_edit_date") or "").strip()
        editor_id = str(item.get("editor_id") or "").strip()
        if editor_id and day in week_set:
            grouped[(editor_id, day)].append(index)
    overflow = set()
    for (editor_id, _day), indexes in grouped.items():
        cap = caps.get(editor_id) or 0
        used = 0.0
        for index in sorted(indexes, key=lambda i: _assign_sort_key(items[i])):
            hours = _item_hours(items[index])
            if cap and not _fits(used, hours, cap):
                overflow.add(index)
                continue
            used += hours
    totals = _day_hours(
        [item for index, item in enumerate(items) if index not in overflow],
        week_dates,
    )
    out = []
    for index, item in enumerate(items):
        next_item = dict(item)
        editor = editor_by_id(item.get("editor_id"))
        cap = int((editor or {}).get("max_hours_per_day") or 0)
        day = str(item.get("planned_edit_date") or "").strip()
        if index in overflow:
            next_item["planned_edit_date"] = ""
            day = ""
        spill = not day or day not in week_set
        next_item["spill"] = spill
        next_item["spill_reason"] = "unassigned" if spill else ""
        next_item["day_hours"] = totals.get(item.get("editor_id") or "", {}).get(day, 0)
        next_item["max_hours"] = cap
        out.append(next_item)
    return out


_CARD_EDIT_FIELDS = ("editor_id", "planned_edit_date", "editor_overridden")


def _save_card_fields(item: dict, patch: dict, actor: str) -> dict | None:
    allowed = {key: patch[key] for key in _CARD_EDIT_FIELDS if key in patch}
    if not allowed:
        return None
    doc_id = weekly_doc_id(item["client_id"], item["year"], item["month"], item["week"])
    card_id = str(item["card_id"])
    doc = weekly_trackers_col().find_one({"id": doc_id}, {"_id": 0, "id": 1, "cards": 1})
    if not doc:
        return None
    found = None
    for card in doc.get("cards") or []:
        if str(card.get("id")) != card_id:
            continue
        found = dict(card)
        break
    if found is None:
        return None
    previous = dict(found)
    next_card = {**found, **allowed}
    apply_card_history(previous, next_card, by=actor)
    sets = {f"cards.$[card].{key}": next_card[key] for key in allowed}
    if next_card.get("history") != found.get("history"):
        sets["cards.$[card].history"] = next_card.get("history") or []
    sets["updated_at"] = _now_iso()
    sets["updated_by"] = actor
    result = weekly_trackers_col().update_one(
        {"id": doc_id, "cards.id": found.get("id")},
        {"$set": sets},
        array_filters=[{"card.id": found.get("id")}],
    )
    if not result.matched_count:
        return None
    return next_card


def _resolve_weekdays(body: EditBoardBody | None) -> list[int]:
    if body and body.working_weekdays:
        return normalize_working_weekdays(body.working_weekdays, fallback=False) or default_working_weekdays()
    if body and body.working_days:
        return list(range(max(1, min(7, int(body.working_days)))))
    return default_working_weekdays()


_LATER_STAGES = {"", "planned", "script_generated"}


def _script_pending(item: dict) -> bool:
    stage = str(item.get("stage") or "planned").strip() or "planned"
    return stage in _LATER_STAGES


def _lowest_load_day(days: list[str], day_hours: dict[str, float], hours: float, cap: float) -> str | None:
    best = None
    best_load = None
    for day in days:
        load = day_hours[day]
        if not _fits(load, hours, cap):
            continue
        if best is None or load < best_load:
            best = day
            best_load = load
    return best


def _choose_day(working_iso: list[str], day_hours: dict[str, float], hours: float, cap: float, *, prefer_late: bool) -> str | None:
    if not working_iso:
        return None
    ordered = list(reversed(working_iso)) if prefer_late else list(working_iso)
    split = max(1, (len(ordered) + 1) // 2)
    return _lowest_load_day(ordered[:split], day_hours, hours, cap) or _lowest_load_day(ordered[split:], day_hours, hours, cap)


def _assign(items: list[dict], working: list[date], actor: str) -> list[dict]:
    working_iso = [_iso(day) for day in working]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        editor_id = item.get("editor_id") or late_editor_id()
        if not editor_by_id(editor_id):
            editor_id = late_editor_id()
            item["editor_id"] = editor_id
        grouped[editor_id].append(item)

    for editor_id, rows in grouped.items():
        editor = editor_by_id(editor_id) or {}
        cap = float(editor.get("max_hours_per_day") or 0)
        day_hours = {day: 0.0 for day in working_iso}
        rows.sort(key=_assign_sort_key)
        for item in rows:
            hours = _item_hours(item)
            prefer_late = (not item.get("late")) and _script_pending(item)
            best = _choose_day(working_iso, day_hours, hours, cap, prefer_late=prefer_late)
            patch = {"editor_id": editor_id}
            if best:
                patch["planned_edit_date"] = best
                day_hours[best] += hours
            else:
                patch["planned_edit_date"] = ""
            saved = _save_card_fields(item, patch, actor)
            item.update(patch)
            if saved and saved.get("edit_hours") not in (None, ""):
                item["edit_hours"] = saved.get("edit_hours")
    return items


def _board_payload(items: list[dict], *, week_offset: int, working_weekdays: list[int], today: date | None = None) -> dict:
    today = today or date.today()
    week_offset = _clamp_week_offset(week_offset)
    weekdays = normalize_working_weekdays(working_weekdays)
    days = calendar_week_dates(today, week_offset)
    week_dates = [_iso(day) for day in days]
    wanted = set(weekdays)
    annotated = _annotate_spill(items, week_dates)
    editors_in_use = []
    seen = set()
    for item in annotated:
        editor_id = item.get("editor_id")
        if editor_id and editor_id not in seen:
            seen.add(editor_id)
            editors_in_use.append(editor_by_id(editor_id) or {"id": editor_id, "name": editor_id})
    editors_in_use.sort(key=lambda row: (row.get("name") or "").lower())
    return {
        "editors": editor_list(),
        "week_offset": week_offset,
        "week": _week_meta(week_offset, today),
        "weeks": [_week_meta(0, today), _week_meta(1, today)],
        "working_days": len(weekdays),
        "working_weekdays": weekdays,
        "days": [
            {
                "date": _iso(day),
                "weekday": day.strftime("%A"),
                "short": day.strftime("%a")[0],
                "label": day.strftime("%a %d %b"),
                "weekday_index": day.weekday(),
                "working": day.weekday() in wanted,
            }
            for day in days
        ],
        "editors_in_use": editors_in_use,
        "items": annotated,
    }


@router.post("/edit.tracker.meta")
def edit_tracker_meta(auth: dict = Depends(current_user)):
    scoped_editor_id = require_editor_roster(auth)
    today = date.today()
    editors = editor_list()
    if scoped_editor_id:
        editors = [row for row in editors if row.get("id") == scoped_editor_id]
    return {
        "editors": editors,
        "late_editor_id": late_editor_id(),
        "default_working_days": default_working_days(),
        "default_working_weekdays": default_working_weekdays(),
        "weeks": [_week_meta(0, today), _week_meta(1, today)],
        "edit_hours": load_hours(),
        "scoped_editor_id": scoped_editor_id or None,
        "can_assign": not bool(scoped_editor_id),
        "can_manage_settings": not bool(scoped_editor_id),
    }


def load_hours() -> dict:
    from backend.trackers.editors import load_editor_config
    return dict(load_editor_config().get("edit_hours") or {})


@router.post("/edit.tracker.board")
def edit_tracker_board(body: EditBoardBody | None = None, auth: dict = Depends(current_user)):
    scoped_editor_id = require_editor_roster(auth)
    actor = auth.get("email") or auth["user_id"]
    week_offset = _clamp_week_offset(body.week_offset if body else 0)
    weekdays = _resolve_weekdays(body)
    items = _collect_items(actor, week_offset, create_missing=False)
    items = _filter_items_for_auth(items, auth)
    payload = _board_payload(items, week_offset=week_offset, working_weekdays=weekdays)
    payload["scoped_editor_id"] = scoped_editor_id or None
    payload["can_assign"] = not bool(scoped_editor_id)
    payload["can_manage_settings"] = not bool(scoped_editor_id)
    return payload


@router.post("/edit.tracker.assign")
def edit_tracker_assign(body: EditAssignBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    actor = auth.get("email") or auth["user_id"]
    week_offset = _clamp_week_offset(body.week_offset)
    weekdays = _resolve_weekdays(body)
    if not weekdays:
        raise HTTPException(400, "Select at least one working day")
    working = working_dates(weekdays=weekdays, week_offset=week_offset)
    if not working:
        raise HTTPException(400, "Select at least one working day")
    items = _collect_items(actor, week_offset, create_missing=True)
    items = _assign(items, working, actor)
    return _board_payload(items, week_offset=week_offset, working_weekdays=weekdays)


def _client_settings_row(project: dict) -> dict:
    editor_id = str(project.get("video_editor_id") or "").strip()
    if not editor_by_id(editor_id):
        editor_id = editor_value_from_sections(project.get("profile_sections") or [])
    if not editor_by_id(editor_id):
        editor_id = ""
    return {
        "client_id": project.get("id") or "",
        "name": project.get("name") or "Untitled",
        "video_editor_id": editor_id,
        "long_video_hours": edit_hours_for(project, "long_video"),
        "short_video_hours": edit_hours_for(project, "short"),
    }


def _propagate_client_prefs(project: dict) -> None:
    client_id = project.get("id")
    if not client_id:
        return
    now = _now_iso()
    for doc in weekly_trackers_col().find(
        {"$or": [{"project_id": client_id}, {"client_id": client_id}]},
        {"_id": 0, "id": 1, "year": 1, "month": 1, "week": 1, "cards": 1},
    ):
        try:
            late = week_is_before_current(int(doc.get("year")), int(doc.get("month")), int(doc.get("week")))
        except (TypeError, ValueError):
            late = False
        for card in doc.get("cards") or []:
            if not isinstance(card, dict) or not _is_video(card):
                continue
            card_id = card.get("id")
            if not card_id:
                continue
            sets = {}
            if not card.get("editor_overridden"):
                editor_id = default_editor_id(project, late=late)
                if editor_id != str(card.get("editor_id") or "").strip():
                    sets["cards.$[card].editor_id"] = editor_id
            hours = edit_hours_for(project, card.get("type"))
            try:
                stored_hours = float(card.get("edit_hours") or 0)
            except (TypeError, ValueError):
                stored_hours = 0
            if hours != stored_hours:
                sets["cards.$[card].edit_hours"] = hours
            if not sets:
                continue
            sets["updated_at"] = now
            weekly_trackers_col().update_one(
                {"id": doc["id"], "cards.id": card_id},
                {"$set": sets},
                array_filters=[{"card.id": card_id}],
            )


def _save_client_prefs(project: dict, body: EditClientPrefsBody) -> dict:
    editor_id = str(project.get("video_editor_id") or "").strip()
    if body.video_editor_id is not None:
        editor_id = str(body.video_editor_id or "").strip()
        if editor_id and not editor_by_id(editor_id):
            raise HTTPException(400, "Unknown editor")
    long_hours = body.long_video_hours
    short_hours = body.short_video_hours
    if long_hours is not None:
        long_hours = _hours_int(long_hours, edit_hours_for(project, "long_video"))
    if short_hours is not None:
        short_hours = _hours_int(short_hours, edit_hours_for(project, "short"))
    sections = ensure_editor_sections(
        project.get("profile_sections") or [],
        editor_id=editor_id,
        long_hours=long_hours,
        short_hours=short_hours,
        project=project,
    )
    if body.video_editor_id is not None:
        for section in sections:
            for field in section.get("fields") or []:
                if not isinstance(field, dict):
                    continue
                if field.get("id") == EDITOR_FIELD_ID or str(field.get("label") or "").strip() == EDITOR_FIELD_LABEL:
                    field["value"] = editor_id
    hours = hours_values_from_sections(sections, project)
    patch = {
        "profile_sections": sections,
        "video_editor_id": editor_id or None,
        "long_video_hours": hours["long_video_hours"],
        "short_video_hours": hours["short_video_hours"],
        "updated_at": _now_iso(),
    }
    projects_col().update_one({"id": project["id"]}, {"$set": patch})
    updated = {**project, **patch}
    _propagate_client_prefs(updated)
    return _client_settings_row(updated)


@router.post("/edit.tracker.settings")
def edit_tracker_settings(auth: dict = Depends(current_user)):
    require_internal(auth)
    clients = sorted(_active_projects(), key=lambda row: str(row.get("name") or "").lower())
    return {
        "editors": editor_list(),
        "clients": [_client_settings_row(project) for project in clients],
    }


@router.post("/edit.tracker.settings.patch")
def edit_tracker_settings_patch(body: EditClientPrefsBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    project = projects_col().find_one({"id": body.client_id}, {"_id": 0}) or {}
    if not project:
        raise HTTPException(404, "Client not found")
    if (
        body.video_editor_id is None
        and body.long_video_hours is None
        and body.short_video_hours is None
    ):
        raise HTTPException(400, "Nothing to update")
    return {"client": _save_client_prefs(project, body)}


@router.post("/edit.tracker.card.patch")
def edit_tracker_card_patch(body: EditCardPatchBody, auth: dict = Depends(current_user)):
    scoped_editor_id = require_editor_roster(auth)
    actor = auth.get("email") or auth["user_id"]
    project = projects_col().find_one({"id": body.client_id}, {"_id": 0}) or {}
    if not project:
        raise HTTPException(404, "Client not found")
    patch: dict[str, Any] = {}
    if body.editor_id is not None:
        if scoped_editor_id:
            raise HTTPException(403, "Editors cannot reassign cards")
        if body.editor_id and not editor_by_id(body.editor_id):
            raise HTTPException(400, "Unknown editor")
        patch["editor_id"] = body.editor_id
        patch["editor_overridden"] = True
    if body.planned_edit_date is not None:
        if scoped_editor_id:
            raise HTTPException(403, "Editors cannot change edit day")
        raw = str(body.planned_edit_date or "").strip()
        if raw and _parse_iso(raw) is None:
            raise HTTPException(400, "planned_edit_date must be YYYY-MM-DD")
        patch["planned_edit_date"] = raw[:10] if raw else ""
    if not patch:
        raise HTTPException(400, "Nothing to update")
    if scoped_editor_id:
        doc_id = weekly_doc_id(body.client_id, body.year, body.month, body.week)
        existing = weekly_trackers_col().find_one({"id": doc_id}, {"_id": 0, "cards": 1}) or {}
        card = next(
            (
                row
                for row in (existing.get("cards") or [])
                if str(row.get("id")) == str(body.card_id)
            ),
            None,
        )
        if not card or str(card.get("editor_id") or "").strip() != scoped_editor_id:
            raise HTTPException(403, "Card is not assigned to you")
    item = {
        "client_id": body.client_id,
        "year": body.year,
        "month": body.month,
        "week": body.week,
        "card_id": body.card_id,
    }
    saved = _save_card_fields(item, patch, actor)
    if not saved:
        raise HTTPException(404, "Card not found")
    late = week_is_before_current(body.year, body.month, body.week)
    hydrated = _hydrate_card(saved, project, late, fill_editor="editor_id" not in patch)
    return {
        "item": _item_from_card(
            project,
            {"year": body.year, "month": body.month, "week": body.week},
            hydrated,
            late,
        )
    }
