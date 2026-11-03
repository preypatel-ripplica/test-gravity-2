"""Weekly tracker + custom tracker APIs (separate collections)."""

from __future__ import annotations

import uuid
from calendar import monthrange
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.main.access_guards import require_domain_access, require_internal
from backend.main.auth import current_user
from backend.main.db import (
    channels_col,
    custom_trackers_col,
    yt_metadata_col,
    projects_col,
    weekly_trackers_col,
)
from backend.main.main_crudl import find_project, project_list
from backend.main.models import Domain
from backend.trackers.models import custom_doc_id, weekly_doc_id
from backend.trackers.tracker_card_history import apply_card_history
from backend.trackers.tracker_settings import (
    MARKING_DID_NOT_TRACK,
    card_types_from_slots,
    current_week_tuple,
    has_delay_proof,
    is_did_not_track,
    iter_weeks_inclusive,
    normalize_deliverables,
    normalize_marking,
    slots_for_week,
    slots_from_card_types,
    tracker_start_tuple,
    week_is_before_current,
    week_is_before_start,
)

router = APIRouter(tags=["trackers"])
DOMAIN = Domain.VIDEOS

LANG_ORDER = ("hinglish", "arabic", "russian")
CARD_TYPES = ("long_video", "short", "static_post", "blog", "paid_ads")
DEFAULT_PLATFORMS = {
    "long_video": ["youtube", "facebook", "instagram"],
    "short": ["youtube", "facebook", "instagram"],
    "static_post": ["facebook", "instagram"],
    "blog": ["website"],
    "paid_ads": [],
}
VIDEO_DEFAULT_SLOTS = {
    "hinglish": ["youtube", "facebook", "instagram"],
    "arabic": ["youtube", "facebook", "instagram"],
    "russian": ["youtube", "facebook", "instagram"],
}
STAGES = {
    "long_video": [
        "planned",
        "script_generated",
        "yt_metadata_generated",
        "audio_generated",
        "video_edited",
        "shared_with_doctor",
        "posted",
        "link_shared_with_doctor",
    ],
    "short": [
        "planned",
        "script_generated",
        "yt_metadata_generated",
        "audio_generated",
        "video_edited",
        "shared_with_doctor",
        "posted",
        "link_shared_with_doctor",
    ],
    "static_post": ["planned", "posted", "link_shared_with_doctor"],
    "blog": ["planned", "published", "link_shared_with_doctor"],
    "paid_ads": ["planned", "posted", "link_shared_with_doctor"],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "id") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _pid(body: Any) -> str:
    return (getattr(body, "project_id", None) or getattr(body, "client_id", None) or "").strip()


def _require_project(auth: dict, project_id: str) -> dict:
    require_domain_access(auth["user_id"], project_id, DOMAIN)
    return find_project(project_id)


def _assigned_languages(project_id: str) -> list[str]:
    seen: set[str] = set()
    for ch in channels_col().find({"project_id": project_id}, {"language": 1}):
        lang = str(ch.get("language") or "").strip().lower()
        if lang in LANG_ORDER:
            seen.add(lang)
    found = [lang for lang in LANG_ORDER if lang in seen]
    return found or list(LANG_ORDER)


def _empty_assets() -> dict:
    return {
        "script_url": "",
        "script_text": "",
        "script_source": "",
        "audio_url": "",
        "video_url": "",
    }


def default_card(card_type: str, sort_order: int, *, is_default: bool = False) -> dict:
    return {
        "id": _new_id("card"),
        "type": card_type,
        "title": "",
        "started": False,
        "collapsed": True,
        "sort_order": sort_order,
        "stage": "planned",
        "is_default": is_default,
        "assets": _empty_assets(),
        "destinations": [],
        "structure": {
            "platforms": list(DEFAULT_PLATFORMS[card_type]),
            "extra_slots": [],
            "hidden_cells": [],
        },
        "generated_post_ids": [],
        "destination_post_ids": {},
        "feedback_notes": [],
        "doctor_notes": [],
        "doctor_files": [],
        "content_plan_item_id": None,
        "topic_id": None,
        "marking": "none",
        "delay_reason": "",
        "delay_proofs": [],
        "delay_recorded_at": "",
        "delay_recorded_by": "",
        "history": [],
        "editor_id": "",
        "editor_overridden": False,
        "edit_hours": 0,
        "planned_edit_date": "",
    }


