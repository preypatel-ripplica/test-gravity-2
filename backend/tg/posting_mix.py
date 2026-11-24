"""Client posting-mix template. Missing mix means the legacy tracker grid."""

from __future__ import annotations

import re
from typing import Any

STANDARD_PLATFORMS = ("youtube", "instagram", "facebook")

LANGUAGE_LABELS = {
    "hinglish": "Hindi",
    "english": "English",
    "bengali": "Bengali",
    "telugu": "Telugu",
    "marathi": "Marathi",
    "tamil": "Tamil",
    "gujarati": "Gujarati",
    "kannada": "Kannada",
    "malayalam": "Malayalam",
    "punjabi": "Punjabi",
    "odia": "Odia",
    "urdu": "Urdu",
    "arabic": "Arabic",
    "russian": "Russian",
}


def language_key(raw: str | None, *, label: str | None = None) -> str:
    text = (raw or label or "").strip().lower()
    if text in {"hindi", "hinglish"}:
        return "hinglish"
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:40]


def language_label(key: str, explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    return LANGUAGE_LABELS.get(key, key.replace("-", " ").title())


def normalize_youtube_languages(raw) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw or []:
        if isinstance(item, str):
            key = language_key(item)
            label = language_label(key)
        elif isinstance(item, dict):
            key = language_key(item.get("key"), label=item.get("label"))
            label = language_label(key, item.get("label"))
        else:
            continue
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"key": key, "label": label})
    return out


def mix_is_saved(raw) -> bool:
    return isinstance(raw, dict) and bool(raw.get("saved"))


def normalize_posting_mix(raw) -> dict[str, Any] | None:
    if not mix_is_saved(raw):
        return None
    include_in = raw.get("include") if isinstance(raw.get("include"), dict) else {}
    extras = []
    seen = set(STANDARD_PLATFORMS)
    for item in raw.get("extra_platforms") or []:
        if isinstance(item, str):
            key = language_key(item)
            label = language_label(key, item)
        elif isinstance(item, dict):
            key = language_key(item.get("key"), label=item.get("label"))
            label = language_label(key, item.get("label"))
        else:
            continue
        if not key or key in seen or key in STANDARD_PLATFORMS:
            continue
        seen.add(key)
        extras.append({"key": key, "label": label})
    return {
        "saved": True,
        "include": {
            "youtube": bool(include_in.get("youtube")),
            "instagram": bool(include_in.get("instagram")),
            "facebook": bool(include_in.get("facebook")),
        },
        "extra_platforms": extras,
    }


def tracker_destination_context(project: dict | None) -> dict[str, Any]:
    """Shape the weekly tracker uses. No saved mix keeps the legacy grid."""
    project = project or {}
    languages = normalize_youtube_languages(project.get("youtube_languages"))
    mix = normalize_posting_mix(project.get("posting_mix"))
    labels = {row["key"]: row["label"] for row in languages}
    if not mix:
        return {
            "destinations_mode": "legacy",
            "languages": [],
            "language_labels": labels,
            "posting_mix": None,
        }
    return {
        "destinations_mode": "posting_mix",
        "languages": [row["key"] for row in languages] if mix["include"]["youtube"] else [],
        "language_labels": labels,
        "posting_mix": mix,
    }


def mix_platforms(mix: dict | None, card_type: str) -> list[str]:
    if not mix:
        return []
    include = mix.get("include") or {}
    extras = [row["key"] for row in mix.get("extra_platforms") or []]
    video = card_type in {"long_video", "short"}
    platforms: list[str] = []
    if video and include.get("youtube"):
        platforms.append("youtube")
    if include.get("facebook") and card_type != "blog":
        platforms.append("facebook")
    if include.get("instagram") and card_type != "blog":
        platforms.append("instagram")
    if card_type != "paid_ads":
        platforms.extend(extras)
    if card_type == "blog":
        return ["website"]
    if card_type == "paid_ads":
        return []
    return platforms


def seed_rows_for_mix(card_type: str, languages: list[str], mix: dict) -> list[dict]:
    """Empty destination slots for a new card. Does not touch cards that already have links."""
    platforms = mix_platforms(mix, card_type)
    if card_type in {"long_video", "short"}:
        rows = []
        langs = languages or []
        for lang in langs:
            if "youtube" in platforms:
                rows.append({"language": lang, "platform": "youtube", "url": ""})
        for platform in platforms:
            if platform == "youtube":
                continue
            rows.append({"platform": platform, "url": ""})
        return rows
    return [{"platform": platform, "url": ""} for platform in platforms]


def collapse_mix_destinations(
    destinations: list[dict],
    card_type: str,
    languages: list[str],
    mix: dict | None,
) -> list[dict]:
    """One YouTube cell per language; Instagram/Facebook/extras are one cell each.

    Leftover legacy rows (Hindi/Arabic/Russian × Instagram) collapse to a single slot.
    Extra language-less slots from Edit structure are kept.
    """
    if not mix_is_saved(mix):
        return list(destinations or [])
    platforms = mix_platforms(mix, card_type)
    dests = [dict(row) for row in (destinations or []) if isinstance(row, dict)]
    out: list[dict] = []
    if "youtube" in platforms:
        langs = list(languages or [])
        for lang in langs:
            match = next(
                (
                    row
                    for row in dests
                    if row.get("platform") == "youtube" and row.get("language") == lang
                ),
                None,
            )
            out.append(match or {"language": lang, "platform": "youtube", "url": ""})
    for platform in platforms:
        if platform == "youtube":
            continue
        rows = [row for row in dests if row.get("platform") == platform]
        shared = [row for row in rows if not row.get("language")]
        languaged = [row for row in rows if row.get("language")]
        if shared:
            out.extend(shared)
            seen_urls = {(row.get("url") or "").strip() for row in shared if (row.get("url") or "").strip()}
            for row in languaged:
                url = (row.get("url") or "").strip()
                if url and url not in seen_urls:
                    extra = dict(row)
                    extra.pop("language", None)
                    extra["url"] = url
                    out.append(extra)
                    seen_urls.add(url)
        elif languaged:
            pick = next((row for row in languaged if (row.get("url") or "").strip()), languaged[0])
            extra = dict(pick)
            extra.pop("language", None)
            out.append(extra)
        else:
            out.append({"platform": platform, "url": ""})
    return out
