"""Test-only profession. Not registered for production clients."""

from __future__ import annotations

from backend.tg.professions.base import Profession


class MockProfession(Profession):
    key = "mock"
    uses_google_trends = False
    uses_recommendations_tab = False
    uses_video_mapping = False
    uses_festivals = False
    uses_monthly_report = False

    def topic_instructions(self):
        return {"sitemap": "mock", "specialty": "mock", "refine": "mock"}

    def content_format_catalog(self):
        return []

    def script_template_catalog(self):
        return {}

    def seed_keywords(self, *args, **kwargs):
        return {"mock": True}

    async def analyze_trends(self, *args, **kwargs):
        return {"mock": True}

    def score_keywords(self, *args, **kwargs):
        return {"mock": True}

    def map_videos(self, *args, **kwargs):
        return {"mock": True}

    def generate_content_plan(self, *args, **kwargs):
        return {"mock": True}

    def generate_scripts(self, *args, **kwargs):
        return {"mock": True}

    def refine_script(self, *args, **kwargs):
        return {"mock": True}

    def generate_youtube_metadata(self, *args, **kwargs):
        return {"mock": True}

    def refine_youtube_metadata(self, *args, **kwargs):
        return {"mock": True}

    def generate_thumbnail_prompt(self, *args, **kwargs):
        return "mock"

    def refine_thumbnail_prompt(self, *args, **kwargs):
        return "mock"

    def reference_thumbnail_prompt(self, *args, **kwargs):
        return "mock"

    def generate_social_caption(self, *args, **kwargs):
        return "mock"

    async def build_static_brief(self, *args, **kwargs):
        return {"mock": True}

    def static_image_prompt(self, *args, **kwargs):
        return "mock"

    def pick_static_keywords(self, *args, **kwargs):
        return []

    def generate_monthly_report(self, *args, **kwargs):
        return {"mock": True}

    def refine_monthly_report(self, *args, **kwargs):
        return {"mock": True}

    def polish_monthly_report(self, *args, **kwargs):
        return {"mock": True}
