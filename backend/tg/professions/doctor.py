"""Doctor profession: one hop into the functions that already run in production."""

from __future__ import annotations

from pathlib import Path

from backend.tg.professions.base import Profession

DOCTOR_PROMPTS = Path(__file__).resolve().parent.parent / "prompts" / "doctor"

# Same ids and labels the tracker already shows for a doctor client.
DOCTOR_STAGES = {
    "long_video": [
        {"id": "planned", "label": "Planned"},
        {"id": "script_generated", "label": "Script generated"},
        {"id": "audio_generated", "label": "Audio received"},
        {"id": "video_edited", "label": "Video edited"},
        {"id": "shared_with_doctor", "label": "Shared with doctor"},
        {"id": "yt_metadata_generated", "label": "Metadata generated"},
        {"id": "posted", "label": "Posted"},
        {"id": "link_shared_with_doctor", "label": "Link shared with doctor"},
    ],
    "short": [
        {"id": "planned", "label": "Planned"},
        {"id": "script_generated", "label": "Script generated"},
        {"id": "audio_generated", "label": "Audio received"},
        {"id": "video_edited", "label": "Video edited"},
        {"id": "shared_with_doctor", "label": "Shared with doctor"},
        {"id": "yt_metadata_generated", "label": "Metadata generated"},
        {"id": "posted", "label": "Posted"},
        {"id": "link_shared_with_doctor", "label": "Link shared with doctor"},
    ],
    "static_post": [
        {"id": "planned", "label": "Planned"},
        {"id": "posted", "label": "Posted"},
        {"id": "link_shared_with_doctor", "label": "Link shared with doctor"},
    ],
    "blog": [
        {"id": "planned", "label": "Planned"},
        {"id": "published", "label": "Published"},
        {"id": "link_shared_with_doctor", "label": "Link shared with doctor"},
    ],
    "paid_ads": [
        {"id": "planned", "label": "Planned"},
        {"id": "creatives_checked", "label": "Creatives checked"},
        {"id": "balance_checked", "label": "Balance checked"},
        {"id": "next_2_weeks_planned", "label": "Next 2 weeks planned"},
        {"id": "results_discussed", "label": "Results discussed"},
        {"id": "link_shared_with_doctor", "label": "Link shared with doctor"},
    ],
}


class DoctorProfession(Profession):
    key = "doctor"
    prompts_dir = DOCTOR_PROMPTS

    def topic_instructions(self) -> dict[str, str]:
        from backend.tg.services import openai_topics as topics

        return {
            "sitemap": topics.SYSTEM_SITEMAP,
            "specialty": topics.SYSTEM_SPECIALTY,
            "refine": topics.SYSTEM_REFINE,
        }

    def content_format_catalog(self):
        from backend.tg.services.content_formats import catalog_for_prompt

        return catalog_for_prompt()

    def script_template_catalog(self):
        from backend.tg.services.script_templates import catalog_for_script_prompt

        return catalog_for_script_prompt()

    def stages(self, card_type: str) -> list[dict]:
        rows = DOCTOR_STAGES.get(card_type) or DOCTOR_STAGES["blog"]
        return [dict(row) for row in rows]

    def seed_keywords(self, *args, **kwargs):
        mode = kwargs.pop("mode", "refresh")
        if mode == "suggest":
            from backend.tg.services.topics import generate_auto_topics

            return self._run(generate_auto_topics, **kwargs)
        from backend.tg.clients import refresh_client_topics

        return self._run(refresh_client_topics, *args, **kwargs)

    async def analyze_trends(self, *args, **kwargs):
        from backend.tg.clients import analyze_client_trends
        from backend.tg.professions.prompt_context import use_prompts
        from backend.tg.services.trends import analyze_topics_trends

        # Keep a direct reference so tests can confirm this is the DataForSEO step.
        self._trend_impl = analyze_topics_trends
        with use_prompts(self.prompts_dir):
            return await analyze_client_trends(*args, **kwargs)

    def score_keywords(self, *args, **kwargs):
        from backend.tg.clients import save_client_recommendations

        return self._run(save_client_recommendations, *args, **kwargs)

    def map_videos(self, *args, **kwargs):
        from backend.tg.clients import map_client_content_plan

        return self._run(map_client_content_plan, *args, **kwargs)

    def generate_content_plan(self, *args, **kwargs):
        from backend.tg.clients import run_client_content_plan

        return self._run(run_client_content_plan, *args, **kwargs)

    def generate_scripts(self, *args, **kwargs):
        from backend.tg.clients import run_client_content_scripts

        return self._run(run_client_content_scripts, *args, **kwargs)

    def refine_script(self, *args, **kwargs):
        from backend.tg.clients import run_client_content_script_refine

        return self._run(run_client_content_script_refine, *args, **kwargs)

    def generate_youtube_metadata(self, *args, **kwargs):
        from backend.tg.services.youtube_metadata import generate_youtube_metadata

        return self._run(generate_youtube_metadata, *args, **kwargs)

    def refine_youtube_metadata(self, *args, **kwargs):
        from backend.tg.services.youtube_metadata import refine_youtube_metadata

        return self._run(refine_youtube_metadata, *args, **kwargs)

    def generate_thumbnail_prompt(self, *args, **kwargs):
        from backend.tg.services.youtube_metadata import generate_youtube_thumbnail_prompt

        return self._run(generate_youtube_thumbnail_prompt, *args, **kwargs)

    def refine_thumbnail_prompt(self, *args, **kwargs):
        from backend.tg.services.youtube_metadata import refine_youtube_thumbnail_prompt

        return self._run(refine_youtube_thumbnail_prompt, *args, **kwargs)

    def reference_thumbnail_prompt(self, *args, **kwargs):
        from backend.tg.services.youtube_metadata import reference_thumbnail_prompt

        return self._run(reference_thumbnail_prompt, *args, **kwargs)

    def generate_social_caption(self, *args, **kwargs):
        from backend.tg.services.youtube_metadata import generate_social_caption

        return self._run(generate_social_caption, *args, **kwargs)

    async def build_static_brief(self, *args, **kwargs):
        from backend.tg.professions.prompt_context import use_prompts
        from backend.tg.routes.social import _build_brief

        with use_prompts(self.prompts_dir):
            return await _build_brief(*args, **kwargs)

    def static_image_prompt(self, *args, **kwargs):
        from backend.tg.routes.social import _image_prompt

        return self._run(_image_prompt, *args, **kwargs)

    def pick_static_keywords(self, client, **kwargs):
        from backend.tg.routes.social import _recommended_keywords

        return _recommended_keywords(client)

    def generate_monthly_report(self, *args, **kwargs):
        from backend.tg.services.openai_monthly_report import generate_report_narrative

        return self._run(generate_report_narrative, *args, **kwargs)

    def refine_monthly_report(self, *args, **kwargs):
        from backend.tg.services.openai_monthly_report import refine_report_narrative

        return self._run(refine_report_narrative, *args, **kwargs)

    def polish_monthly_report(self, *args, **kwargs):
        from backend.tg.services.openai_monthly_report import polish_report_narrative

        return self._run(polish_report_narrative, *args, **kwargs)