def seed_default_cards(slots=None) -> list[dict]:
    types = card_types_from_slots(slots)
    return [default_card(card_type, index, is_default=True) for index, card_type in enumerate(types)]


def seed_destinations_for_card(card: dict, languages: list[str]) -> dict:
    if card.get("destinations"):
        return card
    if card.get("type") == "paid_ads":
        card["destinations"] = []
        return card
    langs = languages or list(LANG_ORDER)
    destinations = []
    if card["type"] in {"long_video", "short"}:
        for lang in langs:
            for platform in VIDEO_DEFAULT_SLOTS.get(lang, ["youtube", "facebook"]):
                destinations.append(
                    {
                        "id": _new_id("dest"),
                        "language": lang,
                        "platform": platform,
                        "url": "",
                    }
                )
    else:
        platforms = list(
            (card.get("structure") or {}).get("platforms")
            or DEFAULT_PLATFORMS.get(card["type"], [])
        )
        for platform in platforms:
            destinations.append(
                {"id": _new_id("dest"), "platform": platform, "url": ""}
            )
    card["destinations"] = destinations
    return card


def _validate_month(year: int, month: int) -> None:
    if month < 1 or month > 12:
        raise HTTPException(400, "Month must be 1-12")
    if year < 2000 or year > 2100:
        raise HTTPException(400, "Invalid year")


def _validate_week(year: int, month: int, week: int) -> None:
    _validate_month(year, month)
    if week < 1 or week > 4:
        raise HTTPException(400, "Week must be 1-4")


def _weeks_in_month(year: int, month: int) -> list[int]:
    last = monthrange(year, month)[1]
    return [week for week, start in enumerate((1, 8, 15, 22), start=1) if start <= last]


def _card_is_out(card: dict) -> bool:
    return any(str(dest.get("url") or "").strip() for dest in card.get("destinations") or [])


def _week_summary_from_cards(week: int, cards: list[dict] | None, slots=None) -> dict:
    if cards is None:
        total = len(card_types_from_slots(slots)) if slots is not None else 4
        return {"week": week, "out": 0, "total": total, "to_start": total}
    return {
        "week": week,
        "out": sum(1 for card in cards if _card_is_out(card)),
        "total": len(cards),
        "to_start": sum(1 for card in cards if not card.get("started")),
    }


def _stage_index(card_type: str, stage: str) -> int:
    order = STAGES.get(card_type) or ["planned"]
    try:
        return order.index(stage)
    except ValueError:
        return 0


def _at_least_stage(card: dict, stage: str) -> None:
    current = str(card.get("stage") or "planned")
    if _stage_index(card.get("type") or "", stage) > _stage_index(
        card.get("type") or "", current
    ):
        card["stage"] = stage


def _hydrate_cards(project_id: str, cards: list[dict]) -> list[dict]:
    packages = {
        str(p.get("topic_id")): p
        for p in yt_metadata_col().find({"project_id": project_id}, {"_id": 0})
        if p.get("topic_id")
    }
    out = []
    for card in cards:
        row = dict(card)
        row["destinations"] = [
            dict(d) for d in (card.get("destinations") or []) if isinstance(d, dict)
        ]
        topic_id = str(row.get("topic_id") or "").strip()
        pkg = packages.get(topic_id) if topic_id else None
        if pkg:
            locales = pkg.get("locales") or pkg.get("yt_locales") or {}
            row["yt_locales"] = locales
            if any(
                isinstance(loc, dict) and str(loc.get("yt_title") or "").strip()
                for loc in (locales or {}).values()
            ):
                _at_least_stage(row, "yt_metadata_generated")
            for platform, key in (
                ("youtube", "youtube_urls"),
                ("instagram", "instagram_urls"),
                ("facebook", "facebook_urls"),
            ):
                # productions store posted_urls; also accept legacy keys if present
                for entry in pkg.get(key) or []:
                    if isinstance(entry, dict) and entry.get("url"):
                        _ensure_dest_url(row, platform, entry["url"], entry.get("language"))
            for entry in pkg.get("posted_urls") or []:
                if isinstance(entry, dict) and entry.get("url"):
                    _ensure_dest_url(
                        row,
                        str(entry.get("platform") or "youtube"),
                        entry["url"],
                        entry.get("language"),
                    )
            if pkg.get("posted_urls") or pkg.get("youtube_urls"):
                _at_least_stage(row, "posted")
        out.append(row)
    return out


