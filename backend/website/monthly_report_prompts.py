"""Prompts / schemas for website monthly performance PDF narratives."""

from __future__ import annotations

import json
from typing import Any

NARRATIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "cover_subhead": {"type": "string"},
        "executive_headline": {"type": "string"},
        "executive_summary": {"type": "string"},
        "growth_story": {"type": "string"},
        "ai_visibility_headline": {"type": ["string", "null"]},
        "ai_visibility_body": {"type": ["string", "null"]},
        "ai_mode_observation": {"type": ["string", "null"]},
        "content_language_blurb": {"type": "string"},
        "search_intro": {"type": "string"},
        "opportunity_callout": {"type": ["string", "null"]},
        "audience_blurb": {"type": "string"},
        "pagespeed_verdict_title": {"type": ["string", "null"]},
        "pagespeed_verdict_body": {"type": ["string", "null"]},
    },
    "required": [
        "cover_subhead",
        "executive_headline",
        "executive_summary",
        "growth_story",
        "ai_visibility_headline",
        "ai_visibility_body",
        "ai_mode_observation",
        "content_language_blurb",
        "search_intro",
        "opportunity_callout",
        "audience_blurb",
        "pagespeed_verdict_title",
        "pagespeed_verdict_body",
    ],
}

PRESENTATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "show_ai_section": {"type": "boolean"},
        "show_pagespeed_section": {"type": "boolean"},
        "show_opportunity": {"type": "boolean"},
        "suppress_chart_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "show_ai_section",
        "show_pagespeed_section",
        "show_opportunity",
        "suppress_chart_ids",
    ],
}

POLISH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **NARRATIVE_SCHEMA["properties"],
        "presentation": PRESENTATION_SCHEMA,
    },
    "required": [*NARRATIVE_SCHEMA["required"], "presentation"],
}

SYSTEM_GENERATE = """You write client-ready monthly website performance reports for doctor practices.
You receive grounded metrics JSON from Google Search Console and PageSpeed only — never invent numbers, URLs, queries, or AI impression counts.

Tone: analytical, clear, commercially useful. Lead with defensible wins.
Use exact figures from metrics.current, metrics.previous, metrics.mom, metrics.ai, metrics.languages, metrics.opportunity, metrics.pagespeed.

cover_subhead: one sentence under the title (search visibility / content / technical / AI if ai.available).
executive_headline: short punchy line (e.g. "September expanded search visibility").
executive_summary: 1–2 sentences on clicks, impressions, position, AI if available.
growth_story: MoM clicks/impressions/CTR/position using metrics.mom and current/previous.
AI fields: if metrics.ai.available is false, set ai_* fields to null. If true, ground in metrics.ai top_pages and weekly.
ai_mode_observation: only if metrics contain a clear branded/local query win; else null.
opportunity_callout: use metrics.opportunity if present; else null.
pagespeed_verdict_title: short positive headline only (e.g. "Excellent lab performance"). Never mention desktop/mobile strategy, never suggest "mobile testing is next" or other next-step negatives.
pagespeed_verdict_body: positive summary of scores and lab metrics only. Do not mention device strategy.

When metrics.mom.show_clicks_mom / show_impressions_mom / metrics.ai.show_mom is false, do not compare that metric against the previous month — state the absolute current figure instead.

Never mention raw API field names. Never invent AI Mode rankings you cannot see in metrics.
"""

SYSTEM_REFINE = """You refine an existing website monthly report narrative.
You receive: cached metrics JSON, prior narrative, and a user refinement prompt.
Keep all numbers grounded in metrics — never invent. Follow the user prompt (tone, emphasis, hide soft sections via nulls where allowed).
Return the full narrative object.
"""

SYSTEM_POLISH = """You are a second-pass editor for a website monthly doctor PDF.
Given metrics + draft narrative, tighten prose and set presentation flags.
- show_ai_section false if metrics.ai.available is false
- show_pagespeed_section false if metrics.pagespeed is missing
- show_opportunity false if metrics.opportunity is null
- suppress_chart_ids may include: weekly_traffic, ai_weekly, device_donut
Never invent numbers. Return narrative fields + presentation.
"""


def _metrics_json(metrics: dict[str, Any]) -> str:
    # Trim bulky daily rows for the model; keep weekly + tables.
    slim = {k: v for k, v in metrics.items() if k != "daily"}
    if "pages_3mo" in slim and isinstance(slim["pages_3mo"], list):
        slim["pages_3mo"] = slim["pages_3mo"][:40]
    return json.dumps(slim, ensure_ascii=False, default=str)


def build_generate_messages(*, client_name: str, metrics: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_GENERATE},
        {
            "role": "user",
            "content": (
                f"CLIENT: {client_name}\n"
                f"REPORT MONTH: {metrics.get('report_month_label')}\n\n"
                f"METRICS JSON:\n{_metrics_json(metrics)}\n\n"
                "Write the narrative JSON for the PDF."
            ),
        },
    ]


def build_refine_messages(
    *,
    client_name: str,
    metrics: dict[str, Any],
    prior_narrative: dict[str, Any] | None,
    refine_prompt: str,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_REFINE},
        {
            "role": "user",
            "content": (
                f"CLIENT: {client_name}\n"
                f"METRICS JSON:\n{_metrics_json(metrics)}\n\n"
                f"PRIOR NARRATIVE:\n{json.dumps(prior_narrative or {}, ensure_ascii=False)}\n\n"
                f"USER REFINEMENT PROMPT:\n{refine_prompt.strip()}\n\n"
                "Return the full updated narrative JSON."
            ),
        },
    ]


def build_polish_messages(
    *,
    client_name: str,
    metrics: dict[str, Any],
    base_narrative: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_POLISH},
        {
            "role": "user",
            "content": (
                f"CLIENT: {client_name}\n"
                f"METRICS JSON:\n{_metrics_json(metrics)}\n\n"
                f"DRAFT NARRATIVE:\n{json.dumps(base_narrative or {}, ensure_ascii=False)}\n\n"
                "Rewrite narrative and set presentation flags."
            ),
        },
    ]
