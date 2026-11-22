"""Run the Optimize search job and store it on the location. No cron."""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timezone

from backend.tg.config import settings
from backend.tg.database import get_gbp_optimize, merge_gbp_optimize
from backend.tg.services.dataforseo_client import DataForSeoError, post_json
from backend.tg.services.gbp_opportunities import (
    build_service_recommendations,
    draft_profile_copy,
    projected_listing_score,
    runtime_prompt,
)
from backend.tg.services.gbp_optimize import current_services, locality_of, service_names
from backend.tg.services.gbp_visibility import (
    competitors_from_items,
    match_client_rank,
    parse_maps_items,
)
from backend.tg.services.keyword_research import (
    AdsBudget,
    AdsBudgetExceeded,
    _QUESTION,
    attach_theme_demand,
    classify_demand,
    dedupe_equivalent_seeds,
    discover_keywords,
    fallback_service_seeds,
    resolve_ads_location,
    settings_topic_fallback,
)

MAPS_URL = "https://api.dataforseo.com/v3/serp/google/maps/live/advanced"


def _month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _charge(optimize: dict, day: date, calls: int) -> tuple[dict, str]:
    usage = dict(optimize.get("maps_usage") or {})
    month = _month_key(day)
    if usage.get("month") != month:
        usage = {"month": month, "calls": 0}
    cap = int(settings.GBP_MAPS_MONTHLY_CALL_CAP or 0)
    if cap and int(usage.get("calls") or 0) + calls > cap:
        return usage, "The monthly Maps check limit for this client has been reached."
    usage["calls"] = int(usage.get("calls") or 0) + calls
    return usage, ""


def _previous_point(previous: list[dict], phrase: str, point: dict, day: str) -> dict | None:
    for keyword in previous:
        if (keyword.get("phrase") or "").lower() != phrase.lower():
            continue
        for saved in keyword.get("points") or []:
            if saved.get("id") != point["id"]:
                continue
            if saved.get("scanned_on") != day or saved.get("error"):
                continue
            if round(float(saved.get("lat") or 0), 4) != round(float(point["lat"]), 4):
                continue
            if round(float(saved.get("lng") or 0), 4) != round(float(point["lng"]), 4):
                continue
            return saved
    return None


def _fail(client_id: str, location_id: str, message: str, **extra) -> dict:
    print(f"[gbp] error {message}", flush=True)
    merge_gbp_optimize(
        client_id,
        location_id,
        {
            "gaps_status": "error",
            "last_error": message,
            "gaps_checked_at": datetime.now(timezone.utc).isoformat(),
            **extra,
        },
    )
    return get_gbp_optimize(client_id, location_id)


def _category_name(location: dict) -> str:
    primary = (location.get("categories") or {}).get("primaryCategory") or {}
    return primary.get("displayName") or ""


def _service_description_map(location: dict) -> dict[str, str]:
    return {item["displayName"]: item.get("description") or "" for item in current_services(location)}


def _label_rows(rows: list[dict], *, city_name: str) -> list[dict]:
    labeled = []
    for row in rows:
        labeled.append(
            {
                **row,
                **classify_demand(
                    city_volume=row.get("volume") if isinstance(row.get("volume"), int) else None,
                    broader_volume=row.get("broader_volume") if isinstance(row.get("broader_volume"), int) else None,
                    theme_has_demand=False,
                    city_name=city_name,
                ),
            }
        )
    return attach_theme_demand(labeled, city_name=city_name)


def _step(name: str, detail="") -> None:
    extra = f" {detail}" if detail else ""
    print(f"[gbp] step={name}{extra}", flush=True)


def _allowed_phrases(items, allowed: dict[str, str]) -> list[str]:
    cleaned = []
    seen = set()
    for item in items or []:
        key = str(item or "").strip().lower()
        if key in allowed and key not in seen:
            seen.add(key)
            cleaned.append(allowed[key])
    return cleaned


def _report_lines(reported: list) -> list[str]:
    lines = []
    for item in reported or []:
        if isinstance(item, dict):
            keyword = str(item.get("keyword") or "").strip()
            impressions = item.get("impressions") or 0
        else:
            keyword, impressions = str(item or "").strip(), 0
        if keyword:
            lines.append(f"- {keyword} ({impressions} impressions)")
    return lines[:40]