def _ensure_dest_url(card: dict, platform: str, url: str, language: str | None = None) -> None:
    url = str(url or "").strip()
    if not url:
        return
    dests = list(card.get("destinations") or [])
    if any(d.get("platform") == platform and str(d.get("url") or "").strip() == url for d in dests):
        card["destinations"] = dests
        return
    lang = str(language or "").strip().lower() or None
    for dest in dests:
        if dest.get("platform") != platform:
            continue
        dest_lang = str(dest.get("language") or "").strip().lower()
        if lang and dest_lang != lang:
            continue
        if str(dest.get("url") or "").strip():
            continue
        dest["url"] = url
        card["destinations"] = dests
        return
    extra = {"id": _new_id("dest"), "platform": platform, "url": url}
    if lang:
        extra["language"] = lang
    dests.append(extra)
    card["destinations"] = dests



def _card_is_complete(card: dict) -> bool:
    stages = STAGES.get(card.get("type") or "") or []
    if not stages:
        return False
    return (card.get("stage") or "") == stages[-1]


def _mark_incomplete_untracked(doc: dict, *, by: str = "") -> bool:
    changed = False
    actor = by or str(doc.get("updated_by") or "system")
    for card in doc.get("cards") or []:
        if not isinstance(card, dict):
            continue
        if is_did_not_track(card.get("marking")):
            continue
        if _card_is_complete(card):
            continue
        previous = dict(card)
        card["marking"] = MARKING_DID_NOT_TRACK
        apply_card_history(previous, card, by=actor)
        changed = True
    return changed


def _card_has_work(card: dict) -> bool:
    stage = str(card.get("stage") or "planned")
    stages = STAGES.get(card.get("type") or "") or []
    if stages and stage != stages[0]:
        return True
    if str(card.get("title") or "").strip():
        return True
    assets = card.get("assets") or {}
    for key in ("script_url", "script_text", "audio_url", "video_url"):
        if str(assets.get(key) or "").strip():
            return True
    if card.get("content_plan_item_id") or card.get("topic_id"):
        return True
    if card.get("generated_post_ids") or card.get("feedback_notes") or card.get("doctor_notes") or card.get("doctor_files"):
        return True
    for dest in card.get("destinations") or []:
        if isinstance(dest, dict) and str(dest.get("url") or "").strip():
            return True
    return False


def _order_cards_by_type(cards: list[dict]) -> list[dict]:
    ranked = sorted(
        [card for card in cards if isinstance(card, dict)],
        key=lambda card: (
            CARD_TYPES.index(card.get("type")) if card.get("type") in CARD_TYPES else len(CARD_TYPES),
            int(card.get("sort_order") or 0),
        ),
    )
    for index, card in enumerate(ranked):
        card["sort_order"] = index
    return ranked


def _sync_week_cards(doc: dict, slots) -> bool:
    from collections import Counter, defaultdict

    wanted = Counter(card_types_from_slots(slots))
    cards = [card for card in (doc.get("cards") or []) if isinstance(card, dict)]
    grouped: dict[str, list[dict]] = defaultdict(list)
    unknown: list[dict] = []
    for card in cards:
        card_type = str(card.get("type") or "")
        if card_type in CARD_TYPES:
            grouped[card_type].append(card)
        else:
            unknown.append(card)
    next_cards = list(unknown)
    changed = False
    for card_type in CARD_TYPES:
        group = grouped.get(card_type) or []
        need = int(wanted.get(card_type, 0))
        with_work = [card for card in group if _card_has_work(card)]
        empty = [card for card in group if not _card_has_work(card)]
        kept = list(with_work)
        remaining = max(0, need - len(kept))
        kept.extend(empty[:remaining])
        if len(kept) != len(group):
            changed = True
        next_cards.extend(kept)
    have = Counter(str(card.get("type") or "") for card in next_cards)
    next_order = max((int(card.get("sort_order") or 0) for card in next_cards), default=-1) + 1
    for card_type, need in wanted.items():
        for _ in range(max(0, int(need) - int(have.get(card_type, 0)))):
            next_cards.append(default_card(card_type, next_order, is_default=True))
            next_order += 1
            changed = True
    ordered = _order_cards_by_type(next_cards)
    before_ids = [card.get("id") for card in cards]
    after_ids = [card.get("id") for card in ordered]
    if changed or before_ids != after_ids:
        doc["cards"] = ordered
        return True
    return False


