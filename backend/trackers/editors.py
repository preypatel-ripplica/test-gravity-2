"""Hardcoded editor roster and video-edit hours."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

EDITORS_PATH = Path(__file__).with_name("editors.json")
EDITOR_FIELD_ID = "fld-video-editor"
EDITOR_FIELD_LABEL = "Editor"
LONG_HOURS_FIELD_ID = "fld-long-video-hours"
LONG_HOURS_FIELD_LABEL = "Long video hours"
SHORT_HOURS_FIELD_ID = "fld-short-video-hours"
SHORT_HOURS_FIELD_LABEL = "Short video hours"
VIDEO_EDITING_TITLE = "Video Editing / Generation"
VIDEO_TYPES = {"long_video", "short"}
_DOCTOR_NAME = re.compile(r"^dr\.?\b", re.I)
HOUR_FIELDS = (
    (LONG_HOURS_FIELD_ID, LONG_HOURS_FIELD_LABEL, "long_video"),
    (SHORT_HOURS_FIELD_ID, SHORT_HOURS_FIELD_LABEL, "short"),
)


@lru_cache(maxsize=1)
def load_editor_config() -> dict:
    return json.loads(EDITORS_PATH.read_text())


def editor_list() -> list[dict]:
    return [dict(row) for row in load_editor_config()["editors"]]


def editor_by_id(editor_id: str | None) -> dict | None:
    key = str(editor_id or "").strip()
    for row in editor_list():
        if row["id"] == key:
            return dict(row)
    return None


def late_editor_id() -> str:
    return str(load_editor_config().get("late_editor_id") or "test-editor")


def default_working_days() -> int:
    return int(load_editor_config().get("default_working_days") or 6)


def is_doctor_client(project: dict | None) -> bool:
    if not isinstance(project, dict):
        return False
    name = str(project.get("name") or "").strip()
    if _DOCTOR_NAME.match(name):
        return True
    if str(project.get("specialty") or "").strip():
        return True
    if str(project.get("designation") or "").strip():
        return True
    return False


def default_edit_hours(project: dict | None) -> int:
    hours = load_editor_config().get("edit_hours") or {}
    if is_doctor_client(project):
        return int(hours.get("doctor") or 1)
    return int(hours.get("non_doctor") or 2)


def _snap_hours(value, fallback: float = 1) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        try:
            number = float(fallback)
        except (TypeError, ValueError):
            number = 1.0
    snapped = round(number * 2) / 2
    if snapped < 0.5:
        return 0.5
    if snapped > 12:
        return 12.0
    return snapped


def _hours_int(raw, fallback: float = 1) -> float:
    try:
        return _snap_hours(str(raw).strip(), fallback)
    except (TypeError, ValueError):
        return _snap_hours(fallback)


def hours_from_sections(sections, card_type: str | None, fallback: float) -> float:
    wanted_id = SHORT_HOURS_FIELD_ID if card_type == "short" else LONG_HOURS_FIELD_ID
    wanted_label = SHORT_HOURS_FIELD_LABEL if card_type == "short" else LONG_HOURS_FIELD_LABEL
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        for field in section.get("fields") or []:
            if not isinstance(field, dict):
                continue
            if field.get("id") == wanted_id or str(field.get("label") or "").strip() == wanted_label:
                return _hours_int(field.get("value"), fallback)
    return fallback


def edit_hours_for(project: dict | None, card_type: str | None = None) -> float:
    project = project or {}
    fallback = default_edit_hours(project)
    key = "short_video_hours" if card_type == "short" else "long_video_hours"
    stored = project.get(key)
    if stored not in (None, ""):
        return _hours_int(stored, fallback)
    return hours_from_sections(project.get("profile_sections") or [], card_type, fallback)


def hours_values_from_sections(sections, project: dict | None = None) -> dict[str, float]:
    fallback = default_edit_hours(project)
    return {
        "long_video_hours": hours_from_sections(sections, "long_video", fallback),
        "short_video_hours": hours_from_sections(sections, "short", fallback),
    }


def calendar_week_dates(today: date | None = None, week_offset: int = 0) -> list[date]:
    today = today or date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=int(week_offset or 0))
    return [monday + timedelta(days=offset) for offset in range(7)]


def default_working_weekdays() -> list[int]:
    return list(range(max(1, min(7, default_working_days()))))


def normalize_working_weekdays(raw, *, fallback: bool = True) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for item in raw or []:
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6 and day not in seen:
            seen.add(day)
            out.append(day)
    out.sort()
    if out:
        return out
    return default_working_weekdays() if fallback else []


def working_dates(
    working_days: int | None = None,
    today: date | None = None,
    *,
    weekdays: list[int] | None = None,
    week_offset: int = 0,
) -> list[date]:
    days = calendar_week_dates(today, week_offset)
    if weekdays is not None:
        wanted = set(normalize_working_weekdays(weekdays, fallback=False))
        return [day for day in days if day.weekday() in wanted]
    count = max(1, min(7, int(working_days or default_working_days())))
    return days[:count]


def default_editor_id(project: dict | None, *, late: bool) -> str:
    stored = str((project or {}).get("video_editor_id") or "").strip()
    if editor_by_id(stored):
        return stored
    if late:
        return late_editor_id()
    return editor_list()[0]["id"]


def editor_value_from_sections(sections) -> str:
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        for field in section.get("fields") or []:
            if not isinstance(field, dict):
                continue
            if field.get("id") == EDITOR_FIELD_ID or str(field.get("label") or "").strip() == EDITOR_FIELD_LABEL:
                value = str(field.get("value") or "").strip()
                if editor_by_id(value):
                    return value
    return ""


def ensure_editor_sections(
    sections,
    editor_id: str = "",
    long_hours=None,
    short_hours=None,
    project: dict | None = None,
) -> list[dict]:
    rows = [dict(section) for section in (sections or []) if isinstance(section, dict)]
    chosen = editor_id or editor_value_from_sections(rows) or ""
    fallback = default_edit_hours(project)
    video = None
    for section in rows:
        if str(section.get("title") or "").strip() == VIDEO_EDITING_TITLE:
            video = section
            break
    if video is None:
        video = {"id": "sec-video-editing", "title": VIDEO_EDITING_TITLE, "is_default": True, "fields": []}
        rows.insert(0, video)
    fields = [dict(field) for field in (video.get("fields") or []) if isinstance(field, dict)]
    editor_field = None
    hour_fields = {}
    kept = []
    for field in fields:
        label = str(field.get("label") or "").strip()
        if field.get("id") == EDITOR_FIELD_ID or label == EDITOR_FIELD_LABEL:
            editor_field = field
            continue
        matched = False
        for field_id, field_label, _kind in HOUR_FIELDS:
            if field.get("id") == field_id or label == field_label:
                hour_fields[field_id] = field
                matched = True
                break
        if not matched:
            kept.append(field)
    editor_field = editor_field or {"id": EDITOR_FIELD_ID, "label": EDITOR_FIELD_LABEL, "value": ""}
    editor_field["id"] = EDITOR_FIELD_ID
    editor_field["label"] = EDITOR_FIELD_LABEL
    if chosen:
        editor_field["value"] = chosen
    preset = {
        LONG_HOURS_FIELD_ID: long_hours if long_hours not in (None, "") else hours_from_sections(rows, "long_video", fallback),
        SHORT_HOURS_FIELD_ID: short_hours if short_hours not in (None, "") else hours_from_sections(rows, "short", fallback),
    }
    if project:
        if project.get("long_video_hours") not in (None, "") and long_hours in (None, ""):
            preset[LONG_HOURS_FIELD_ID] = project.get("long_video_hours")
        if project.get("short_video_hours") not in (None, "") and short_hours in (None, ""):
            preset[SHORT_HOURS_FIELD_ID] = project.get("short_video_hours")
    pinned = [editor_field]
    for field_id, field_label, _kind in HOUR_FIELDS:
        field = hour_fields.get(field_id) or {"id": field_id, "label": field_label, "value": ""}
        field["id"] = field_id
        field["label"] = field_label
        hours = _hours_int(preset.get(field_id, field.get("value")), fallback)
        field["value"] = str(int(hours) if hours == int(hours) else hours)
        pinned.append(field)
    video["fields"] = [*pinned, *kept]
    return rows
