"""Per-card timeline of status and data changes."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from backend.trackers.tracker_settings import MARKING_DID_NOT_TRACK, is_did_not_track, normalize_marking
from backend.tg.services.tracker_sheet import STAGE_LABELS, TYPE_LABELS

HISTORY_CAP = 200
COALESCE_SECONDS = 180
COALESCE_KINDS = {"title"}
ASSET_LABELS = {
    "script_text": "Script",
    "script_url": "Script file",
    "audio_url": "Audio",
    "video_url": "Video",
}
PLATFORM_LABELS = {
    "youtube": "YouTube",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "website": "Website",
    "other": "Other",
}
LANG_LABELS = {
    "hinglish": "Hinglish",
    "arabic": "Arabic",
    "russian": "Russian",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return f"hist-{uuid4().hex[:12]}"


def _clean_text(value) -> str:
    return str(value or "").strip()


def _short(value, limit: int = 80) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _parse_at(value) -> datetime | None:
    raw = _clean_text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _stage_label(stage_id: str) -> str:
    key = _clean_text(stage_id) or "planned"
    return STAGE_LABELS.get(key, key.replace("_", " ").title())


def _type_label(card_type: str) -> str:
    return TYPE_LABELS.get(card_type or "", (card_type or "card").replace("_", " ").title())


def _dest_label(dest: dict) -> str:
    platform = PLATFORM_LABELS.get(dest.get("platform") or "", str(dest.get("platform") or "Link").title())
    lang = LANG_LABELS.get(str(dest.get("language") or "").strip().lower(), "")
    return f"{platform} ({lang})" if lang else platform


def history_event(kind: str, label: str, *, detail: str = "", by: str = "") -> dict:
    return {
        "id": _new_id(),
        "at": _now_iso(),
        "by": _clean_text(by),
        "kind": kind,
        "label": label,
        "detail": _clean_text(detail),
    }


def normalize_history(rows) -> list[dict]:
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        label = _clean_text(row.get("label"))
        if not label:
            continue
        out.append({
            "id": _clean_text(row.get("id")) or _new_id(),
            "at": _clean_text(row.get("at")) or _now_iso(),
            "by": _clean_text(row.get("by")),
            "kind": _clean_text(row.get("kind")) or "update",
            "label": label,
            "detail": _clean_text(row.get("detail")),
        })
    return out[-HISTORY_CAP:]


def _can_coalesce(last: dict | None, event: dict) -> bool:
    if not last or last.get("kind") != event.get("kind"):
        return False
    if last.get("kind") not in COALESCE_KINDS:
        return False
    if _clean_text(last.get("by")) != _clean_text(event.get("by")):
        return False
    last_at = _parse_at(last.get("at"))
    next_at = _parse_at(event.get("at"))
    if not last_at or not next_at:
        return False
    return abs((next_at - last_at).total_seconds()) <= COALESCE_SECONDS


def merge_history(base, events, *, by: str = "") -> list[dict]:
    history = normalize_history(base)
    for event in events or []:
        if not isinstance(event, dict):
            continue
        row = {
            **event,
            "id": _clean_text(event.get("id")) or _new_id(),
            "at": _clean_text(event.get("at")) or _now_iso(),
            "by": _clean_text(event.get("by")) or _clean_text(by),
            "kind": _clean_text(event.get("kind")) or "update",
            "label": _clean_text(event.get("label")),
            "detail": _clean_text(event.get("detail")),
        }
        if not row["label"]:
            continue
        last = history[-1] if history else None
        if _can_coalesce(last, row):
            last["at"] = row["at"]
            last["detail"] = row["detail"] or last.get("detail") or ""
            last["label"] = row["label"] or last.get("label") or ""
            continue
        history.append(row)
    return history[-HISTORY_CAP:]


def _note_ids(card: dict | None, key: str) -> set[str]:
    ids = set()
    for note in (card or {}).get(key) or []:
        if isinstance(note, dict) and note.get("id"):
            ids.add(str(note["id"]))
    return ids


def _file_ids(card: dict | None, key: str) -> dict[str, dict]:
    out = {}
    for row in (card or {}).get(key) or []:
        if isinstance(row, dict) and (row.get("id") or row.get("url")):
            out[str(row.get("id") or row.get("url"))] = row
    return out


def _filled_dests(card: dict | None) -> dict[str, dict]:
    out = {}
    for dest in (card or {}).get("destinations") or []:
        if not isinstance(dest, dict):
            continue
        url = _clean_text(dest.get("url"))
        if not url:
            continue
        key = str(dest.get("id") or "") or f"{dest.get('language')}-{dest.get('platform')}-{url}"
        out[key] = dest
    return out


def _empty_snapshot(card_type: str) -> dict:
    return {
        "type": card_type,
        "title": "",
        "stage": "planned",
        "marking": "none",
        "assets": {},
        "destinations": [],
        "generated_post_ids": [],
        "feedback_notes": [],
        "doctor_notes": [],
        "doctor_files": [],
        "content_plan_item_id": None,
        "delay_reason": "",
        "delay_proofs": [],
        "history": [],
    }


def diff_card_history(previous: dict | None, incoming: dict) -> list[dict]:
    events: list[dict] = []
    if not isinstance(incoming, dict):
        return events
    is_new = previous is None
    before = previous if isinstance(previous, dict) else _empty_snapshot(incoming.get("type") or "")
    if is_new:
        events.append(history_event("created", f"{_type_label(incoming.get('type'))} card added"))

    before_stage = _clean_text(before.get("stage")) or "planned"
    next_stage = _clean_text(incoming.get("stage")) or "planned"
    if before_stage != next_stage:
        events.append(history_event(
            "stage",
            f"Status changed to {_stage_label(next_stage)}",
            detail=f"{_stage_label(before_stage)} → {_stage_label(next_stage)}",
        ))

    before_marking = normalize_marking(before.get("marking"))
    next_marking = normalize_marking(incoming.get("marking"))
    if before_marking != next_marking:
        if is_did_not_track(next_marking):
            events.append(history_event("marking", "Marked as did not track"))
        elif before_marking == MARKING_DID_NOT_TRACK:
            events.append(history_event("marking", "Cleared did not track"))

    before_title = _clean_text(before.get("title"))
    next_title = _clean_text(incoming.get("title"))
    if before_title != next_title:
        if next_title and not before_title:
            events.append(history_event("title", "Title added", detail=next_title))
        elif next_title:
            events.append(history_event("title", "Title updated", detail=next_title))
        else:
            events.append(history_event("title", "Title cleared"))

    before_assets = before.get("assets") if isinstance(before.get("assets"), dict) else {}
    next_assets = incoming.get("assets") if isinstance(incoming.get("assets"), dict) else {}
    for key, label in ASSET_LABELS.items():
        prev_value = _clean_text(before_assets.get(key))
        next_value = _clean_text(next_assets.get(key))
        if prev_value == next_value:
            continue
        if key == "script_text":
            detail = "Script text saved" if next_value else ""
        else:
            detail = _short(next_value)
        if next_value and not prev_value:
            events.append(history_event("asset", f"{label} added", detail=detail))
        elif next_value:
            events.append(history_event("asset", f"{label} updated", detail=detail))
        else:
            events.append(history_event("asset", f"{label} removed"))

    before_plan = _clean_text(before.get("content_plan_item_id"))
    next_plan = _clean_text(incoming.get("content_plan_item_id"))
    if before_plan != next_plan and next_plan:
        events.append(history_event("script", "Script attached from content plan"))

    before_dests = _filled_dests(before)
    next_dests = _filled_dests(incoming)
    for key, dest in next_dests.items():
        url = _clean_text(dest.get("url"))
        label = _dest_label(dest)
        if key not in before_dests:
            events.append(history_event("destination", f"{label} link added", detail=_short(url)))
        elif _clean_text(before_dests[key].get("url")) != url:
            events.append(history_event("destination", f"{label} link updated", detail=_short(url)))
    for key, dest in before_dests.items():
        if key not in next_dests:
            events.append(history_event("destination", f"{_dest_label(dest)} link removed"))

    for key, added_label in (
        ("feedback_notes", "Feedback note added"),
        ("doctor_notes", "Doctor note added"),
    ):
        added = _note_ids(incoming, key) - _note_ids(before, key)
        for _ in added:
            events.append(history_event("note", added_label))

    before_files = _file_ids(before, "doctor_files")
    next_files = _file_ids(incoming, "doctor_files")
    for key, row in next_files.items():
        if key not in before_files:
            events.append(history_event("file", "Doctor file added", detail=_clean_text(row.get("name"))))

    before_posts = {str(item) for item in (before.get("generated_post_ids") or []) if item}
    next_posts = {str(item) for item in (incoming.get("generated_post_ids") or []) if item}
    if len(next_posts) > len(before_posts):
        events.append(history_event("post", "Generated post added"))

    before_reason = _clean_text(before.get("delay_reason"))
    next_reason = _clean_text(incoming.get("delay_reason"))
    if before_reason != next_reason and next_reason:
        events.append(history_event("delay", "Delay reason added", detail=_short(next_reason, 120)))

    before_proofs = _file_ids(before, "delay_proofs")
    next_proofs = _file_ids(incoming, "delay_proofs")
    added_proofs = [row for key, row in next_proofs.items() if key not in before_proofs]
    if added_proofs:
        names = ", ".join(_clean_text(row.get("name")) or "Proof" for row in added_proofs)
        events.append(history_event("delay", "Delay proof uploaded", detail=names))

    return events


def apply_card_history(previous: dict | None, incoming: dict, *, by: str = "") -> dict:
    if not isinstance(incoming, dict):
        return incoming
    events = diff_card_history(previous, incoming)
    base = previous.get("history") if isinstance(previous, dict) else []
    incoming["history"] = merge_history(base, events, by=by)
    return incoming
