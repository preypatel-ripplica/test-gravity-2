"""Profession lookup. Unknown and missing keys fall back to doctor.

MockProfession is not in PROFESSIONS. Production saves reject "mock".
"""

from __future__ import annotations

from backend.tg.professions.creator import CreatorProfession
from backend.tg.professions.doctor import DOCTOR_PROMPTS, DoctorProfession

PROFESSIONS = {
    "doctor": DoctorProfession,
    "creator": CreatorProfession,
}

SELECTABLE_PROFESSIONS = ("doctor", "creator")


def normalize_profession_key(value: str | None) -> str:
    return (value or "").strip().lower() or "doctor"


def get_profession(client: dict | None):
    key = normalize_profession_key((client or {}).get("profession"))
    cls = PROFESSIONS.get(key) or DoctorProfession
    return cls()


def client_profession_fields(project: dict | None) -> dict:
    """Fields the signed-in client list needs so the UI can follow the profession."""
    project = project or {}
    profession = get_profession(project)
    mix = project.get("posting_mix")
    return {
        "profession": profession.key,
        "niche": project.get("niche"),
        "niche_details": project.get("niche_details") or "",
        "example_topics": list(project.get("example_topics") or []),
        "capabilities": profession.capabilities(),
        "youtube_languages": list(project.get("youtube_languages") or []),
        "posting_mix": mix if isinstance(mix, dict) else None,
        "migrated_from_plug": project.get("migrated_from_plug") or None,
    }


def profession_for(client_id: str | None, username: str | None = None):
    from backend.tg.database import fetch_client_doc

    client = fetch_client_doc(client_id, username=username) if client_id else None
    return get_profession(client or {})


__all__ = [
    "DOCTOR_PROMPTS",
    "DoctorProfession",
    "CreatorProfession",
    "PROFESSIONS",
    "SELECTABLE_PROFESSIONS",
    "get_profession",
    "normalize_profession_key",
    "client_profession_fields",
    "profession_for",
]