def _stamp_week_slots(doc: dict, slots) -> bool:
    normalized = normalize_deliverables(slots)
    existing = doc.get("deliverable_slots")
    if existing is not None and card_types_from_slots(existing) == card_types_from_slots(normalized):
        return False
    doc["deliverable_slots"] = normalized
    return True


def _ensure_card_started(card: dict, languages: list[str]) -> bool:
    changed = False
    if not card.get("started"):
        card["started"] = True
        changed = True
    if not card.get("destinations") and card.get("type") != "paid_ads":
        seed_destinations_for_card(card, languages)
        changed = True
    return changed


def _project_client_view(project: dict) -> dict:
    """Shape project like TG client for tracker_settings helpers."""
    return project or {}


def _ensure_week(project_id: str, year: int, month: int, week: int, actor: str) -> dict:
    project = projects_col().find_one({"id": project_id}, {"_id": 0}) or {}
    client = _project_client_view(project)
    slots = slots_for_week(client, year, month, week)
    languages = _assigned_languages(project_id)
    doc_id = weekly_doc_id(project_id, year, month, week)
    if week_is_before_start(client, year, month, week):
        return {
            "id": doc_id,
            "project_id": project_id,
            "client_id": project_id,
            "year": year,
            "month": month,
            "week": week,
            "cards": [],
            "deliverable_slots": slots,
            "languages": languages,
            "updated_at": _now_iso(),
            "updated_by": actor,
        }
    existing = weekly_trackers_col().find_one({"id": doc_id}, {"_id": 0})
    before_current = week_is_before_current(year, month, week)
    late = before_current
    from backend.trackers.editors import VIDEO_TYPES, default_editor_id, edit_hours_for

    if existing:
        if existing.get("deliverable_slots") is None:
            _stamp_week_slots(existing, slots)
            weekly_trackers_col().update_one(
                {"id": doc_id},
                {"$set": {"deliverable_slots": existing.get("deliverable_slots")}},
            )
        return existing
    cards = seed_default_cards(slots)

    for card in cards:
        _ensure_card_started(card, languages)
        if str(card.get("type") or "") in VIDEO_TYPES:
            card["editor_id"] = default_editor_id(project, late=late)
            card["edit_hours"] = edit_hours_for(project, card.get("type"))
    doc = {
        "id": doc_id,
        "project_id": project_id,
        "client_id": project_id,
        "year": year,
        "month": month,
        "week": week,
        "cards": cards,
        "deliverable_slots": slots,
        "languages": languages,
        "updated_at": _now_iso(),
        "updated_by": actor,
    }
    if before_current:
        _mark_incomplete_untracked(doc, by=actor)
    weekly_trackers_col().replace_one({"id": doc_id}, doc, upsert=True)
    return doc


def sync_weeks_from_deliverable_change(project_id: str, actor: str, from_week: tuple[int, int, int]) -> None:
    project = projects_col().find_one({"id": project_id}, {"_id": 0}) or {}
    client = _project_client_view(project)
    languages = _assigned_languages(project_id)
    from_year, from_month, from_week_n = from_week
    for doc in weekly_trackers_col().find({"project_id": project_id}, {"_id": 0}):
        try:
            year = int(doc.get("year"))
            month = int(doc.get("month"))
            week = int(doc.get("week"))
        except (TypeError, ValueError):
            continue
        if (year, month) < (from_year, from_month):
            continue
        if year == from_year and month == from_month and week < from_week_n:
            continue
        if week_is_before_start(client, year, month, week):
            continue
        slots = slots_for_week(client, year, month, week)
        changed = _sync_week_cards(doc, slots)
        changed = _stamp_week_slots(doc, slots) or changed
        for card in doc.get("cards") or []:
            if isinstance(card, dict) and _ensure_card_started(card, languages):
                changed = True
        if changed:
            doc["updated_at"] = _now_iso()
            doc["updated_by"] = actor
            weekly_trackers_col().replace_one({"id": doc["id"]}, doc, upsert=True)