def _ai_settings_seeds(topics: list[dict], completer, category: str, instruction: str = "") -> list[str]:
    """Up to 10 Settings topics that can be written as GMB services. No word-overlap gate."""
    fallback = settings_topic_fallback(topics)
    catalog = []
    seen = set()
    from backend.tg.services.keyword_research import _topic_text, top_topics, topics_have_saved_scores

    if topics_have_saved_scores(topics):
        for topic in top_topics(topics, 40):
            text = _topic_text(topic)
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                catalog.append(text)
    allowed = {text.lower(): text for text in catalog}
    if not completer or not catalog:
        return fallback
    try:
        raw = completer(
            "Choose Settings topics that can be written as a Google Business Profile service.\n"
            "A keeper is a service line, the kind of name that goes on the Google service list.\n"
            "Drop symptoms, questions, doctor or hospital names, the word best, and near me.\n"
            "The topics you keep must not be semantically similar. Return different offerings.\n"
            "Choose only from the list. Do not invent. Return at most 10.\n"
            + runtime_prompt(instruction)
            + 'Reply as JSON {"seeds": ["..."]}.\n'
            f"Category: {category}\nTopics:\n"
            + "\n".join(f"- {text}" for text in catalog)
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] settings seeds failed: {exc}", flush=True)
        return fallback
    chosen = _allowed_phrases((raw or {}).get("seeds"), allowed)[:10]
    return chosen or fallback


def _ai_seed_bundle(
    settings_seeds: list[str],
    services: list[str],
    reported: list,
    completer,
    instruction: str = "",
) -> dict:
    """One call: pick up to 10 GMB services, then dedupe with Settings into the final seed list."""
    service_fallback = fallback_service_seeds(services, settings_seeds, reported)
    seed_fallback = dedupe_equivalent_seeds([*settings_seeds, *service_fallback])
    if not services:
        return {"service_seeds": [], "seeds": list(settings_seeds)}
    if not completer:
        return {"service_seeds": service_fallback, "seeds": seed_fallback}
    service_allowed = {name.lower(): name for name in services}
    seed_allowed = {name.lower(): name for name in [*settings_seeds, *services]}
    try:
        raw = completer(
            "Build the final seed list for one clinic.\n"
            "From the profile services, take up to 10 that are not already covered by a Settings seed. "
            "Prefer the lowest search-report impressions: a gap, not a query the listing already wins. "
            "Copy service names only from the profile list. Do not use search volume.\n"
            "Then combine those services with the Settings seeds. Merge only true equivalents "
            "(BPH Treatment with Enlarged Prostate Treatment). Keep distinct procedures. "
            "Prefer the longer service line. Do not invent a phrase. "
            "Do not drop a real offering just to shorten the list.\n"
            + runtime_prompt(instruction)
            + 'Reply as JSON {"service_seeds": ["..."], "seeds": ["..."]}.\n'
            "Settings seeds:\n"
            + "\n".join(f"- {seed}" for seed in settings_seeds)
            + "\nProfile services:\n"
            + "\n".join(f"- {name}" for name in services)
            + "\nSearch report:\n"
            + ("\n".join(_report_lines(reported)) or "- none")
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] seed bundle failed: {exc}", flush=True)
        return {"service_seeds": service_fallback, "seeds": seed_fallback}
    service_seeds = _allowed_phrases((raw or {}).get("service_seeds"), service_allowed)[:10]
    seeds = _allowed_phrases((raw or {}).get("seeds"), seed_allowed)
    if not seeds:
        return {"service_seeds": service_fallback, "seeds": seed_fallback}
    return {"service_seeds": service_seeds, "seeds": seeds}


def _keyword_row(phrase: str, source: dict | None) -> dict:
    row = source or {}
    measured = row.get("demand_status") == "measured" and isinstance(row.get("volume"), int)
    return {
        "phrase": phrase,
        "volume": row.get("volume") if measured else None,
        "broader_volume": row.get("broader_volume") if isinstance(row.get("broader_volume"), int) else None,
        "demand_status": row.get("demand_status") or "unknown",
        "demand_location": row.get("demand_location") or "",
        "service": row.get("service") or "",
        "sentence": "",
        "sentence_key": "",
        "clinic_rank": None,
        "weighted_gap": None,
        "opportunity_score": None,
        "points": [],
        "competitors": [],
    }


def _fallback_final_keywords(rows: list[dict], *, limit: int = 10) -> list[dict]:
    chosen = []
    seen = set()
    ranked = sorted(rows, key=lambda row: -(row.get("volume") or row.get("broader_volume") or 0))
    for row in ranked:
        phrase = str(row.get("keyword") or "").strip()
        key = phrase.lower()
        if not phrase or key in seen or phrase.lower().startswith(_QUESTION) or "?" in phrase:
            continue
        seen.add(key)
        chosen.append(_keyword_row(phrase, row))
        if len(chosen) >= limit:
            break
    return chosen


