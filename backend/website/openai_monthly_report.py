"""OpenAI helpers for website monthly report narrative generate / refine / polish."""

from __future__ import annotations

from typing import Any

from backend.tg.services.openai_content_plan import _call_openai
from backend.website.monthly_report_prompts import (
    NARRATIVE_SCHEMA,
    POLISH_SCHEMA,
    build_generate_messages,
    build_polish_messages,
    build_refine_messages,
)

_NARRATIVE_KEYS = (
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
)


def generate_report_narrative(*, client_name: str, metrics: dict[str, Any]) -> dict[str, Any]:
    messages = build_generate_messages(client_name=client_name, metrics=metrics)
    return _call_openai(
        messages=messages,
        schema=NARRATIVE_SCHEMA,
        schema_name="website_monthly_report_narrative",
        effort="medium",
        stage="website-monthly-report-generate",
        timeout=180.0,
    )


def refine_report_narrative(
    *,
    client_name: str,
    metrics: dict[str, Any],
    prior_narrative: dict[str, Any] | None,
    refine_prompt: str,
) -> dict[str, Any]:
    messages = build_refine_messages(
        client_name=client_name,
        metrics=metrics,
        prior_narrative=prior_narrative,
        refine_prompt=refine_prompt,
    )
    return _call_openai(
        messages=messages,
        schema=NARRATIVE_SCHEMA,
        schema_name="website_monthly_report_narrative_refine",
        effort="medium",
        stage="website-monthly-report-refine",
        timeout=180.0,
    )


def polish_report_narrative(
    *,
    client_name: str,
    metrics: dict[str, Any],
    base_narrative: dict[str, Any],
) -> dict[str, Any]:
    messages = build_polish_messages(
        client_name=client_name,
        metrics=metrics,
        base_narrative=base_narrative,
    )
    return _call_openai(
        messages=messages,
        schema=POLISH_SCHEMA,
        schema_name="website_monthly_report_polish",
        effort="medium",
        stage="website-monthly-report-polish",
        timeout=180.0,
    )