def _weekly_response(doc: dict, languages: list[str]) -> dict:
    cards = _hydrate_cards(doc["project_id"], list(doc.get("cards") or []))
    slots = doc.get("deliverable_slots")
    return {
        "tracker": {
            "id": doc.get("id"),
            "client_id": doc.get("project_id") or doc.get("client_id"),
            "year": doc.get("year"),
            "month": doc.get("month"),
            "week": doc.get("week"),
            "cards": cards,
            "deliverable_slots": normalize_deliverables(slots) if slots is not None else None,
            "languages": languages,
            "updated_at": doc.get("updated_at"),
            "updated_by": doc.get("updated_by"),
        },
        "languages": languages,
    }


# --- request bodies ---


class WeeklyGetBody(BaseModel):
    client_id: Optional[str] = None
    project_id: Optional[str] = None
    year: int
    month: int
    week: int


class WeeklyMonthBody(BaseModel):
    client_id: Optional[str] = None
    project_id: Optional[str] = None
    year: int
    month: int


class WeeklyPocBody(BaseModel):
    year: int
    month: int


class WeeklySaveBody(BaseModel):
    client_id: Optional[str] = None
    project_id: Optional[str] = None
    year: int
    month: int
    week: int
    cards: list[dict[str, Any]] = Field(default_factory=list)


class WeeklyClientBody(BaseModel):
    client_id: Optional[str] = None
    project_id: Optional[str] = None


class CustomGetBody(BaseModel):
    client_id: Optional[str] = None
    project_id: Optional[str] = None


class CustomSaveBody(BaseModel):
    client_id: Optional[str] = None
    project_id: Optional[str] = None
    tasks: list[dict[str, Any]] = Field(default_factory=list)


# --- weekly endpoints ---


@router.post("/weekly.tracker.get")
def weekly_tracker_get(body: WeeklyGetBody, auth: dict = Depends(current_user)):
    project_id = _pid(body)
    _validate_week(body.year, body.month, body.week)
    _require_project(auth, project_id)
    languages = _assigned_languages(project_id)
    doc = _ensure_week(
        project_id, body.year, body.month, body.week, auth.get("email") or auth["user_id"]
    )
    return _weekly_response(doc, languages)


@router.post("/weekly.tracker.month.summary")
def weekly_tracker_month_summary(
    body: WeeklyMonthBody, auth: dict = Depends(current_user)
):
    project_id = _pid(body)
    _validate_month(body.year, body.month)
    _require_project(auth, project_id)
    docs = {
        int(d.get("week") or 0): d
        for d in weekly_trackers_col().find(
            {
                "project_id": project_id,
                "year": body.year,
                "month": body.month,
            },
            {"_id": 0},
        )
    }
    project = projects_col().find_one({"id": project_id}, {"_id": 0}) or {}
    weeks = []
    for week in _weeks_in_month(body.year, body.month):
        if week_is_before_start(project, body.year, body.month, week):
            weeks.append({"week": week, "out": 0, "total": 0, "to_start": 0})
            continue
        week_doc = docs.get(week)
        week_slots = (week_doc or {}).get("deliverable_slots")
        weeks.append(
            _week_summary_from_cards(
                week,
                (week_doc.get("cards") if week_doc else None),
                week_slots if week_slots is not None else slots_for_week(project, body.year, body.month, week),
            )
        )
    return {"weeks": weeks}


@router.post("/weekly.tracker.poc.summary")
def weekly_tracker_poc_summary(body: WeeklyPocBody, auth: dict = Depends(current_user)):
    _validate_month(body.year, body.month)
    week_ids = _weeks_in_month(body.year, body.month)
    projects = project_list(auth)["projects"]
    clients_out = []
    totals = {week: {"week": week, "out": 0, "total": 0, "to_start": 0} for week in week_ids}
    for project in projects:
        project_id = project["id"]
        docs = {
            int(d.get("week") or 0): d
            for d in weekly_trackers_col().find(
                {"project_id": project_id, "year": body.year, "month": body.month},
                {"_id": 0},
            )
        }
        weeks = []
        for week in week_ids:
            if week_is_before_start(project, body.year, body.month, week):
                weeks.append({"week": week, "out": 0, "total": 0, "to_start": 0})
                continue
            week_doc = docs.get(week)
            week_slots = (week_doc or {}).get("deliverable_slots")
            weeks.append(
                _week_summary_from_cards(
                    week,
                    (week_doc.get("cards") if week_doc else None),
                    week_slots if week_slots is not None else slots_for_week(project, body.year, body.month, week),
                )
            )
        for row in weeks:
            totals[row["week"]]["out"] += row["out"]
            totals[row["week"]]["total"] += row["total"]
            totals[row["week"]]["to_start"] += row["to_start"]
        clients_out.append(
            {
                "client_id": project_id,
                "name": project.get("name") or "Untitled",
                "weeks": weeks,
            }
        )
    clients_out.sort(key=lambda row: (row["name"] or "").lower())
    return {"weeks": [totals[week] for week in week_ids], "clients": clients_out}