def _ai_final_keywords(rows: list[dict], *, category: str, business: str, completer, instruction: str = "") -> list[dict]:
    """One call: drop junk and keep 10 different service lines. Maps is not used."""
    ranked = sorted(rows, key=lambda row: -(row.get("volume") or row.get("broader_volume") or 0))
    sample = ranked[:100]
    fallback = _fallback_final_keywords(sample)
    by_key = {str(row.get("keyword") or "").strip().lower(): row for row in sample if row.get("keyword")}
    if not completer or not sample:
        return fallback
    lines = []
    for row in sample:
        volume = row.get("volume") if row.get("demand_status") == "measured" else row.get("broader_volume")
        lines.append(f"- {row.get('keyword')} | demand={volume if isinstance(volume, int) else 'unknown'} | status={row.get('demand_status') or 'unknown'}")
    try:
        raw = completer(
            "Pick the next Google Business Profile service lines for this clinic.\n"
            "Drop a truncated leftover, a size or language variant, a competitor or hospital or doctor name, or a question.\n"
            "Keep a phrase only if it can be written as a service name. "
            "Do not drop a phrase only because its demand is unknown. "
            "Do not guess what the clinic offers, except when the owner note says they do not offer it.\n"
            "Score what remains on relevance to this listing, local intent "
            "(a nearby patient would search this to book; not a brand, a how-to, or a doctor name), "
            "and demand using the number given. Do not invent demand.\n"
            "Take one phrase per category, then fill to 10. "
            "A second phrase from a category is allowed only when there are fewer than 10 categories. "
            "Every keeper must itself be a service line. The 10 must be different offerings.\n"
            "Choose only from the list. Do not invent.\n"
            + runtime_prompt(instruction)
            + 'Reply as JSON {"keywords": ["..."]}.\n'
            f"Business: {business}\nCategory: {category}\nPhrases:\n"
            + "\n".join(lines)
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] final keywords failed: {exc}", flush=True)
        return fallback
    chosen = []
    seen = set()
    for item in (raw or {}).get("keywords") or []:
        key = str(item or "").strip().lower()
        if key in by_key and key not in seen:
            seen.add(key)
            chosen.append(_keyword_row(by_key[key]["keyword"], by_key[key]))
        if len(chosen) >= 10:
            break
    return chosen or fallback


def _ai_service_hints(keywords: list[dict], services: list[str], completer, instruction: str = "") -> dict:
    if not completer or not keywords:
        return {}
    try:
        raw = completer(
            "Map each phrase to a service already on this clinic's Google list.\n"
            "match is same or none. same means it is that listed offering. none means it is not on the list.\n"
            "Copy current_service from the service list when match is same, otherwise leave it empty.\n"
            "concept is the service name to write. Use the phrase itself. "
            "Only if that phrase still cannot be written as a service, supply a similar service line. "
            "That rewrite is the last option and about a 1% case. "
            "Never use a doctor name, a hospital name, best, or near me as the concept.\n"
            "Do not choose ADD, KEEP, or REPLACE.\n"
            + runtime_prompt(instruction)
            + 'Reply as JSON {"items": [{"keyword": "", "match": "", "concept": "", "current_service": ""}]}.\n'
            "Services:\n"
            + "\n".join(f"- {name}" for name in services)
            + "\nSearches:\n"
            + "\n".join(f"- {row.get('phrase')}" for row in keywords)
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] service match failed: {exc}", flush=True)
        return {}
    hints = {}
    for item in (raw or {}).get("items") or []:
        if isinstance(item, dict) and item.get("keyword"):
            hints[str(item["keyword"]).strip().lower()] = item
    return hints


