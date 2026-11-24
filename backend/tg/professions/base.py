"""Profession pipeline contract.

Doctor implements every step with today's functions. A later profession
overrides methods, swaps prompts_dir, or flips capability flags.
"""

from __future__ import annotations

from pathlib import Path


class Profession:
    key = ""
    prompts_dir: Path | None = None

    uses_google_trends = True
    uses_recommendations_tab = True
    uses_video_mapping = True
    uses_festivals = True
    uses_monthly_report = True

    keyword_layout = "priority_trends"
    title_pick = "weighted_mapped"
    profile_label = "Doctor profile"
    audience_noun = "doctor"

    def ui_profile(self) -> dict:
        """How existing screens should look. Not a second route tree."""
        return {
            "keyword_layout": self.keyword_layout,
            "title_pick": self.title_pick,
            "profile_label": self.profile_label,
            "audience_noun": self.audience_noun or self.key or "doctor",
        }

    def capabilities(self) -> dict:
        return {
            "uses_google_trends": bool(self.uses_google_trends),
            "uses_recommendations_tab": bool(self.uses_recommendations_tab),
            "uses_video_mapping": bool(self.uses_video_mapping),
            "uses_festivals": bool(self.uses_festivals),
            "uses_monthly_report": bool(self.uses_monthly_report),
            "ui": self.ui_profile(),
        }

    def prompt(self, name: str) -> str:
        from backend.tg.services.openai_content_plan import _load_prompt

        return _load_prompt(name, prompts_dir=self.prompts_dir)

    def topic_instructions(self) -> dict[str, str]:
        raise NotImplementedError

    def content_format_catalog(self):
        raise NotImplementedError

    def script_template_catalog(self):
        raise NotImplementedError

    def seed_keywords(self, *args, **kwargs):
        raise NotImplementedError

    async def analyze_trends(self, *args, **kwargs):
        raise NotImplementedError

    def score_keywords(self, *args, **kwargs):
        raise NotImplementedError

    def map_videos(self, *args, **kwargs):
        raise NotImplementedError

    def generate_content_plan(self, *args, **kwargs):
        raise NotImplementedError

    def generate_scripts(self, *args, **kwargs):
        raise NotImplementedError

    def refine_script(self, *args, **kwargs):
        raise NotImplementedError

    def generate_youtube_metadata(self, *args, **kwargs):
        raise NotImplementedError

    def refine_youtube_metadata(self, *args, **kwargs):
        raise NotImplementedError

    def generate_thumbnail_prompt(self, *args, **kwargs):
        raise NotImplementedError

    def refine_thumbnail_prompt(self, *args, **kwargs):
        raise NotImplementedError

    def reference_thumbnail_prompt(self, *args, **kwargs):
        raise NotImplementedError

    def generate_social_caption(self, *args, **kwargs):
        raise NotImplementedError

    async def build_static_brief(self, *args, **kwargs):
        raise NotImplementedError

    def static_image_prompt(self, *args, **kwargs):
        raise NotImplementedError

    def pick_static_keywords(self, *args, **kwargs):
        raise NotImplementedError

    def generate_monthly_report(self, *args, **kwargs):
        raise NotImplementedError

    def refine_monthly_report(self, *args, **kwargs):
        raise NotImplementedError

    def polish_monthly_report(self, *args, **kwargs):
        raise NotImplementedError

    def _run(self, fn, *args, **kwargs):
        from backend.tg.professions.prompt_context import use_prompts

        with use_prompts(self.prompts_dir):
            return fn(*args, **kwargs)

    def stages(self, card_type: str) -> list[dict]:
        """Default checkpoint list. Doctor overrides this with today's stages."""
        noun = self.audience_noun or "client"
        if card_type in ("long_video", "short"):
            return [
                {"id": "planned", "label": "Planned"},
                {"id": "script_generated", "label": "Script generated"},
                {"id": "video_edited", "label": "Video edited"},
                {"id": "yt_metadata_generated", "label": "Metadata generated"},
                {"id": "posted", "label": "Posted"},
                {"id": "link_shared_with_client", "label": f"Link shared with {noun}"},
            ]
        if card_type == "static_post":
            rows = [
                {"id": "planned", "label": "Planned"},
                {"id": "posted", "label": "Posted"},
            ]
        elif card_type == "paid_ads":
            rows = [
                {"id": "planned", "label": "Planned"},
                {"id": "creatives_checked", "label": "Creatives checked"},
                {"id": "balance_checked", "label": "Balance checked"},
                {"id": "next_2_weeks_planned", "label": "Next 2 weeks planned"},
                {"id": "results_discussed", "label": "Results discussed"},
            ]
        else:
            rows = [
                {"id": "planned", "label": "Planned"},
                {"id": "published", "label": "Published"},
            ]
        rows.append({"id": "link_shared_with_client", "label": f"Link shared with {noun}"})
        return rows