@router.post("/weekly.tracker.mark-missed")
def weekly_tracker_mark_missed(body: WeeklyClientBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    project_id = _pid(body)
    project = _require_project(auth, project_id)
    actor = auth.get("email") or auth["user_id"]
    current = current_week_tuple()
    start = tracker_start_tuple(project)
    existing_docs = list(weekly_trackers_col().find({"project_id": project_id}, {"_id": 0}))
    week_keys = set()
    if start and start < current:
        week_keys.update(key for key in iter_weeks_inclusive(start, current) if key < current)
    for doc in existing_docs:
        try:
            key = (int(doc.get("year")), int(doc.get("month")), int(doc.get("week")))
        except (TypeError, ValueError):
            continue
        if key < current:
            week_keys.add(key)
    marked_cards = 0
    marked_weeks = 0
    for year, month, week in sorted(week_keys):
        if not week_is_before_current(year, month, week):
            continue
        doc = _ensure_week(project_id, year, month, week, actor)
        if not _mark_incomplete_untracked(doc, by=actor):
            continue
        doc["updated_at"] = _now_iso()
        doc["updated_by"] = actor
        weekly_trackers_col().replace_one({"id": doc["id"]}, doc, upsert=True)
        marked_weeks += 1
        marked_cards += sum(
            1
            for card in (doc.get("cards") or [])
            if isinstance(card, dict) and is_did_not_track(card.get("marking"))
        )
    return {"marked_cards": marked_cards, "marked_weeks": marked_weeks}


@router.post("/weekly.tracker.save")
def weekly_tracker_save(body: WeeklySaveBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    project_id = _pid(body)
    _validate_week(body.year, body.month, body.week)
    _require_project(auth, project_id)
    languages = _assigned_languages(project_id)
    actor = auth.get("email") or auth["user_id"]
    existing = _ensure_week(project_id, body.year, body.month, body.week, actor)
    cards = []
    existing_by_id = {
        str(row.get("id")): row
        for row in (existing.get("cards") or [])
        if isinstance(row, dict) and row.get("id")
    }
    for index, incoming in enumerate(body.cards or []):
        card = dict(incoming)
        card["sort_order"] = index if card.get("sort_order") is None else card["sort_order"]
        card["marking"] = normalize_marking(card.get("marking"))
        if card.get("started") and not card.get("destinations"):
            seed_destinations_for_card(card, languages)
        card.pop("generated_posts", None)
        cards.append(card)
    if week_is_before_current(body.year, body.month, body.week):
        for card in cards:
            if not _card_is_complete(card):
                continue
            previous = existing_by_id.get(str(card.get("id")))
            if previous and _card_is_complete(previous):
                continue
            if not has_delay_proof(card):
                raise HTTPException(
                    400,
                    "This task is from an earlier week. Add a reason for the delay and "
                    "upload proof (voice, chat screenshot, or call history) before marking it completed.",
                )
            if not str(card.get("delay_recorded_at") or "").strip():
                card["delay_recorded_at"] = _now_iso()
            card["delay_recorded_by"] = actor
    for card in cards:
        apply_card_history(existing_by_id.get(str(card.get("id"))), card, by=actor)
    cards.sort(key=lambda row: int(row.get("sort_order") or 0))
    doc = {
        **existing,
        "cards": cards,
        "deliverable_slots": slots_from_card_types(card.get("type") for card in cards),
        "languages": languages,
        "updated_at": _now_iso(),
        "updated_by": actor,
    }
    weekly_trackers_col().replace_one({"id": existing["id"]}, {**doc}, upsert=True)
    return _weekly_response(doc, languages)


@router.post("/weekly.tracker.script-links.get")
def weekly_tracker_script_links_get(
    body: WeeklyClientBody, auth: dict = Depends(current_user)
):
    project_id = _pid(body)
    _require_project(auth, project_id)
    placements = []
    for doc in weekly_trackers_col().find({"project_id": project_id}, {"_id": 0}):
        for card in doc.get("cards") or []:
            item_id = card.get("content_plan_item_id")
            if not item_id:
                continue
            placements.append(
                {
                    "item_id": item_id,
                    "year": doc.get("year"),
                    "month": doc.get("month"),
                    "week": doc.get("week"),
                    "card_id": card.get("id"),
                    "card_title": card.get("title"),
                    "card_type": card.get("type"),
                }
            )
    return {"placements": placements}


@router.post("/weekly.tracker.attach-script")
def weekly_tracker_attach_script(body: dict, auth: dict = Depends(current_user)):
    require_internal(auth)
    project_id = (body or {}).get("project_id") or (body or {}).get("client_id")
    year = int((body or {}).get("year"))
    month = int((body or {}).get("month"))
    week = int((body or {}).get("week"))
    item_id = (body or {}).get("item_id")
    card_id = (body or {}).get("card_id")
    _validate_week(year, month, week)
    _require_project(auth, project_id)
    languages = _assigned_languages(project_id)
    doc = _ensure_week(project_id, year, month, week, auth.get("email") or auth["user_id"])
    cards = list(doc.get("cards") or [])

    # pull script from plan_items / content_plan first (needed for card type + already check)
    from backend.main.db import plan_items_col, projects_col

    script = ""
    topic_id = None
    title = ""
    item_format = ""
    pi = plan_items_col().find_one({"id": item_id, "project_id": project_id}, {"_id": 0})
    if pi:
        script = pi.get("script") or ""
        topic_id = pi.get("topic_id")
        title = pi.get("title") or ""
        item_format = str(pi.get("format") or "")
    else:
        project = projects_col().find_one({"id": project_id}, {"_id": 0, "content_plan": 1})
        for item in ((project or {}).get("content_plan") or {}).get("items") or []:
            if item.get("id") == item_id:
                script = item.get("script") or ""
                topic_id = item.get("topic_id")
                title = (
                    item.get("title_en")
                    or item.get("working_title")
                    or item.get("topic_text")
                    or ""
                )
                item_format = str(item.get("format") or "")
                break

    fmt = item_format.strip().lower()
    preferred_type = "short" if fmt.startswith("short") else "long_video"

    target = None
    created = False
    if card_id:
        target = next((c for c in cards if c.get("id") == card_id), None)
        if not target:
            raise HTTPException(404, "Card not found")
    else:
        # Scripts page: never clobber an occupied card.
        # 1) empty slot of the right type  2) else create a new card
        target = next(
            (
                c
                for c in cards
                if c.get("type") == preferred_type and not _card_has_work(c)
            ),
            None,
        )
        if not target:
            sort_order = max((int(c.get("sort_order") or 0) for c in cards), default=-1) + 1
            target = default_card(preferred_type, sort_order, is_default=False)
            cards.append(target)
            created = True

    already = str(target.get("content_plan_item_id") or "") == str(item_id or "")
    assets = dict(target.get("assets") or _empty_assets())
    assets["script_text"] = script
    assets["script_source"] = "content_plan"
    target["assets"] = assets
    target["content_plan_item_id"] = item_id
    if topic_id:
        target["topic_id"] = topic_id
    if title and not target.get("title"):
        target["title"] = title
    target["started"] = True
    if not target.get("destinations"):
        seed_destinations_for_card(target, languages)
    _at_least_stage(target, "script_generated")
    doc["cards"] = _order_cards_by_type(cards)
    doc["updated_at"] = _now_iso()
    doc["updated_by"] = auth.get("email") or auth["user_id"]
    weekly_trackers_col().replace_one({"id": doc["id"]}, doc, upsert=True)
    response = _weekly_response(doc, languages)
    response["status"] = "already" if already else ("created" if created else "attached")
    response["card_id"] = target.get("id")
    return response


@router.post("/weekly.tracker.note.add")
def weekly_tracker_note_add(body: dict, auth: dict = Depends(current_user)):
    require_internal(auth)
    project_id = (body or {}).get("project_id") or (body or {}).get("client_id")
    year = int((body or {}).get("year"))
    month = int((body or {}).get("month"))
    week = int((body or {}).get("week"))
    card_id = (body or {}).get("card_id")
    note_type = (body or {}).get("note_type") or "feedback"
    text = str((body or {}).get("text") or "")
    _validate_week(year, month, week)
    _require_project(auth, project_id)
    languages = _assigned_languages(project_id)
    doc = _ensure_week(project_id, year, month, week, auth.get("email") or auth["user_id"])
    cards = list(doc.get("cards") or [])
    card = next((c for c in cards if c.get("id") == card_id), None)
    if not card:
        raise HTTPException(404, "Card not found")
    key = "doctor_notes" if note_type == "doctor" else "feedback_notes"
    notes = list(card.get(key) or [])
    notes.append(
        {
            "id": _new_id("note"),
            "text": text,
            "language": (body or {}).get("language") or "all",
            "attachments": (body or {}).get("attachments") or [],
            "created_by": auth.get("email") or auth["user_id"],
            "created_at": _now_iso(),
        }
    )
    card[key] = notes
    doc["cards"] = cards
    doc["updated_at"] = _now_iso()
    weekly_trackers_col().replace_one({"id": doc["id"]}, doc, upsert=True)
    return _weekly_response(doc, languages)


# --- custom tracker ---


def _default_due_date() -> str:
    from datetime import date, timedelta
    return (date.today() + timedelta(days=2)).isoformat()


def _clean_task(row: dict) -> dict:
    raw = str(row.get("due_date") or "").strip()
    due = raw[:10] if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-" else ""
    if not due and not bool(row.get("done")):
        due = _default_due_date()
    return {
        "id": row.get("id") or _new_id("tsk"),
        "title": str(row.get("title") or "").strip(),
        "done": bool(row.get("done")),
        "due_date": due,
        "comment": str(row.get("comment") or "").strip(),
    }


def _ensure_custom(project_id: str, actor: str) -> dict:
    doc_id = custom_doc_id(project_id)
    existing = custom_trackers_col().find_one({"id": doc_id}, {"_id": 0})
    if existing:
        tasks = [_clean_task(t) for t in (existing.get("tasks") or []) if isinstance(t, dict)]
        existing["tasks"] = tasks
        return existing
    doc = {
        "id": doc_id,
        "project_id": project_id,
        "client_id": project_id,
        "tasks": [],
        "updated_at": _now_iso(),
        "updated_by": actor,
    }
    custom_trackers_col().insert_one(doc)
    doc.pop("_id", None)
    return doc


def _custom_response(doc: dict) -> dict:
    return {
        "tracker": {
            "id": doc.get("id"),
            "client_id": doc.get("project_id") or doc.get("client_id"),
            "tasks": doc.get("tasks") or [],
            "updated_at": doc.get("updated_at"),
            "updated_by": doc.get("updated_by"),
        }
    }


@router.post("/custom.tracker.get")
def custom_tracker_get(body: CustomGetBody, auth: dict = Depends(current_user)):
    project_id = _pid(body)
    _require_project(auth, project_id)
    doc = _ensure_custom(project_id, auth.get("email") or auth["user_id"])
    return _custom_response(doc)


@router.post("/custom.tracker.save")
def custom_tracker_save(body: CustomSaveBody, auth: dict = Depends(current_user)):
    require_internal(auth)
    project_id = _pid(body)
    _require_project(auth, project_id)
    existing = _ensure_custom(project_id, auth.get("email") or auth["user_id"])
    tasks = [_clean_task(t) for t in (body.tasks or []) if isinstance(t, dict)]
    # unique ids
    seen = set()
    unique = []
    for t in tasks:
        if t["id"] in seen:
            t = {**t, "id": _new_id("tsk")}
        seen.add(t["id"])
        unique.append(t)
    doc = {
        **existing,
        "tasks": unique,
        "updated_at": _now_iso(),
        "updated_by": auth.get("email") or auth["user_id"],
    }
    custom_trackers_col().replace_one({"id": existing["id"]}, doc, upsert=True)
    return _custom_response(doc)
