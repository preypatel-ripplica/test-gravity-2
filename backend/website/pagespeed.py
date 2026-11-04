"""PageSpeed Insights helper for website monthly reports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException, status

from backend.main.config import PAGESPEED_API_KEY

PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def _ms_to_s(value: Any) -> float | None:
    try:
        return round(float(value) / 1000.0, 1)
    except (TypeError, ValueError):
        return None


def _score_100(category: dict[str, Any] | None) -> int | None:
    if not category:
        return None
    try:
        return int(round(float(category.get("score") or 0) * 100))
    except (TypeError, ValueError):
        return None


def fetch_pagespeed(site_url: str, *, strategy: str = "mobile") -> dict[str, Any]:
    """Run PSI for homepage. Returns grounded lab metrics; omits missing categories."""
    url = (site_url or "").strip()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Site URL is required for PageSpeed.",
        )
    if "://" not in url:
        url = f"https://{url}"
    strat = strategy if strategy in {"mobile", "desktop"} else "mobile"

    params: dict[str, Any] = {
        "url": url,
        "strategy": strat,
        "category": ["performance", "accessibility", "best-practices", "seo"],
    }
    if PAGESPEED_API_KEY:
        params["key"] = PAGESPEED_API_KEY

    with httpx.Client(timeout=90) as client:
        response = client.get(PSI_URL, params=params)

    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PageSpeed Insights failed: {response.text[:400]}",
        )

    data = response.json()
    lighthouse = data.get("lighthouseResult") or {}
    categories = lighthouse.get("categories") or {}
    audits = lighthouse.get("audits") or {}
    raw_fetch = lighthouse.get("fetchTime") or datetime.now(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(str(raw_fetch).replace("Z", "+00:00"))
        fetch_time = parsed.strftime("%d %b %Y, %I:%M %p UTC")
    except Exception:
        fetch_time = str(raw_fetch)

    def audit_display(audit_id: str) -> Any:
        audit = audits.get(audit_id) or {}
        return audit.get("displayValue") or audit.get("numericValue")

    fcp = _ms_to_s((audits.get("first-contentful-paint") or {}).get("numericValue"))
    lcp = _ms_to_s((audits.get("largest-contentful-paint") or {}).get("numericValue"))
    tbt = (audits.get("total-blocking-time") or {}).get("numericValue")
    cls = (audits.get("cumulative-layout-shift") or {}).get("numericValue")
    si = _ms_to_s((audits.get("speed-index") or {}).get("numericValue"))

    try:
        tbt_ms = int(round(float(tbt))) if tbt is not None else None
    except (TypeError, ValueError):
        tbt_ms = None
    try:
        cls_val = round(float(cls), 3) if cls is not None else None
    except (TypeError, ValueError):
        cls_val = None

    scores = {
        "performance": _score_100(categories.get("performance")),
        "accessibility": _score_100(categories.get("accessibility")),
        "best_practices": _score_100(categories.get("best-practices")),
        "seo": _score_100(categories.get("seo")),
    }

    # Agentic Browsing is not a standard PSI category yet — omit rather than invent.
    agentic = None

    return {
        "url": url,
        "strategy": strat,
        "fetched_at": fetch_time,
        "lighthouse_version": lighthouse.get("lighthouseVersion"),
        "scores": scores,
        "agentic_browsing": agentic,
        "lab": {
            "fcp_s": fcp,
            "lcp_s": lcp,
            "tbt_ms": tbt_ms,
            "cls": cls_val,
            "si_s": si,
            "fcp_display": audit_display("first-contentful-paint"),
            "lcp_display": audit_display("largest-contentful-paint"),
            "tbt_display": audit_display("total-blocking-time"),
            "cls_display": audit_display("cumulative-layout-shift"),
            "si_display": audit_display("speed-index"),
        },
    }
