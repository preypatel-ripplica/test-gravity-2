"""Google Trends (web + YouTube) scoring for client topics via DataForSEO.

Region defaults to India. Batches up to 5 keywords per Live Explore request
(~$0.011/task) to control cost. Logs every request cost to the terminal.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings

DATAFORSEO_TRENDS_URL = (
    "https://api.dataforseo.com/v3/keywords_data/google_trends/explore/live"
)

_FORBIDDEN_RE = re.compile(r'[<>|\\"\-+=~!:*()\[\]{}]')

# Max 5 keywords per Explore task; billed per task (~$0.011 live)
_BATCH_SIZE = 5
_LIVE_COST_ESTIMATE = 0.011

_STOP_STATUS_MARKERS = (
    "payment",
    "balance",
    "fund",
    "credit",
    "limit",
    "quota",
    "unauthorized",
    "forbidden",
)


def _log(msg: str) -> None:
    print(f"[trends] {msg}", flush=True)


def _auth_header() -> str:
    login = (settings.DATAFORSEO_LOGIN or "").strip()
    password = (settings.DATAFORSEO_PASSWORD or "").strip()
    if not login or not password:
        raise ValueError(
            "DataForSEO credentials missing. Set DATAFORSEO_LOGIN and "
            "DATAFORSEO_PASSWORD in .env (https://app.dataforseo.com/api-access)."
        )
    token = base64.b64encode(f"{login}:{password}".encode()).decode()
    return f"Basic {token}"


def _sanitize_keyword(text: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    cleaned = _FORBIDDEN_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) < 2 or len(cleaned) > 100:
        return None
    return cleaned


def _chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _parse_multi_series(item: dict | None, n_keywords: int) -> list[list[dict]]:
    series: list[list[dict]] = [[] for _ in range(n_keywords)]
    if not item or item.get("type") != "google_trends_graph":
        return series
    for row in item.get("data") or []:
        values = row.get("values") or []
        missing = bool(row.get("missing_data"))
        ts = int(row.get("timestamp") or 0)
        date_from = row.get("date_from")
        for i in range(n_keywords):
            if i >= len(values) or values[i] is None or missing:
                continue
            try:
                val = float(values[i])
            except (TypeError, ValueError):
                continue
            series[i].append(
                {"timestamp": ts, "value": val, "date_from": date_from}
            )
    return series


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _series_avg(points: list[dict]) -> float | None:
    return _avg([p["value"] for p in points])


def _momentum(points: list[dict]) -> float | None:
    if len(points) < 8:
        return None
    recent_n = max(4, len(points) // 4)
    recent = points[-recent_n:]
    prior = points[-(2 * recent_n) : -recent_n]
    if not prior:
        return None
    recent_avg = _series_avg(recent)
    prior_avg = _series_avg(prior)
    if recent_avg is None or prior_avg is None or prior_avg <= 0:
        if recent_avg and recent_avg > 0:
            return 1.0
        return None
    return max(-1.0, min(2.0, (recent_avg / prior_avg) - 1.0))


def _confidence(
    web_avg: float | None, yt_avg: float | None, web_points: int, yt_points: int
) -> str:
    has_web = web_avg is not None and web_avg > 0 and web_points >= 4
    has_yt = yt_avg is not None and yt_avg > 0 and yt_points >= 4
    if has_web and has_yt:
        return "high"
    if has_web or has_yt:
        return "medium"
    return "low"


def _percentile_ranks(values: list[float | None]) -> list[float | None]:
    indexed = [(i, v) for i, v in enumerate(values) if v is not None]
    if not indexed:
        return [None] * len(values)
    indexed.sort(key=lambda x: x[1])
    n = len(indexed)
    ranks: list[float | None] = [None] * len(values)
    i = 0
    while i < n:
        j = i
        while j < n and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j - 1) / 2.0
        pct = (avg_rank / (n - 1) * 100.0) if n > 1 else 50.0
        for k in range(i, j):
            ranks[indexed[k][0]] = pct
        i = j
    return ranks


def _compose_score(
    web_pct: float | None,
    yt_pct: float | None,
    momentum: float | None,
    rising_flag: int,
) -> float | None:
    parts: list[tuple[float, float]] = []
    if web_pct is not None:
        parts.append((0.40, web_pct))
    if yt_pct is not None:
        parts.append((0.30, yt_pct))
    if momentum is not None:
        parts.append((0.20, ((momentum + 1.0) / 3.0) * 100.0))
    parts.append((0.10, {0: 0.0, 1: 50.0, 2: 100.0}.get(rising_flag or 0, 0.0)))
    if web_pct is None and yt_pct is None and momentum is None:
        return None
    total_w = sum(w for w, _ in parts)
    if total_w <= 0:
        return None
    return round(max(0.0, min(100.0, sum(w * v for w, v in parts) / total_w)), 1)


def _is_fresh(topic: dict, geo: str, ttl_days: int) -> bool:
    if topic.get("trend_geo") != geo:
        return False
    fetched = topic.get("trend_fetched_at")
    if not fetched:
        return False
    try:
        ts = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - ts < timedelta(days=ttl_days)


def _should_stop(message: str | None, status_code: int | None = None) -> bool:
    if status_code in (40100, 40200, 40201, 40202, 40203, 40204, 40205, 40206):
        return True
    text = (message or "").lower()
    return any(m in text for m in _STOP_STATUS_MARKERS)


def _weight_rank(weight: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(weight or "medium", 1)


async def _fetch_batch(
    client: httpx.AsyncClient,
    keywords: list[str],
    *,
    trend_type: str,
    location_name: str,
) -> dict[str, Any]:
    payload = [
        {
            "keywords": keywords,
            "location_name": location_name,
            "language_code": "en",
            "type": trend_type,
            "time_range": "past_12_months",
            "item_types": ["google_trends_graph"],
        }
    ]
    label = f"{trend_type} [{', '.join(keywords)}]"
    _log(f"→ request {label}")

    try:
        resp = await client.post(DATAFORSEO_TRENDS_URL, json=payload, timeout=90.0)
    except httpx.HTTPError as exc:
        _log(f"✗ HTTP error on {label}: {exc}")
        return {
            "series": [[] for _ in keywords],
            "cost": 0.0,
            "error": f"HTTP error: {exc}",
            "stop": False,
        }

    try:
        body = resp.json()
    except ValueError:
        _log(f"✗ Non-JSON response on {label}: HTTP {resp.status_code}")
        return {
            "series": [[] for _ in keywords],
            "cost": 0.0,
            "error": f"Non-JSON response HTTP {resp.status_code}",
            "stop": resp.status_code in (401, 402, 403),
        }

    top_code = body.get("status_code")
    top_msg = body.get("status_message") or ""
    cost = float(body.get("cost") or 0)
    _log(f"← {label} status={top_code} cost=${cost:.4f} msg={top_msg!r}")

    if top_code and top_code != 20000:
        return {
            "series": [[] for _ in keywords],
            "cost": cost,
            "error": top_msg or f"DataForSEO error {top_code}",
            "stop": _should_stop(top_msg, top_code),
        }

    tasks = body.get("tasks") or []
    if not tasks:
        _log(f"✗ {label}: empty tasks array")
        return {
            "series": [[] for _ in keywords],
            "cost": cost,
            "error": "empty tasks",
            "stop": False,
        }

    task = tasks[0]
    task_cost = float(task.get("cost") or cost or 0)
    task_code = task.get("status_code")
    task_msg = task.get("status_message") or ""
    if task_cost and abs(task_cost - cost) > 1e-9:
        _log(f"  task cost=${task_cost:.4f} status={task_code} {task_msg!r}")

    if task_code not in (20000, None):
        _log(f"✗ {label}: task failed {task_code} {task_msg}")
        return {
            "series": [[] for _ in keywords],
            "cost": task_cost or cost,
            "error": task_msg or f"task {task_code}",
            "stop": _should_stop(task_msg, task_code),
        }

    results = task.get("result") or []
    if not results:
        _log(f"⚠ {label}: no result (often insufficient Trends data)")
        return {
            "series": [[] for _ in keywords],
            "cost": task_cost or cost,
            "error": None,
            "stop": False,
        }

    items = results[0].get("items") or []
    graph = next((i for i in items if i.get("type") == "google_trends_graph"), None)
    series = _parse_multi_series(graph, len(keywords))
    avgs = [_series_avg(s) for s in series]
    _log(
        f"  ok points={[len(s) for s in series]} avgs="
        f"{[round(a, 1) if a is not None else None for a in avgs]}"
    )
    return {
        "series": series,
        "cost": task_cost or cost,
        "error": None,
        "stop": False,
    }


async def analyze_topics_trends(
    topics: list[dict],
    *,
    force: bool = False,
) -> tuple[list[dict], dict]:
    """Score topics with India Google Search + YouTube Trends.

    Batches up to 5 keywords/task. Processes high → medium → low first.
    Stops immediately on balance/payment errors so credit is not wasted.
    """
    geo = (settings.TRENDS_GEO or "IN").strip().upper() or "IN"
    location_name = (settings.TRENDS_LOCATION_NAME or "India").strip() or "India"
    ttl_days = max(0, int(settings.TRENDS_TTL_DAYS or 7))
    now_iso = datetime.now(timezone.utc).isoformat()

    updated = [dict(t) for t in topics]
    to_fetch: list[int] = []
    skipped_cached = 0

    for i, topic in enumerate(updated):
        has_interest = (
            topic.get("web_interest") is not None
            or topic.get("youtube_interest") is not None
        )
        if (
            not force
            and _is_fresh(topic, geo, ttl_days)
            and (topic.get("trend_score") is not None or has_interest)
        ):
            skipped_cached += 1
            continue
        if not _sanitize_keyword(topic.get("text") or ""):
            _log(f"skip invalid keyword: {topic.get('text')!r}")
            topic["trend_score"] = None
            topic["trend_confidence"] = "low"
            topic["trend_geo"] = geo
            topic["web_interest"] = None
            topic["youtube_interest"] = None
            topic["momentum"] = None
            topic["rising_flag"] = 0
            topic["trend_fetched_at"] = now_iso
            continue
        to_fetch.append(i)

    to_fetch.sort(key=lambda idx: (_weight_rank(updated[idx].get("weight")), idx))

    n_fetch = len(to_fetch)
    n_batches = len(_chunk(to_fetch, _BATCH_SIZE)) if to_fetch else 0
    est_tasks = n_batches * 2
    est_cost = est_tasks * _LIVE_COST_ESTIMATE

    _log(
        f"start force={force} geo={geo} total={len(updated)} "
        f"to_fetch={n_fetch} cached_skip={skipped_cached} "
        f"batches={n_batches}×2(web+yt)≈{est_tasks} tasks "
        f"est_cost≈${est_cost:.2f} (~${_LIVE_COST_ESTIMATE}/live task)"
    )
    if n_fetch:
        _log(
            f"cost tip: old 1-kw mode was {n_fetch * 2} tasks ≈ "
            f"${n_fetch * 2 * _LIVE_COST_ESTIMATE:.2f}; "
            f"batched mode ≈ ${est_cost:.2f}"
        )

    summary: dict[str, Any] = {
        "geo": geo,
        "scored": 0,
        "insufficient_data": 0,
        "skipped_cached": skipped_cached,
        "fetched_at": now_iso,
        "error": None,
        "api_tasks": 0,
        "total_cost": 0.0,
    }

    if not to_fetch:
        summary["scored"] = sum(1 for t in updated if t.get("trend_score") is not None)
        summary["insufficient_data"] = sum(
            1 for t in updated if t.get("trend_confidence") == "low"
        )
        _log("nothing to fetch")
        return updated, summary

    auth = _auth_header()
    headers = {"Authorization": auth, "Content-Type": "application/json"}
    metrics: dict[int, dict] = {}
    completed: set[int] = set()

    async with httpx.AsyncClient(headers=headers) as client:
        for batch_num, batch_idxs in enumerate(_chunk(to_fetch, _BATCH_SIZE), start=1):
            keywords = [_sanitize_keyword(updated[i]["text"]) for i in batch_idxs]
            assert all(keywords)
            _log(
                f"batch {batch_num}/{n_batches} "
                f"weights={[updated[i].get('weight') for i in batch_idxs]} "
                f"keywords={keywords}"
            )

            web = await _fetch_batch(
                client, keywords, trend_type="web", location_name=location_name
            )
            summary["api_tasks"] += 1
            summary["total_cost"] += float(web.get("cost") or 0)

            if web.get("stop"):
                summary["error"] = (
                    web.get("error") or "DataForSEO stopped (balance/limit)"
                )
                _log(f"STOP after web: {summary['error']}")
                break

            if web.get("error"):
                _log(f"web error (continuing): {web['error']}")
                if not summary["error"]:
                    summary["error"] = web["error"]

            yt = await _fetch_batch(
                client, keywords, trend_type="youtube", location_name=location_name
            )
            summary["api_tasks"] += 1
            summary["total_cost"] += float(yt.get("cost") or 0)

            if yt.get("stop"):
                summary["error"] = (
                    yt.get("error") or "DataForSEO stopped (balance/limit)"
                )
                _log(f"STOP after youtube: {summary['error']}")
                # Keep web data from this batch
                for i, idx in enumerate(batch_idxs):
                    web_pts = (web.get("series") or [[]])[i]
                    metrics[idx] = {
                        "web_points": web_pts,
                        "yt_points": [],
                        "web_avg": _series_avg(web_pts),
                        "yt_avg": None,
                        "rising_flag": 0,
                    }
                    completed.add(idx)
                break

            if yt.get("error"):
                _log(f"youtube error (continuing): {yt['error']}")
                if not summary["error"]:
                    summary["error"] = yt["error"]

            for i, idx in enumerate(batch_idxs):
                web_pts = (web.get("series") or [[]])[i]
                yt_pts = (yt.get("series") or [[]])[i]
                web_avg = _series_avg(web_pts)
                yt_avg = _series_avg(yt_pts)
                metrics[idx] = {
                    "web_points": web_pts,
                    "yt_points": yt_pts,
                    "web_avg": web_avg,
                    "yt_avg": yt_avg,
                    "rising_flag": 0,
                }
                completed.add(idx)
                _log(
                    f"  · {updated[idx]['text']!r}: web={web_avg} yt={yt_avg}"
                )

            _log(
                f"running total: tasks={summary['api_tasks']} "
                f"cost=${summary['total_cost']:.4f} completed={len(completed)}/{n_fetch}"
            )

    # Apply metrics for completed topics
    for idx in completed:
        m = metrics[idx]
        topic = updated[idx]
        mom = _momentum(m["web_points"])
        if mom is None:
            mom = _momentum(m["yt_points"])
        conf = _confidence(
            m["web_avg"], m["yt_avg"], len(m["web_points"]), len(m["yt_points"])
        )
        topic["web_interest"] = (
            round(m["web_avg"], 1) if m["web_avg"] is not None else None
        )
        topic["youtube_interest"] = (
            round(m["yt_avg"], 1) if m["yt_avg"] is not None else None
        )
        topic["momentum"] = round(mom, 3) if mom is not None else None
        topic["rising_flag"] = 0
        topic["trend_confidence"] = conf
        topic["trend_geo"] = geo
        topic["trend_fetched_at"] = now_iso

    # Percentile score across all topics that have interest data.
    # Always compose a score when web/yt interest exists — even for low
    # confidence (sparse series). The UI shows a "Low data" badge instead
    # of hiding the score.
    all_web = [t.get("web_interest") for t in updated]
    all_yt = [t.get("youtube_interest") for t in updated]
    all_web_pct = _percentile_ranks(all_web)
    all_yt_pct = _percentile_ranks(all_yt)
    for i, topic in enumerate(updated):
        if topic.get("web_interest") is None and topic.get("youtube_interest") is None:
            topic["trend_score"] = None
            continue
        topic["trend_score"] = _compose_score(
            all_web_pct[i],
            all_yt_pct[i],
            topic.get("momentum"),
            int(topic.get("rising_flag") or 0),
        )

    summary["scored"] = sum(1 for t in updated if t.get("trend_score") is not None)
    summary["insufficient_data"] = sum(
        1 for t in updated if t.get("trend_confidence") == "low"
    )
    remaining = n_fetch - len(completed)
    _log(
        f"done scored={summary['scored']} low_data={summary['insufficient_data']} "
        f"completed={len(completed)} remaining_unfetched={remaining} "
        f"tasks={summary['api_tasks']} total_cost=${summary['total_cost']:.4f} "
        f"error={summary['error']!r}"
    )
    if remaining > 0 and summary["error"]:
        _log(
            f"partial run: {remaining} topics not fetched because of: {summary['error']}"
        )
    return updated, summary
