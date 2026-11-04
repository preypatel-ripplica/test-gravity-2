"""Assemble a grounded GSC metrics bundle for website monthly PDF reports."""

from __future__ import annotations

import calendar
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, status

from backend.website import seo_trackers

DEFAULT_LANGUAGE_PREFIXES: dict[str, str] = {
    "hi": "Hindi",
    "ar": "Arabic",
    "ru": "Russian",
}

AI_APPEARANCE_RE = re.compile(
    r"(ai[_\s-]?overview|ai[_\s-]?mode|ai[_\s-]?search|generative|sge)",
    re.IGNORECASE,
)


def _month_start(yyyy_mm: str) -> date:
    year, month = map(int, yyyy_mm.split("-"))
    return date(year, month, 1)


def _month_end(yyyy_mm: str) -> date:
    year, month = map(int, yyyy_mm.split("-"))
    last = calendar.monthrange(year, month)[1]
    return date(year, month, last)


def previous_calendar_month(yyyy_mm: str) -> str:
    start = _month_start(yyyy_mm)
    prev = start - timedelta(days=1)
    return f"{prev.year:04d}-{prev.month:02d}"


def month_label(yyyy_mm: str) -> str:
    names = [
        "",
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    try:
        year, month = yyyy_mm.split("-")
        return f"{names[int(month)]} {year}"
    except (ValueError, IndexError):
        return yyyy_mm


def _cap_end(end: date) -> date:
    lag = datetime.now(timezone.utc).date() - timedelta(days=3)
    return min(end, lag)


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None if current == 0 else 100.0
    return round(((current - previous) / previous) * 100, 1)


def _metric_row(payload: dict[str, Any]) -> dict[str, Any]:
    row = (payload.get("rows") or [{}])[0] if payload.get("rows") else {}
    clicks = float(row.get("clicks") or 0)
    impressions = float(row.get("impressions") or 0)
    ctr = round(float(row.get("ctr") or 0) * 100, 2)
    position = round(float(row.get("position") or 0), 2)
    return {
        "clicks": int(round(clicks)),
        "impressions": int(round(impressions)),
        "ctr": ctr,
        "position": position,
    }


def _dim_rows(payload: dict[str, Any], *, key_index: int = 0) -> list[dict[str, Any]]:
    rows = []
    for row in payload.get("rows") or []:
        keys = row.get("keys") or []
        key = (keys[key_index] if len(keys) > key_index else "") or ""
        rows.append(
            {
                "key": str(key).strip(),
                "clicks": int(round(float(row.get("clicks") or 0))),
                "impressions": int(round(float(row.get("impressions") or 0))),
                "ctr": round(float(row.get("ctr") or 0) * 100, 2),
                "position": round(float(row.get("position") or 0), 2),
            }
        )
    return rows


def _page_path(url: str) -> str:
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        # urllib.parse.ParseResult uses `.path` (not `.pathname`)
        path = parsed.path or "/"
        return path if path.startswith("/") else f"/{path}"
    except Exception:
        return url


_COUNTRY_NAMES: dict[str, str] = {
    "ind": "India",
    "usa": "United States",
    "gbr": "United Kingdom",
    "can": "Canada",
    "are": "United Arab Emirates",
    "sau": "Saudi Arabia",
    "egy": "Egypt",
    "syr": "Syria",
    "yem": "Yemen",
    "mar": "Morocco",
    "rus": "Russia",
    "deu": "Germany",
    "aus": "Australia",
    "sgp": "Singapore",
    "pak": "Pakistan",
    "bgd": "Bangladesh",
    "npl": "Nepal",
    "lka": "Sri Lanka",
    "qat": "Qatar",
    "kwt": "Kuwait",
    "omn": "Oman",
    "bhr": "Bahrain",
    "irq": "Iraq",
    "jor": "Jordan",
    "lbn": "Lebanon",
    "fra": "France",
    "ita": "Italy",
    "esp": "Spain",
    "nld": "Netherlands",
    "zzz": "Unknown Region",
}


def _country_label(code: str) -> str:
    key = (code or "").strip().lower()
    if not key:
        return "Unknown"
    return _COUNTRY_NAMES.get(key, key.upper())


def _slug_from_path(path: str) -> str:
    cleaned = path.rstrip("/") or "/"
    if cleaned == "/":
        return "/"
    parts = [p for p in cleaned.split("/") if p]
    # Drop language prefix segment for display slug when present
    if parts and parts[0] in DEFAULT_LANGUAGE_PREFIXES:
        parts = parts[1:]
    if not parts:
        return "/"
    return parts[-1]


# Romanized / Hinglish slug cues (avoid short tokens like ke/ki/ka — too many English FPs)
HINDI_SLUG_HINT_RE = re.compile(
    r"(?:^|[-_/])(?:"
    r"in-hindi|hindi|"
    r"seene|ganth|mein|safed|dhabba|kharcha|kitna|kaise|ilaj|karan|"
    r"fefad|pheph|oesophagus-kya|kya-hota|kya-hai|kab-tak|kitne|"
    r"fefadon|phephde|ganth-ke|seene-mein"
    r")(?:[-_/]|$)",
    re.IGNORECASE,
)
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def _looks_like_hindi_slug(path: str) -> bool:
    """True for Devanagari paths or romanized Hindi blog slugs (no /hi/ prefix required)."""
    cleaned = (path or "").strip().lower()
    if not cleaned:
        return False
    if DEVANAGARI_RE.search(cleaned):
        return True
    if re.search(r"(?:^|[-_/])in-hindi(?:[-_/]|$)|(?:^|[-_/])hindi(?:[-_/]|$)|-hindi$", cleaned):
        return True
    # Need 2+ strong Hinglish cues, or one very specific compound
    hits = HINDI_SLUG_HINT_RE.findall(cleaned)
    if len(hits) >= 2:
        return True
    strong = (
        "seene-mein",
        "ganth-ke",
        "safed-dhabba",
        "in-hindi",
        "chest-xray-mein",
        "meaning-of-esophagus-in-hindi",
    )
    return any(token in cleaned for token in strong)


def language_for_path(
    path: str,
    prefixes: dict[str, str],
    *,
    enabled_languages: list[str] | None = None,
    detect_hindi_slugs: bool = False,
) -> str:
    parts = [p for p in path.split("/") if p]
    lang = "English"
    if parts and parts[0].lower() in prefixes:
        lang = prefixes[parts[0].lower()]
    elif detect_hindi_slugs and _looks_like_hindi_slug(path):
        lang = "Hindi"
    if enabled_languages:
        allowed = {str(x).strip() for x in enabled_languages if str(x).strip()}
        if allowed and lang not in allowed:
            return "English"
    return lang


def _is_ai_appearance(value: str) -> bool:
    return bool(AI_APPEARANCE_RE.search(value or ""))


def _rollup_weeks(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group daily rows into ISO weeks ending Sunday (label = week start Monday)."""
    buckets: dict[str, dict[str, Any]] = {}
    for row in daily:
        try:
            d = date.fromisoformat(row["date"])
        except (KeyError, ValueError):
            continue
        week_start = d - timedelta(days=d.weekday())
        key = week_start.isoformat()
        bucket = buckets.setdefault(
            key,
            {"week_start": key, "label": week_start.strftime("%m-%d"), "clicks": 0, "impressions": 0},
        )
        bucket["clicks"] += int(row.get("clicks") or 0)
        bucket["impressions"] += int(row.get("impressions") or 0)
    return [buckets[k] for k in sorted(buckets.keys())]


def _resolve_property(project_id: str) -> tuple[str, str, dict[str, Any]]:
    config = seo_trackers.get_tracker_config(project_id)
    candidates = seo_trackers.gsc_property_candidates(config)
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set a GSC property (or site URL) in tracker settings first.",
        )
    token = seo_trackers.google_access_token(project_id)
    last_error = "Could not query Search Console"
    for property_url in candidates:
        try:
            seo_trackers._gsc_query(
                token,
                property_url,
                {
                    "startDate": (datetime.now(timezone.utc).date() - timedelta(days=10)).isoformat(),
                    "endDate": (datetime.now(timezone.utc).date() - timedelta(days=3)).isoformat(),
                    "rowLimit": 1,
                },
            )
            return token, property_url, config
        except HTTPException as exc:
            last_error = str(exc.detail)
            continue
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=last_error)


def _query(
    token: str,
    property_url: str,
    *,
    start: date,
    end: date,
    dimensions: list[str] | None = None,
    row_limit: int = 250,
    dimension_filter_groups: list[dict[str, Any]] | None = None,
    soft: bool = False,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "rowLimit": row_limit,
    }
    if dimensions:
        body["dimensions"] = dimensions
    if dimension_filter_groups:
        body["dimensionFilterGroups"] = dimension_filter_groups
    try:
        return seo_trackers._gsc_query(token, property_url, body)
    except HTTPException:
        if soft:
            return {"rows": []}
        raise


def _ai_impressions_from_appearance(payload: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    matched = []
    total = 0
    for row in _dim_rows(payload):
        if _is_ai_appearance(row["key"]):
            matched.append(row)
            total += int(row["impressions"] or 0)
    return total, matched


def fetch_gsc_monthly_bundle(project_id: str, report_month: str) -> dict[str, Any]:
    """Grounded GSC metrics for one reporting month (plus MoM and ~3mo windows)."""
    token, property_url, config = _resolve_property(project_id)
    prev_month = previous_calendar_month(report_month)

    cur_start = _month_start(report_month)
    cur_end = _cap_end(_month_end(report_month))
    if cur_end < cur_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Report month {report_month} has no Search Console data yet (data lags ~3 days).",
        )
    prev_start = _month_start(prev_month)
    prev_end = _cap_end(_month_end(prev_month))

    # Rolling ~3 months ending on report month end (sample uses Jun 29–Sep 30 style)
    three_end = cur_end
    three_start = _month_start(
        previous_calendar_month(previous_calendar_month(report_month))
    )

    prefixes_cfg = config.get("language_prefixes")
    if prefixes_cfg is None:
        language_prefixes = dict(DEFAULT_LANGUAGE_PREFIXES)
    elif isinstance(prefixes_cfg, dict) and not prefixes_cfg:
        # Explicit empty dict = prefix languages disabled (slug hints / English only)
        language_prefixes = {}
    else:
        language_prefixes = {
            str(k).strip().lower(): str(v).strip()
            for k, v in (prefixes_cfg or {}).items()
            if str(k).strip() and str(v).strip()
        }
    enabled_languages_raw = config.get("enabled_languages")
    enabled_languages: list[str] | None = None
    if isinstance(enabled_languages_raw, list) and enabled_languages_raw:
        enabled_languages = [str(x).strip() for x in enabled_languages_raw if str(x).strip()]
    detect_hindi_slugs = bool(config.get("detect_hindi_slugs"))

    jobs: dict[str, dict[str, Any]] = {
        "cur_totals": {"start": cur_start, "end": cur_end, "row_limit": 1},
        "prev_totals": {"start": prev_start, "end": prev_end, "row_limit": 1},
        "daily": {
            "start": three_start,
            "end": cur_end,
            "dimensions": ["date"],
            "row_limit": 5000,
        },
        "month_queries": {
            "start": cur_start,
            "end": cur_end,
            "dimensions": ["query"],
            "row_limit": 50,
        },
        "month_pages": {
            "start": cur_start,
            "end": cur_end,
            "dimensions": ["page"],
            "row_limit": 25,
        },
        "pages_3mo": {
            "start": three_start,
            "end": three_end,
            "dimensions": ["page"],
            "row_limit": 250,
        },
        "queries_3mo": {
            "start": three_start,
            "end": three_end,
            "dimensions": ["query"],
            "row_limit": 250,
        },
        "countries": {
            "start": three_start,
            "end": three_end,
            "dimensions": ["country"],
            "row_limit": 25,
        },
        "devices": {
            "start": three_start,
            "end": three_end,
            "dimensions": ["device"],
            "row_limit": 10,
        },
        "ai_cur": {
            "start": cur_start,
            "end": cur_end,
            "dimensions": ["searchAppearance"],
            "row_limit": 50,
            "soft": True,
        },
        "ai_prev": {
            "start": prev_start,
            "end": prev_end,
            "dimensions": ["searchAppearance"],
            "row_limit": 50,
            "soft": True,
        },
        "ai_daily": {
            "start": cur_start,
            "end": cur_end,
            "dimensions": ["date", "searchAppearance"],
            "row_limit": 2500,
            "soft": True,
        },
        "ai_pages": {
            "start": three_start,
            "end": three_end,
            "dimensions": ["page", "searchAppearance"],
            "row_limit": 1000,
            "soft": True,
        },
    }

    payloads: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(
                _query,
                token,
                property_url,
                start=spec["start"],
                end=spec["end"],
                dimensions=spec.get("dimensions"),
                row_limit=spec.get("row_limit", 250),
                soft=bool(spec.get("soft")),
            ): key
            for key, spec in jobs.items()
        }
        for fut in as_completed(futures):
            payloads[futures[fut]] = fut.result()

    cur_totals = _metric_row(payloads["cur_totals"])
    prev_totals = _metric_row(payloads["prev_totals"])

    daily = []
    for row in payloads["daily"].get("rows") or []:
        daily.append(
            {
                "date": (row.get("keys") or [""])[0],
                "clicks": int(round(float(row.get("clicks") or 0))),
                "impressions": int(round(float(row.get("impressions") or 0))),
            }
        )
    daily.sort(key=lambda item: item["date"])
    weekly = _rollup_weeks(daily)

    month_queries = _dim_rows(payloads["month_queries"])
    month_pages = _dim_rows(payloads["month_pages"])
    pages_3mo = _dim_rows(payloads["pages_3mo"])
    countries = [
        {**row, "key": _country_label(row["key"]), "code": row["key"]}
        for row in _dim_rows(payloads["countries"])
    ]
    devices = _dim_rows(payloads["devices"])

    # Language aggregation from 3mo pages
    language_map: dict[str, dict[str, Any]] = {}
    content_pages: list[dict[str, Any]] = []
    for row in pages_3mo:
        path = _page_path(row["key"])
        lang = language_for_path(
            path,
            language_prefixes,
            enabled_languages=enabled_languages,
            detect_hindi_slugs=detect_hindi_slugs,
        )
        bucket = language_map.setdefault(
            lang, {"language": lang, "clicks": 0, "impressions": 0, "pages": 0}
        )
        bucket["clicks"] += row["clicks"]
        bucket["impressions"] += row["impressions"]
        bucket["pages"] += 1
        content_pages.append(
            {
                **row,
                "path": path,
                "slug": _slug_from_path(path),
                "language": lang,
            }
        )
    languages = sorted(language_map.values(), key=lambda item: item["clicks"], reverse=True)
    for item in languages:
        clicks = item["clicks"]
        imps = item["impressions"] or 0
        item["ctr"] = round((clicks / imps) * 100, 2) if imps else 0.0

    top_by_language: dict[str, list[dict[str, Any]]] = {}
    lang_keys = {*(item["language"] for item in languages), "English"}
    if enabled_languages:
        lang_keys = {lang for lang in lang_keys if lang in set(enabled_languages)} | {"English"}
    for lang in sorted(lang_keys):
        # Collapse trailing-slash URL variants from GSC into one row
        merged_pages: dict[str, dict[str, Any]] = {}
        for page in content_pages:
            if page["language"] != lang:
                continue
            key = (page.get("path") or "").rstrip("/") or "/"
            bucket = merged_pages.get(key)
            if not bucket:
                merged_pages[key] = {**page, "path": key, "slug": _slug_from_path(key)}
                continue
            bucket["clicks"] += int(page.get("clicks") or 0)
            bucket["impressions"] += int(page.get("impressions") or 0)
            imps = bucket["impressions"] or 0
            bucket["ctr"] = round((bucket["clicks"] / imps) * 100, 2) if imps else 0.0
        ranked = sorted(merged_pages.values(), key=lambda item: item["clicks"], reverse=True)
        top_by_language[lang] = ranked[:8]

    # Position bands from 3mo pages
    page_top3, page_top5, page_top10 = [], [], []
    for row in sorted(content_pages, key=lambda item: item["position"]):
        pos = float(row["position"] or 0)
        entry = {
            "path": row["path"],
            "label": row["path"],
            "position": pos,
            "clicks": row["clicks"],
            "impressions": row["impressions"],
        }
        if pos <= 3:
            page_top3.append(entry)
        elif pos <= 5:
            page_top5.append(entry)
        elif pos <= 10:
            page_top10.append(entry)

    # Position bands from 3mo queries (useful when few pages rank top-3 but many queries do)
    queries_3mo = _dim_rows(payloads["queries_3mo"])
    query_top3, query_top5, query_top10 = _split_query_position_bands(queries_3mo)
    page_bands = {
        "dimension": "page",
        "label": "Pages",
        "top3_count": len(page_top3),
        "top5_count": len(page_top3) + len(page_top5),
        "top10_count": len(page_top3) + len(page_top5) + len(page_top10),
        "top3": page_top3[:40],
        "top5": page_top5[:40],
        "top10": page_top10[:80],
    }
    query_bands = {
        "dimension": "query",
        "label": "Queries",
        "top3_count": len(query_top3),
        "top5_count": len(query_top3) + len(query_top5),
        "top10_count": len(query_top3) + len(query_top5) + len(query_top10),
        "top3": query_top3[:40],
        "top5": query_top5[:40],
        "top10": query_top10[:80],
    }
    mode = str(config.get("rank_bands_dimension") or "auto").strip().lower()
    if mode not in {"auto", "page", "query"}:
        mode = "auto"
    if mode == "query":
        position_bands = query_bands
    elif mode == "page":
        position_bands = page_bands
    else:
        # Auto: when almost no pages sit in top 3 but volume queries do, show queries.
        vol_queries = [
            q
            for q in query_top3
            if int(q.get("impressions") or 0) >= 50 or int(q.get("clicks") or 0) >= 3
        ]
        position_bands = (
            query_bands
            if page_bands["top3_count"] < 5 and len(vol_queries) >= 3
            else page_bands
        )
    position_bands["mode"] = mode
    position_bands["page_top3_count"] = page_bands["top3_count"]
    position_bands["query_top3_count"] = query_bands["top3_count"]

    ai_cur_imps, ai_cur_types = _ai_impressions_from_appearance(payloads["ai_cur"])
    ai_prev_imps, _ = _ai_impressions_from_appearance(payloads["ai_prev"])

    ai_daily_map: dict[str, int] = {}
    for row in payloads["ai_daily"].get("rows") or []:
        keys = row.get("keys") or ["", ""]
        day, appearance = (keys[0] if keys else ""), (keys[1] if len(keys) > 1 else "")
        if not _is_ai_appearance(appearance):
            continue
        ai_daily_map[day] = ai_daily_map.get(day, 0) + int(round(float(row.get("impressions") or 0)))

    ai_daily = [{"date": d, "impressions": ai_daily_map[d]} for d in sorted(ai_daily_map.keys())]
    ai_weekly_buckets: dict[str, dict[str, Any]] = {}
    for row in ai_daily:
        try:
            d = date.fromisoformat(row["date"])
        except ValueError:
            continue
        week_start = d - timedelta(days=d.weekday())
        key = week_start.isoformat()
        bucket = ai_weekly_buckets.setdefault(
            key, {"week_start": key, "label": week_start.strftime("%m-%d"), "impressions": 0}
        )
        bucket["impressions"] += row["impressions"]
    ai_weekly = [ai_weekly_buckets[k] for k in sorted(ai_weekly_buckets.keys())]

    page_ai: dict[str, int] = {}
    for row in payloads["ai_pages"].get("rows") or []:
        keys = row.get("keys") or ["", ""]
        page, appearance = (keys[0] if keys else ""), (keys[1] if len(keys) > 1 else "")
        if not _is_ai_appearance(appearance):
            continue
        page_ai[page] = page_ai.get(page, 0) + int(round(float(row.get("impressions") or 0)))
    ai_pages = [
        {"key": k, "path": _page_path(k), "slug": _slug_from_path(_page_path(k)), "impressions": v}
        for k, v in sorted(page_ai.items(), key=lambda item: item[1], reverse=True)
    ][:12]

    device_total_clicks = sum(d["clicks"] for d in devices) or 1
    device_share = [
        {
            **d,
            "label": (d["key"] or "").title(),
            "share_pct": round((d["clicks"] / device_total_clicks) * 100, 1),
        }
        for d in devices
    ]

    india_clicks = next((c["clicks"] for c in countries if c["key"].upper() in {"IND", "INDIA"}), 0)
    country_total = sum(c["clicks"] for c in countries) or 1
    india_share_pct = round((india_clicks / country_total) * 100, 1)

    # Optional manual AI impressions from tracker_config (GSC Generative AI report is UI-only for now)
    ai_source = "api" if (ai_cur_imps or ai_prev_imps or ai_pages) else "unavailable"
    manual_ai = config.get("ai_by_month") or {}
    if isinstance(manual_ai, dict) and manual_ai:

        def _manual_imps(month_key: str) -> int | None:
            raw = manual_ai.get(month_key)
            if raw is None:
                return None
            if isinstance(raw, dict):
                try:
                    return int(round(float(raw.get("impressions") or 0)))
                except (TypeError, ValueError):
                    return None
            try:
                return int(round(float(raw)))
            except (TypeError, ValueError):
                return None

        man_cur = _manual_imps(report_month)
        man_prev = _manual_imps(prev_month)
        if man_cur is not None or man_prev is not None:
            ai_cur_imps = man_cur or 0
            ai_prev_imps = man_prev or 0
            ai_source = "manual"
            # Optional top pages from current month manual blob
            cur_blob = manual_ai.get(report_month)
            if isinstance(cur_blob, dict) and isinstance(cur_blob.get("top_pages"), list):
                ai_pages = []
                for item in cur_blob.get("top_pages") or []:
                    if not isinstance(item, dict):
                        continue
                    key = str(item.get("key") or item.get("path") or item.get("slug") or "").strip()
                    if not key:
                        continue
                    path = _page_path(key) if "://" in key or key.startswith("/") else f"/{key}"
                    try:
                        imps = int(round(float(item.get("impressions") or 0)))
                    except (TypeError, ValueError):
                        imps = 0
                    ai_pages.append(
                        {
                            "key": key,
                            "path": path,
                            "slug": _slug_from_path(path),
                            "impressions": imps,
                        }
                    )
                ai_pages = ai_pages[:12]

    mom = {
        "clicks_pct": _pct_change(cur_totals["clicks"], prev_totals["clicks"]),
        "impressions_pct": _pct_change(cur_totals["impressions"], prev_totals["impressions"]),
        "ctr_delta": round(cur_totals["ctr"] - prev_totals["ctr"], 2),
        "position_delta": round(prev_totals["position"] - cur_totals["position"], 2),
        "ai_impressions_pct": _pct_change(ai_cur_imps, ai_prev_imps),
        # Only compare MoM when current >= previous (avoid highlighting declines)
        "show_clicks_mom": cur_totals["clicks"] >= prev_totals["clicks"],
        "show_impressions_mom": cur_totals["impressions"] >= prev_totals["impressions"],
        "show_ai_mom": bool(ai_prev_imps) and ai_cur_imps >= ai_prev_imps,
    }

    site_host = ""
    try:
        site_url = config.get("site_url") or ""
        site_host = urlparse(site_url if "://" in site_url else f"https://{site_url}").hostname or ""
        site_host = site_host.removeprefix("www.")
    except Exception:
        site_host = ""

    return {
        "property": property_url,
        "site_url": config.get("site_url") or "",
        "site_host": site_host,
        "report_month": report_month,
        "previous_month": prev_month,
        "report_month_label": month_label(report_month),
        "previous_month_label": month_label(prev_month),
        "windows": {
            "month": {"start": cur_start.isoformat(), "end": cur_end.isoformat()},
            "previous_month": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
            "three_month": {"start": three_start.isoformat(), "end": three_end.isoformat()},
        },
        "current": cur_totals,
        "previous": prev_totals,
        "mom": mom,
        "daily": daily,
        "weekly": weekly,
        "queries": month_queries,
        "pages": [
            {**row, "path": _page_path(row["key"]), "slug": _slug_from_path(_page_path(row["key"]))}
            for row in month_pages
        ],
        "pages_3mo": content_pages,
        "languages": languages,
        "top_by_language": top_by_language,
        "countries": countries,
        "devices": device_share,
        "india_share_pct": india_share_pct,
        "position_bands": position_bands,
        "query_position_bands": query_bands,
        "page_position_bands": page_bands,
        "ai": {
            "current_impressions": ai_cur_imps,
            "previous_impressions": ai_prev_imps,
            "mom_pct": mom["ai_impressions_pct"] if mom["show_ai_mom"] else None,
            "show_mom": mom["show_ai_mom"],
            "types": ai_cur_types,
            "weekly": ai_weekly,
            "top_pages": ai_pages,
            "available": bool(ai_cur_imps or ai_prev_imps or ai_pages),
            "source": ai_source,
            "api_note": (
                None
                if ai_source != "unavailable"
                else (
                    "Google's Generative AI performance report (AI Overviews / AI Mode) is not "
                    "exposed in the Search Console API yet. Add monthly totals under "
                    "tracker settings ai_by_month, or leave this section hidden."
                )
            ),
        },
        "opportunity": _pick_opportunity(month_queries),
        "language_prefixes": language_prefixes,
    }


def _split_query_position_bands(
    queries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Bucket queries by average position; prefer volume within each band."""
    top3: list[dict[str, Any]] = []
    top5: list[dict[str, Any]] = []
    top10: list[dict[str, Any]] = []
    for row in queries:
        pos = float(row.get("position") or 0)
        if pos <= 0:
            continue
        entry = {
            "query": row.get("key") or "",
            "label": row.get("key") or "",
            "path": row.get("key") or "",  # template reuse
            "position": pos,
            "clicks": int(row.get("clicks") or 0),
            "impressions": int(row.get("impressions") or 0),
            "ctr": row.get("ctr"),
        }
        if not entry["query"]:
            continue
        # Keep volume-bearing queries in the lists clients care about
        if pos <= 3:
            if entry["impressions"] >= 25 or entry["clicks"] >= 2:
                top3.append(entry)
        elif pos <= 5:
            if entry["impressions"] >= 25 or entry["clicks"] >= 2:
                top5.append(entry)
        elif pos <= 10:
            if entry["impressions"] >= 25 or entry["clicks"] >= 2:
                top10.append(entry)
    for bucket in (top3, top5, top10):
        bucket.sort(key=lambda item: (item["clicks"], item["impressions"]), reverse=True)
    return top3, top5, top10


def _pick_opportunity(queries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """High impressions, middling position — classic opportunity row."""
    candidates = [
        q
        for q in queries
        if q.get("impressions", 0) >= 200 and 5 <= float(q.get("position") or 0) <= 20
    ]
    candidates.sort(key=lambda q: q["impressions"], reverse=True)
    return candidates[0] if candidates else (queries[0] if queries else None)