def _clean_service_description(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return ""
    low = value.lower()
    if "patients can ask about this service when they book" in low:
        return ""
    return value[:300]


def _row_for_service(by_name: dict, proposed: str) -> dict:
    key = (proposed or "").strip().lower()
    if key in by_name:
        return by_name[key]
    for name, row in by_name.items():
        if name and key and (name in key or key in name):
            return row
    return {}


def _ai_suggestion_lines(recommendations: list[dict], completer, instruction: str = "") -> None:
    """Last model step: one suggestion sentence and a short Google service description."""
    shown = [item for item in recommendations if item.get("action") in {"ADD", "REPLACE"} and item.get("proposed_name")]
    for item in recommendations:
        item["why"] = ""
        item["proposed_description"] = _clean_service_description(item.get("proposed_description") or "")
    if not completer or not shown:
        return
    lines = [f"- {item.get('action')} | {item.get('proposed_name')}" for item in shown]
    try:
        raw = completer(
            "For each service, write two fields a clinic can use on Google Business Profile.\n"
            "why: one sentence on why a patient would look for this service.\n"
            "description: the Google service description. One or two short accurate sentences about what the treatment is. Under 280 characters.\n"
            "Do not include the clinic name, a hospital, a city, Google, a service list, awards, or 'ask when you book'.\n"
            "Do not invent a search volume or a rank.\n"
            + runtime_prompt(instruction)
            + 'Reply as JSON {"items": [{"name": "", "why": "", "description": ""}]}.\n'
            + "\n".join(lines)
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] suggestion lines failed: {exc}", flush=True)
        return
    by_name = {}
    for item in (raw or {}).get("items") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        by_name[str(item["name"]).strip().lower()] = {
            "why": re.sub(r"\s+", " ", str(item.get("why") or "")).strip(),
            "description": _clean_service_description(item.get("description") or ""),
        }
    for item in shown:
        row = _row_for_service(by_name, item.get("proposed_name") or "")
        item["why"] = row.get("why") or ""
        if row.get("description"):
            item["proposed_description"] = row["description"]


def _scan_phrase(
    phrase: str,
    points: list[dict],
    *,
    previous: list[dict],
    day,
    day_text: str,
    send,
    place_id: str,
    location: dict,
    phone: str,
    lat: float,
    lng: float,
    usage: dict,
) -> tuple[list[dict], dict, str]:
    point_rows = []
    stopped = ""
    for point in points:
        cached = _previous_point(previous, phrase, point, day_text)
        if cached:
            point_rows.append(cached)
            continue
        usage, stopped = _charge({"maps_usage": usage}, day, 1)
        if stopped:
            point_rows.append({**point, "error": stopped, "found": False, "rank": None, "competitors": [], "scanned_on": day_text})
            continue
        try:
            body = send(
                MAPS_URL,
                [
                    {
                        "keyword": phrase,
                        "language_code": "en",
                        "location_coordinate": f"{point['lat']},{point['lng']},15z",
                        "device": "mobile",
                        "depth": 20,
                    }
                ],
            )
            items = parse_maps_items(body)
            matched = match_client_rank(
                items,
                place_id=place_id,
                name=location.get("title") or "",
                phone=phone,
                lat=lat,
                lng=lng,
            )
            point_rows.append({**point, **matched, "competitors": competitors_from_items(items, matched.get("rank"), place_id=place_id), "scanned_on": day_text})
        except DataForSeoError as exc:
            point_rows.append({**point, "error": exc.message, "found": False, "rank": None, "competitors": [], "scanned_on": day_text})
    return point_rows, usage, stopped


def run_gap_optimize(
    client_id: str,
    location_id: str,
    *,
    location: dict,
    topics: list[dict],
    reported: list[str],
    instruction: str = "",
    lat: float | None = None,
    lng: float | None = None,
    place_id: str = "",
    phone: str = "",
    poster=None,
    completer=None,
    today: date | None = None,
) -> dict:
    day = today or datetime.now(timezone.utc).date()
    day_text = day.isoformat()
    services = service_names(location)
    category = _category_name(location)
    locality = locality_of(location)
    ads_budget = AdsBudget()
    send = ads_budget.wrap(poster or post_json)
    if poster is not None:
        demand_location, demand_is_country = (locality or "India"), False
    else:
        demand_location, demand_is_country = resolve_ads_location(locality)
    city_label = locality if locality and not demand_is_country else "India"
    started = time.perf_counter()
    settings_seeds = _ai_settings_seeds(topics, completer, category, instruction)
    _step("settings_seeds", f"elapsed={time.perf_counter() - started:.2f}s {settings_seeds}")
    started = time.perf_counter()
    bundle = _ai_seed_bundle(settings_seeds, services, reported, completer, instruction)
    seeds = bundle["seeds"]
    _step("service_seeds", bundle.get("service_seeds") or [])
    _step("seeds", f"elapsed={time.perf_counter() - started:.2f}s {seeds}")
    if not seeds:
        message = "No confirmed services or matching topics to optimize."
        from backend.tg.services.keyword_research import topics_have_saved_scores

        if topics and not topics_have_saved_scores(topics) and not services:
            message = "Save recommendation scores in Settings before Optimize can choose searches."
        return _fail(client_id, location_id, message, instruction=instruction or "")
    started = time.perf_counter()
    try:
        print("[gbp] ads skipped city volume retry and India volume", flush=True)
        discovered = discover_keywords(seeds, location_name=demand_location, poster=send)
        seen = {row["keyword"].lower() for row in discovered}
        for seed in seeds:
            if seed.lower() not in seen:
                discovered.append({"keyword": seed, "volume": None, "service": seed})
        with_volume = sum(1 for row in discovered if isinstance(row.get("volume"), int))
        print(
            f"[gbp] ads summary calls={ads_budget.calls} phrases={len(discovered)} "
            f"with_volume={with_volume} null={len(discovered) - with_volume} "
            f"spent={ads_budget.spent:.2f} cap={ads_budget.cap:.2f}",
            flush=True,
        )
        discovered = _label_rows(discovered, city_name=city_label)
        by_volume = sorted(discovered, key=lambda row: -(row.get("volume") or row.get("broader_volume") or 0))
        _step(
            "ads_discovered",
            f"elapsed={time.perf_counter() - started:.2f}s n={len(discovered)} "
            f"top={[(row.get('keyword'), row.get('volume'), row.get('demand_status')) for row in by_volume[:25]]}",
        )
    except (DataForSeoError, AdsBudgetExceeded) as exc:
        return _fail(client_id, location_id, exc.message, instruction=instruction or "")
    # Maps rank checks are paused. The 17-pin scan and the protection scan stay in _scan_phrase
    # and are not called. The final 10 come from the model using Ads demand.
    started = time.perf_counter()
    keywords = _ai_final_keywords(
        discovered,
        category=category,
        business=location.get("title") or "",
        completer=completer,
        instruction=instruction,
    )
    _step(
        "final10",
        f"elapsed={time.perf_counter() - started:.2f}s "
        + str([(row["phrase"], row.get("volume"), row.get("demand_status")) for row in keywords]),
    )
    usage = dict(get_gbp_optimize(client_id, location_id).get("maps_usage") or {})
    stopped = ""
    descriptions = _service_description_map(location)
    started = time.perf_counter()
    hints = _ai_service_hints(keywords, services, completer, instruction)
    _step("service_match", f"elapsed={time.perf_counter() - started:.2f}s n={len(hints)}")
    recommendations = build_service_recommendations(
        keywords,
        services,
        category=category,
        seeds=seeds,
        business_name=location.get("title") or "",
        locality=locality,
        service_descriptions=descriptions,
        hints=hints,
    )
    for item in recommendations:
        item.pop("needs_protection", None)
    _ai_suggestion_lines(recommendations, completer, instruction)
    _step(
        "recs",
        [
            (item.get("action"), item.get("current_name"), item.get("proposed_name"), item.get("why"))
            for item in recommendations
        ],
    )
    copy = draft_profile_copy(
        {
            "business_name": location.get("title") or "",
            "locality": locality,
            "category": category,
            "current_description": ((location.get("profile") or {}).get("description") or ""),
            "services": services,
            "keywords": keywords,
            "recommendations": recommendations,
            "instruction": instruction,
        }
    )
    listing = get_gbp_optimize(client_id, location_id).get("listing") or {}
    projection = projected_listing_score(listing, description=copy.get("description") or "")
    for item in recommendations:
        added = [item["proposed_name"]] if item.get("action") == "ADD" and item.get("proposed_name") else []
        item_projection = projected_listing_score(listing, added_services=added)
        if item_projection:
            item["potential_score"] = item_projection["potential"]
            item["current_score"] = item_projection["current"]
    if copy.get("error"):
        print(f"[gbp] error {copy.get('error')}", flush=True)
    _step("copy", f"title={copy.get('title')!r} desc={(copy.get('description') or '')[:180]!r}")
    now = datetime.now(timezone.utc).isoformat()
    merge_gbp_optimize(
        client_id,
        location_id,
        {
            "gaps_status": "error" if stopped and not keywords else "ready",
            "gaps_checked_at": now,
            "seeds": seeds,
            "suggested_title": copy.get("title") or "",
            "suggested_description": copy.get("description") or "",
            "instruction": instruction or "",
            "not_used": [],
            "keywords": keywords,
            "service_recommendations": recommendations,
            "protection_scans": [],
            "potential_score": projection,
            "maps_usage": usage,
            "last_error": stopped or copy.get("error") or "",
        },
    )
    return get_gbp_optimize(client_id, location_id)

