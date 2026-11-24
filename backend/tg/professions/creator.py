"""Creator pipeline: doctor flow without Google Trends or keyword mapping."""

from __future__ import annotations

from pathlib import Path

from backend.tg.professions.base import Profession
from backend.tg.professions.doctor import DoctorProfession

CREATOR_PROMPTS = Path(__file__).resolve().parent.parent / "prompts" / "creator"

_WEIGHTING = """
Weighting:
- high: core topics this creator's audience searches for and cares about
- medium: related topics and supporting ideas
- low: narrow or occasional topics
No clinic, doctor, patient, or clinical-fact wording.
"""

CREATOR_SYSTEM_SITEMAP = f"""You extract topic keywords from website sitemap URLs for a general creator.

The audience is the general public. Do not write about a clinic, a doctor, patients, or clinical facts.
Infer subjects from URL path slugs. Ignore blog, news, about, contact, and privacy pages.

{_WEIGHTING}
Each topic is 1-4 words. Every topic includes recommendation_score from 0 to 100:
how strongly you recommend that keyword for this creator right now.
Return JSON only.
"""

CREATOR_SYSTEM_SPECIALTY = f"""You build a keyword library for a general creator.

You receive website-derived topics plus the creator's niche. Expand them into a broad
keyword list for a general audience. No clinic, doctor, patient, or clinical-fact wording.

Rules:
- 1-4 words each. No slogans, CTAs, creator names, or full video titles.
- Prefer the niche. Use website topics as evidence of what they already cover.
{_WEIGHTING}
- Do not copy manual_topics_to_preserve into the output.
- Every topic includes recommendation_score from 0 to 100.
Return JSON only.
"""

CREATOR_SYSTEM_REFINE = f"""You revise an existing keyword list for a general creator using ONLY the user's instruction.

Inputs: current auto topics, niche, and user_prompt.
Apply the user_prompt to add, remove, reweight, or rename topics.
Stay on a general audience. No clinic, doctor, patient, or clinical-fact wording.
{_WEIGHTING}
Do not include manual_topics_to_preserve in the output.
Every topic includes recommendation_score from 0 to 100.
Return the full updated auto list as JSON.
"""


class CreatorProfession(DoctorProfession):
    key = "creator"
    prompts_dir = CREATOR_PROMPTS
    uses_google_trends = False
    uses_video_mapping = False
    uses_recommendations_tab = True
    keyword_layout = "ai_ranked"
    title_pick = "score_rank"
    profile_label = "Creator profile"
    audience_noun = "creator"

    def topic_instructions(self) -> dict[str, str]:
        return {
            "sitemap": CREATOR_SYSTEM_SITEMAP,
            "specialty": CREATOR_SYSTEM_SPECIALTY,
            "refine": CREATOR_SYSTEM_REFINE,
        }

    def stages(self, card_type: str) -> list[dict]:
        return Profession.stages(self, card_type)

    def seed_keywords(self, *args, **kwargs):
        mode = kwargs.pop("mode", "refresh")
        from backend.tg.services.creator_topics import (
            generate_creator_keywords,
            refresh_creator_keywords,
        )

        if mode == "suggest":
            return generate_creator_keywords(**kwargs)
        return refresh_creator_keywords(*args, **kwargs)

    async def analyze_trends(self, username: str, client_id: str, *, force: bool = False):
        from fastapi import HTTPException, status

        from backend.tg.database import fetch_client_doc, fetch_topics

        del force
        client = fetch_client_doc(client_id, username=username)
        if not client:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Client '{client_id}' not found.",
            )
        client["topics"] = fetch_topics(client_id)
        return {
            "client": client,
            "summary": {
                "scored": 0,
                "insufficient_data": 0,
                "skipped_cached": 0,
                "api_tasks": 0,
                "total_cost": 0,
                "error": None,
                "geo": "IN",
            },
        }

    def score_keywords(self, username: str, client_id: str):
        from fastapi import HTTPException, status

        from backend.tg.database import fetch_client_doc, fetch_topics, replace_topics
        from backend.tg.services.topics import apply_stored_recommendation_scores, normalize_topics

        client = fetch_client_doc(client_id, username=username)
        if not client:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Client '{client_id}' not found.",
            )
        topics = normalize_topics(fetch_topics(client_id))
        if not topics:
            raise ValueError("No topics to score. Add or refresh topics first.")
        updated = apply_stored_recommendation_scores(topics)
        client["topics"] = updated
        replace_topics(client_id, updated)
        primary = sum(1 for row in updated if float(row.get("recommendation_score") or 0) >= 50)
        return {
            "client": client,
            "primary_count": primary,
            "secondary_count": len(updated) - primary,
            "saved_at": updated[0].get("recommendation_saved_at") if updated else None,
            "threshold": 50.0,
        }

    def map_videos(self, username: str, client_id: str, **kwargs):
        del kwargs
        from backend.tg.clients import get_client_content_plan

        return get_client_content_plan(username, client_id)

    def generate_content_plan(self, *args, **kwargs):
        from backend.tg.clients import _require_client_bundle
        from backend.tg.database import replace_content_plan
        from backend.tg.services.content_plan import generate_titles_from_scores

        def _call(username, client_id, **kw):
            client = _require_client_bundle(username, client_id, with_videos=False)
            kw = dict(kw)
            kw["pick"] = "rank"
            suggestions = generate_titles_from_scores(client, **kw)
            replace_content_plan(client_id, client)
            return {"client": client, "suggestions": suggestions}

        return self._run(_call, *args, **kwargs)

    def pick_static_keywords(self, client, **kwargs):
        del kwargs
        rows = []
        for topic in (client or {}).get("topics") or []:
            if not isinstance(topic, dict):
                continue
            topic_id = str(topic.get("id") or topic.get("topic_id") or "").strip()
            text = str(topic.get("text") or topic.get("topic_text") or "").strip()
            if not topic_id or not text:
                continue
            raw = topic.get("recommendation_score")
            try:
                score = float(raw) if raw is not None else 0.0
            except (TypeError, ValueError):
                score = 0.0
            rows.append(
                {
                    "topic_id": topic_id,
                    "topic_text": text,
                    "recommendation_score": score,
                    "weight": topic.get("weight") or "medium",
                }
            )
        rows.sort(
            key=lambda row: (
                -float(row.get("recommendation_score") or 0),
                (row.get("topic_text") or "").lower(),
            )
        )
        return rows

    def sample_static_keywords(self, keywords, count):
        rows = list(keywords or [])
        if not rows:
            return []
        try:
            requested = int(count or 1)
        except (TypeError, ValueError):
            requested = 1
        n = max(1, min(requested, len(rows)))
        return rows[:n]