def split_polish_result(polished: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    narrative = {k: polished.get(k) for k in _NARRATIVE_KEYS}
    presentation = polished.get("presentation") if isinstance(polished.get("presentation"), dict) else {}
    return narrative, presentation


def apply_presentation_guards(
    metrics: dict[str, Any],
    presentation: dict[str, Any] | None,
) -> dict[str, Any]:
    pres = dict(presentation or {})
    ai = metrics.get("ai") or {}
    if not ai.get("available"):
        pres["show_ai_section"] = False
    if not metrics.get("pagespeed"):
        pres["show_pagespeed_section"] = False
    if not metrics.get("opportunity"):
        pres["show_opportunity"] = False
    pres.setdefault("show_ai_section", bool(ai.get("available")))
    pres.setdefault("show_pagespeed_section", bool(metrics.get("pagespeed")))
    pres.setdefault("show_opportunity", bool(metrics.get("opportunity")))
    pres.setdefault("suppress_chart_ids", [])
    return pres


def fallback_narrative(metrics: dict[str, Any]) -> dict[str, Any]:
    """Deterministic copy if OpenAI is unavailable — still grounded in metrics."""
    cur = metrics.get("current") or {}
    prev = metrics.get("previous") or {}
    mom = metrics.get("mom") or {}
    ai = metrics.get("ai") or {}
    label = metrics.get("report_month_label") or "This month"
    prev_label = metrics.get("previous_month_label") or "prior month"
    clicks_pct = mom.get("clicks_pct")
    impr_pct = mom.get("impressions_pct")
    ai_available = bool(ai.get("available"))

    def pct(v):
        return f"{v:+.1f}%" if v is not None else "n/a"

    cover = (
        f"Search visibility, content performance and technical health for {label}"
        + (", including measured visibility in Google's AI search features." if ai_available else ".")
    )
    growth_bits = []
    if mom.get("show_impressions_mom") and impr_pct is not None:
        growth_bits.append(f"impressions {pct(impr_pct)} vs {prev_label}")
    else:
        growth_bits.append(f"{cur.get('impressions', 0):,} impressions in {label}")
    if mom.get("show_clicks_mom") and clicks_pct is not None:
        growth_bits.append(f"clicks {pct(clicks_pct)} vs {prev_label}")
    else:
        growth_bits.append(f"{cur.get('clicks', 0):,} clicks in {label}")
    growth = (
        f"{growth_bits[0].capitalize()} and {growth_bits[1]}. "
        f"CTR moved from {prev.get('ctr', 0):.2f}% to {cur.get('ctr', 0):.2f}%, "
        f"while average position went from {prev.get('position', 0):.2f} to {cur.get('position', 0):.2f}."
    )
    opp = metrics.get("opportunity")
    opportunity = None
    if opp:
        opportunity = (
            f"Opportunity: '{opp.get('key')}' produces {opp.get('clicks')} clicks from "
            f"{opp.get('impressions'):,} impressions at position {opp.get('position')}."
        )

    ai_body = None
    ai_headline = None
    if ai_available:
        ai_headline = "AI visibility highlights"
        tops = ai.get("top_pages") or []
        bits = [f"{p.get('slug')}: {p.get('impressions'):,} AI imps" for p in tops[:4]]
        if ai.get("show_mom") and ai.get("mom_pct") is not None:
            ai_cmp = f" ({pct(ai.get('mom_pct'))} vs {prev_label})"
        else:
            ai_cmp = ""
        ai_body = (
            f"Google AI impressions reached {ai.get('current_impressions'):,} in {label}{ai_cmp}. "
            + ("Top pages — " + "; ".join(bits) + "." if bits else "")
        )

    psi = metrics.get("pagespeed") or {}
    scores = (psi.get("scores") or {}) if psi else {}
    lab = (psi.get("lab") or {}) if psi else {}
    ps_title = ps_body = None
    if psi:
        perf = scores.get("performance")
        ps_title = "Excellent lab performance" if (perf or 0) >= 90 else "Solid technical health"
        ps_body = (
            f"Lighthouse scored performance {scores.get('performance')}, "
            f"accessibility {scores.get('accessibility')}, best practices {scores.get('best_practices')}, "
            f"and SEO {scores.get('seo')}"
            + (
                f", with LCP {lab.get('lcp_s')}s and CLS {lab.get('cls')}."
                if lab.get("lcp_s") is not None
                else "."
            )
        )

    langs = metrics.get("languages") or []
    lang_bits = ", ".join(f"{l.get('language')} ({l.get('clicks')} clicks)" for l in langs[:4])
    content_blurb = (
        f"Tracked content pages spanned languages: {lang_bits}."
        if lang_bits
        else "Content language breakdown uses page-path prefixes from Search Console."
    )

    return {
        "cover_subhead": cover,
        "executive_headline": f"{label} search performance",
        "executive_summary": (
            f"Clicks reached {cur.get('clicks', 0):,} and impressions {cur.get('impressions', 0):,} "
            f"in {label}"
            + (
                f", with clicks {pct(clicks_pct)} vs {prev_label}."
                if mom.get("show_clicks_mom") and clicks_pct is not None
                else "."
            )
            + f" Average position {cur.get('position', 0):.2f}."
        ),
        "growth_story": growth,
        "ai_visibility_headline": ai_headline,
        "ai_visibility_body": ai_body,
        "ai_mode_observation": None,
        "content_language_blurb": content_blurb,
        "search_intro": "Branded and discovery queries from Google Search Console for the reporting month.",
        "opportunity_callout": opportunity,
        "audience_blurb": (
            f"India contributes {metrics.get('india_share_pct', 0)}% of clicks in the three-month window."
        ),
        "pagespeed_verdict_title": ps_title,
        "pagespeed_verdict_body": ps_body,
    }
