"""Local keyword discovery for GBP Optimize.

Seeds come from the top saved website topics that are not already listing services.
DataForSEO expands them. The shortlist is only phrases absent from Google's own report.
"""

from __future__ import annotations

import math
import re
from typing import Callable

from backend.tg.services.dataforseo_client import auth_header, post_json
from backend.tg.services.gbp_optimize import _tokens

import httpx

LOCATIONS_URL = "https://api.dataforseo.com/v3/keywords_data/google_ads/locations/in"
_LOCATION_CACHE: list[dict] | None = None

KEYWORDS_URL = "https://api.dataforseo.com/v3/keywords_data/google_ads/keywords_for_keywords/live"
VOLUME_URL = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
ADS_CALL_USD = 0.09
ADS_SPEND_CAP_USD = 0.15


class AdsBudgetExceeded(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class AdsBudget:
    """Stop Google Ads calls once the next one would pass the per-run cap."""

    def __init__(self, cap: float = ADS_SPEND_CAP_USD):
        self.cap = float(cap)
        self.spent = 0.0
        self.calls = 0

    def wrap(self, send: Callable) -> Callable:
        def poster(url: str, payload):
            if "keywords_data/google_ads" not in (url or ""):
                return send(url, payload)
            if self.spent + ADS_CALL_USD > self.cap + 1e-9:
                message = (
                    f"Ads API stopped at ${self.spent:.2f} of the ${self.cap:.2f} cap. "
                    f"The next call would cost ${ADS_CALL_USD:.2f}."
                )
                print(
                    f"[gbp] ads error {message} calls={self.calls} spent={self.spent:.2f}",
                    flush=True,
                )
                raise AdsBudgetExceeded(message)
            body = send(url, payload)
            cost = _ads_task_cost(body)
            if cost is None:
                cost = ADS_CALL_USD
            phrases_in = _ads_phrases_in(payload)
            phrases_out = len(parse_keyword_items(body)) if isinstance(body, dict) else 0
            self.calls += 1
            self.spent = round(self.spent + float(cost), 4)
            endpoint = [part for part in (url or "").rstrip("/").split("/") if part][-2:]
            print(
                f"[gbp] ads call={self.calls} endpoint={'/'.join(endpoint)} "
                f"phrases_in={phrases_in} phrases_out={phrases_out} "
                f"cost={cost} spent={self.spent:.2f} cap={self.cap:.2f}",
                flush=True,
            )
            return body

        return poster


def _ads_task_cost(body) -> float | None:
    if not isinstance(body, dict):
        return None
    tasks = body.get("tasks") or []
    task = tasks[0] if tasks and isinstance(tasks[0], dict) else {}
    raw = task.get("cost") if task.get("cost") is not None else body.get("cost")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _ads_phrases_in(payload) -> int:
    rows = payload if isinstance(payload, list) else [payload]
    count = 0
    for row in rows:
        if isinstance(row, dict):
            count += len(row.get("keywords") or [])
    return count

_QUESTION = ("how ", "what ", "why ", "when ", "where ", "who ", "can ", "is ", "does ", "do ")
_BAN_MARKERS = ("do not", "don't", "dont", "ignore", "never", "no ", "not ")


def topics_have_saved_scores(topics: list[dict]) -> bool:
    return any(
        isinstance(topic, dict) and (topic.get("recommendation_saved_at") or topic.get("recommendation_score") is not None)
        for topic in topics or []
    )


def top_topics(topics: list[dict], limit: int = 15) -> list[dict]:
    rows = [topic for topic in topics or [] if isinstance(topic, dict) and (topic.get("text") or topic.get("name") or topic.get("title"))]
    rows.sort(key=lambda topic: (-float(topic.get("recommendation_score") or 0), str(topic.get("text") or "").lower()))
    return rows[:limit]


def _topic_text(topic: dict) -> str:
    return re.sub(r"\s+", " ", str(topic.get("text") or topic.get("name") or topic.get("title") or "")).strip()


def already_a_service(text: str, services: list[str]) -> bool:
    low = text.lower().strip()
    if not low:
        return True
    for name in services or []:
        service = re.sub(r"\s+", " ", str(name or "")).strip().lower()
        if not service:
            continue
        if low == service or low in service or service in low:
            return True
        tokens = _tokens(text)
        if tokens and all(token in service for token in tokens):
            return True
    return False


def seeds_from_topics(topics: list[dict], services: list[str], *, limit: int = 15) -> tuple[list[str], str]:
    """Return (seed phrases, error). Error is set when recommendation scores were never saved."""
    if not topics_have_saved_scores(topics):
        return [], "Save recommendation scores in Settings before Optimize can choose searches."
    seeds = []
    seen = set()
    for topic in top_topics(topics, limit):
        text = _topic_text(topic)
        if not text or already_a_service(text, services):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        seeds.append(text)
    return seeds, ""


def resolve_ads_location(locality: str) -> tuple[str, bool]:
    """Return the DataForSEO location name and whether it is only the country.

    Google Ads does not accept a bare city such as "Gurugram,India".
    A match looks like "Gurugram,Gurugram,Haryana,India".
    """
    place = re.sub(r"\s+", " ", locality or "").strip()
    if not place:
        return "India", True
    try:
        rows = _india_locations()
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] location lookup failed: {exc}", flush=True)
        return "India", True
    low = place.lower()
    for item in rows:
        name = item.get("location_name") or ""
        if item.get("location_type") != "City":
            continue
        if name.lower().startswith(low + ","):
            return name, False
    return "India", True


def _india_locations() -> list[dict]:
    global _LOCATION_CACHE
    if _LOCATION_CACHE is not None:
        return _LOCATION_CACHE
    response = httpx.get(LOCATIONS_URL, headers={"Authorization": auth_header()}, timeout=60)
    body = response.json()
    rows = []
    for task in body.get("tasks") or []:
        rows.extend(task.get("result") or [])
    _LOCATION_CACHE = rows
    return rows


def localize_seed(seed: str, locality: str) -> str:
    """Add the city only when the phrase does not already name a place and is not a question."""
    text = re.sub(r"\s+", " ", seed or "").strip()
    place = re.sub(r"\s+", " ", locality or "").strip()
    if not text or not place:
        return text
    if place.lower() in text.lower():
        return text
    if text.lower().startswith(_QUESTION):
        return text
    return f"{text} {place}"


def _volume(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return number


def parse_keyword_items(body: dict) -> list[dict]:
    rows = []
    for task in body.get("tasks") or []:
        for result in task.get("result") or []:
            items = result if isinstance(result, list) else (result.get("items") or result.get("keywords") or [])
            if isinstance(result, dict) and not items and result.get("keyword"):
                items = [result]
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                keyword = re.sub(r"\s+", " ", str(item.get("keyword") or "")).strip()
                if not keyword:
                    continue
                volume = _volume(item.get("search_volume"))
                if volume is None:
                    months = [
                        _volume(month.get("search_volume"))
                        for month in (item.get("monthly_searches") or [])
                        if isinstance(month, dict)
                    ]
                    months = [value for value in months if isinstance(value, int)]
                    if months:
                        volume = round(sum(months) / len(months))
                rows.append(
                    {
                        "keyword": keyword,
                        "volume": volume,
                        "competition": item.get("competition"),
                    }
                )
    return rows


def discover_keywords(seeds: list[str], *, location_name: str, poster: Callable | None = None) -> list[dict]:
    """Call keywords_for_keywords. `poster` is injectable in tests."""
    send = poster or post_json
    cleaned = []
    seen = set()
    for seed in seeds:
        text = re.sub(r"\s+", " ", seed or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    if not cleaned:
        return []
    found = []
    for offset in range(0, len(cleaned), 20):
        batch = cleaned[offset : offset + 20]
        try:
            body = send(
                KEYWORDS_URL,
                [
                    {
                        "keywords": batch,
                        "location_name": location_name,
                        "language_code": "en",
                        "sort_by": "search_volume",
                    }
                ],
            )
        except AdsBudgetExceeded:
            if found:
                print(
                    f"[gbp] ads stopped with {len(found)} phrases; {len(cleaned) - offset} seeds were not expanded",
                    flush=True,
                )
                break
            raise
        found.extend(parse_keyword_items(body))
    return found


def enrich_volumes(rows: list[dict], *, location_name: str, poster: Callable | None = None) -> list[dict]:
    missing = [row["keyword"] for row in rows if row.get("volume") is None and row.get("keyword")]
    if not missing:
        return rows
    send = poster or post_json
    volumes = {}
    for offset in range(0, len(missing), 1000):
        body = send(
            VOLUME_URL,
            [{"keywords": missing[offset : offset + 1000], "location_name": location_name, "language_code": "en"}],
        )
        for item in parse_keyword_items(body):
            volumes[item["keyword"].lower()] = item.get("volume")
    enriched = []
    for row in rows:
        if row.get("volume") is None:
            row = {**row, "volume": volumes.get(row["keyword"].lower())}
        enriched.append(row)
    return enriched


def _intent_points(keyword: str) -> int:
    low = keyword.lower()
    if low.startswith(_QUESTION) or "?" in keyword:
        return 0
    if "near me" in low or "clinic" in low or "doctor" in low or "hospital" in low:
        return 50
    return 30


def _priority(row: dict) -> float:
    volume = row.get("volume")
    volume_points = 0 if volume is None else min(20.0, math.log10(int(volume) + 1) * 8)
    return _intent_points(row.get("keyword") or "") + volume_points


def _reported_keys(reported: list[str]) -> set[str]:
    return {re.sub(r"\s+", " ", item or "").strip().lower() for item in reported if item}


def _parse_note(note: str) -> tuple[list[str], list[str]]:
    """Return (focus terms, banned terms) from a short user note."""
    text = re.sub(r"\s+", " ", note or "").strip().lower()
    if not text:
        return [], []
    focus = []
    banned = []
    for part in re.split(r"[.;]", text):
        piece = part.strip()
        if not piece:
            continue
        if any(marker in piece for marker in _BAN_MARKERS):
            banned.extend(_tokens(piece))
        else:
            focus.extend(_tokens(piece))
    return focus, banned


def _blocked(keyword: str, banned: list[str]) -> bool:
    low = keyword.lower()
    return any(term in low for term in banned)


def _focused(keyword: str, focus: list[str]) -> bool:
    if not focus:
        return False
    low = keyword.lower()
    return any(term in low for term in focus)


def pick_gap_keywords(
    candidates: list[dict],
    reported: list[str],
    *,
    note: str = "",
    limit: int = 10,
) -> dict:
    """Pick up to 10 phrases that are not in the GBP keyword report."""
    known = _reported_keys(reported)
    focus, banned = _parse_note(note)
    pool = []
    seen = set()
    unused = []
    for row in candidates or []:
        keyword = re.sub(r"\s+", " ", str(row.get("keyword") or "")).strip()
        key = keyword.lower()
        if not keyword or key in seen:
            continue
        seen.add(key)
        if key in known:
            continue
        if _blocked(keyword, banned):
            continue
        pool.append(
            {
                "keyword": keyword,
                "volume": row.get("volume") if isinstance(row.get("volume"), int) else _volume(row.get("volume")),
                "service": row.get("service") or "",
                "competition": row.get("competition"),
                "in_gbp_report": False,
            }
        )
    if focus:
        for term in focus:
            if term and not any(term in row["keyword"].lower() for row in pool):
                unused.append(term)
    pool.sort(key=lambda row: (-_priority(row), row["keyword"].lower()))
    if not focus:
        chosen = pool[:limit]
    else:
        biased = [row for row in pool if _focused(row["keyword"], focus)]
        rest = [row for row in pool if row not in biased]
        chosen = biased[:5] + rest[:5]
        # If the note matches fewer than 5, fill from the normal ranking without duplicating.
        if len(chosen) < limit:
            have = {row["keyword"].lower() for row in chosen}
            for row in pool:
                if row["keyword"].lower() in have:
                    continue
                chosen.append(row)
                if len(chosen) >= limit:
                    break
        chosen = chosen[:limit]
    return {
        "keywords": chosen,
        "not_used": unused,
        "demand_is_country": False,
    }


_GENERIC = {
    "near",
    "doctor",
    "doctors",
    "clinic",
    "hospital",
    "specialist",
    "surgeon",
    "treatment",
    "surgery",
    "consultation",
    "care",
    "best",
    "top",
    "centre",
    "center",
    "medical",
    "patient",
    "patients",
    "service",
    "services",
    "male",
    "female",
    "high",
    "low",
}

_OTHER_CARE = (
    "homeopathic",
    "homeopathy",
    "homoeopathic",
    "homoeopathy",
    "ayurvedic",
    "ayurveda",
    "naturopath",
    "naturopathy",
    "unani",
    "siddha",
    "sidha",
)

_SCAN_THEME_CAP = 2
_FINAL_THEME_CAP = 2


def terms(value: str, extra_skip: set[str] | None = None) -> set[str]:
    """Words of 3+ characters. Abbreviations such as RIRS and BPH stay."""
    skip = _GENERIC | (extra_skip or set())
    found = set()
    for part in re.findall(r"[a-z0-9]+", (value or "").lower()):
        if len(part) >= 5 and part.endswith("s") and not part.endswith("ss"):
            part = part[:-1]
        if len(part) >= 3 and part not in skip:
            found.add(part)
    return found


def _stem(token: str) -> str:
    return token[:5]


def phrase_overlaps(left: str, right: str, *, locality: str = "") -> bool:
    skip = {locality.lower()} if locality else set()
    left_terms = terms(left, skip)
    right_terms = terms(right, skip)
    if left_terms and right_terms:
        return bool(left_terms & right_terms)
    low_left = (left or "").strip().lower()
    low_right = (right or "").strip().lower()
    return bool(low_left and low_right and (low_left in low_right or low_right in low_left))


def topic_matches_listing(text: str, services: list[str], category: str) -> bool:
    """A Settings topic is a seed only when it shares a word with this listing."""
    blob = " ".join([category or "", *[str(name or "") for name in services]])
    return phrase_overlaps(text, blob)


def _impression_rows(reported: list) -> list[dict]:
    rows = []
    for item in reported or []:
        if isinstance(item, dict):
            keyword = re.sub(r"\s+", " ", str(item.get("keyword") or "")).strip()
            try:
                impressions = int(item.get("impressions") or 0)
            except (TypeError, ValueError):
                impressions = 0
        else:
            keyword = re.sub(r"\s+", " ", str(item or "")).strip()
            impressions = 0
        if keyword:
            rows.append({"keyword": keyword, "impressions": impressions})
    return rows


def service_impressions(name: str, reported: list) -> int:
    """Sum Google query impressions that share a word with this service. No match is 0."""
    total = 0
    for row in _impression_rows(reported):
        if phrase_overlaps(name, row["keyword"]):
            total += row["impressions"]
    return total


def dedupe_equivalent_seeds(seeds: list[str]) -> list[str]:
    """Keep one phrase when two seeds are the same offering. Prefer the clearer name."""
    kept: list[str] = []
    for seed in seeds:
        seed_terms = terms(seed)
        next_kept = []
        skip = False
        for current in kept:
            current_terms = terms(current)
            same = bool(seed_terms and current_terms) and (
                seed_terms == current_terms
                or (len(seed_terms) == 1 and seed_terms <= current_terms)
                or (len(current_terms) == 1 and current_terms <= seed_terms)
            )
            if not same:
                next_kept.append(current)
                continue
            if len(seed) > len(current):
                continue
            skip = True
            next_kept.append(current)
        if not skip:
            next_kept.append(seed)
        kept = next_kept
    return kept


def select_seed_phrases(
    topics: list[dict],
    services: list[str],
    *,
    category: str = "",
    reported: list | None = None,
    volumes: dict | None = None,
    settings_limit: int = 10,
    service_limit: int = 10,
) -> dict:
    """Up to 10 listing-backed Settings topics plus up to 10 GBP services.

    Settings topics that do not match this listing are dropped. When the listing
    has more than 10 services, the extra slots go to services that are not already
    covered, then the lowest query impressions, then Ads volume. Unknown volume
    sorts as 0 and is not a displayed demand.
    """
    clean_services = []
    seen_services = set()
    for name in services or []:
        text = re.sub(r"\s+", " ", str(name or "")).strip()
        key = text.lower()
        if text and key not in seen_services:
            seen_services.add(key)
            clean_services.append(text)
    settings_seeds = []
    dropped = []
    if topics_have_saved_scores(topics):
        for topic in top_topics(topics, 40):
            text = _topic_text(topic)
            if not text:
                continue
            if not topic_matches_listing(text, clean_services, category):
                dropped.append(text)
                continue
            if any(text.lower() == seed.lower() for seed in settings_seeds):
                continue
            settings_seeds.append(text)
            if len(settings_seeds) >= settings_limit:
                break
    volume_map = {str(key).lower(): _volume(value) for key, value in (volumes or {}).items()}

    def sort_volume(name: str) -> int:
        value = volume_map.get(name.lower())
        return value if isinstance(value, int) else 0

    ranked = []
    for name in clean_services:
        covered = any(phrase_overlaps(name, seed) for seed in settings_seeds)
        ranked.append((name, covered, service_impressions(name, reported or []), sort_volume(name)))
    ranked.sort(key=lambda row: (row[1], row[2], -row[3], row[0].lower()))
    ordered = dedupe_equivalent_seeds([row[0] for row in ranked])
    if len(clean_services) > service_limit:
        chosen_services = ordered[:service_limit]
    else:
        chosen_services = ordered
    seeds = []
    seen = set()
    for text in settings_seeds + chosen_services:
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        seeds.append(text)
    seeds = dedupe_equivalent_seeds(seeds)[:20]
    error = ""
    if not seeds:
        error = "No confirmed services or matching topics to optimize."
        if topics and not topics_have_saved_scores(topics) and not clean_services:
            error = "Save recommendation scores in Settings before Optimize can choose searches."
    return {
        "seeds": seeds,
        "settings_seeds": settings_seeds,
        "service_seeds": chosen_services,
        "dropped_topics": dropped,
        "error": error,
    }


def settings_topic_fallback(topics: list[dict], *, limit: int = 10) -> list[str]:
    """Multi-word Settings topics when the model does not return seeds. No listing overlap check."""
    if not topics_have_saved_scores(topics):
        return []
    found = []
    for topic in top_topics(topics, 40):
        text = _topic_text(topic)
        if not text or len(text.split()) < 2 or text.lower().startswith(_QUESTION):
            continue
        if any(text.lower() == chosen.lower() for chosen in found):
            continue
        found.append(text)
        if len(found) >= limit:
            break
    return found


def fallback_service_seeds(
    services: list[str],
    settings_seeds: list[str],
    reported: list | None = None,
    *,
    limit: int = 10,
) -> list[str]:
    """Up to 10 profile services not already covered by Settings, then lowest GMB impressions.

    Ads volume is not used.
    """
    clean = []
    seen = set()
    for name in services or []:
        text = re.sub(r"\s+", " ", str(name or "")).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            clean.append(text)
    ranked = []
    for name in clean:
        covered = any(phrase_overlaps(name, seed) for seed in settings_seeds or [])
        ranked.append((name, covered, service_impressions(name, reported or [])))
    ranked.sort(key=lambda row: (row[1], row[2], row[0].lower()))
    ordered = dedupe_equivalent_seeds([row[0] for row in ranked if not row[1]])
    return ordered[:limit]


def classify_demand(
    *,
    city_volume: int | None,
    broader_volume: int | None,
    theme_has_demand: bool,
    city_name: str,
) -> dict:
    """Label demand without copying one phrase's number onto another, or turning a miss into zero."""
    if isinstance(city_volume, int):
        return {
            "volume": city_volume,
            "broader_volume": None,
            "demand_status": "measured",
            "demand_location": city_name or "",
        }
    if isinstance(broader_volume, int):
        return {
            "volume": None,
            "broader_volume": broader_volume,
            "demand_status": "broader",
            "demand_location": "India",
        }
    if theme_has_demand:
        return {
            "volume": None,
            "broader_volume": None,
            "demand_status": "theme",
            "demand_location": "",
        }
    return {
        "volume": None,
        "broader_volume": None,
        "demand_status": "unknown",
        "demand_location": "",
    }


def attach_theme_demand(rows: list[dict], *, city_name: str) -> list[dict]:
    """Mark an unmeasured phrase as a theme signal when a related phrase has demand."""
    anchors = [row.get("keyword") or "" for row in rows if row.get("demand_status") in {"measured", "broader"}]
    labeled = []
    for row in rows:
        if row.get("demand_status") != "unknown":
            labeled.append(row)
            continue
        related = any(phrase_overlaps(row.get("keyword") or "", anchor) for anchor in anchors)
        if not related:
            labeled.append(row)
            continue
        labeled.append(
            {
                **row,
                **classify_demand(
                    city_volume=None,
                    broader_volume=None,
                    theme_has_demand=True,
                    city_name=city_name,
                ),
            }
        )
    return labeled


def _log_demand_points(volume: int | None, known: list[int], *, cap: float = 20) -> float | None:
    if not isinstance(volume, int):
        return None
    logs = [math.log10(value + 1) for value in known if value >= 0]
    if not logs:
        return 0
    top = max(logs) or 1
    return min(cap, (math.log10(volume + 1) / top) * cap)


def local_intent_points(keyword: str, locality: str = "") -> int:
    low = (keyword or "").lower()
    if low.startswith(_QUESTION) or "?" in keyword:
        return 0
    if any(mark in low for mark in ("near me", "clinic", "hospital", "doctor", "specialist", "surgeon")):
        return 30
    if locality and locality.lower() in low:
        return 30
    if any(mark in low for mark in ("treatment", "surgery", "consultation")):
        return 22
    return 12


def relevance_points(keyword: str, seeds: list[str], *, category: str = "", locality: str = "") -> int:
    skip = {locality.lower()} if locality else set()
    keyword_terms = terms(keyword, skip)
    if not keyword_terms:
        return 0
    best = 0
    for seed in seeds:
        seed_terms = terms(seed, skip)
        if not seed_terms:
            continue
        if seed_terms <= keyword_terms or keyword_terms <= seed_terms:
            best = max(best, 50)
        elif seed_terms & keyword_terms:
            best = max(best, 28)
    category_terms = terms(category, skip)
    if best == 0 and category_terms and (category_terms & keyword_terms):
        best = 20
    return best


def is_other_brand(keyword: str, *, business_name: str, seeds: list[str], category: str) -> bool:
    low = (keyword or "").lower()
    if business_name and business_name.lower() in low:
        return False
    if re.search(r"\bdr\b", low):
        return True
    allowed = terms(business_name) | terms(category)
    for seed in seeds:
        allowed |= terms(seed)
    allowed |= {"urology", "urologist", "cardiology", "cardiologist", "dental", "dentist", "hospital", "clinic"}
    match = re.search(r"\b([a-z]{3,})\s+hospital\b", low)
    if match and match.group(1) not in allowed and _stem(match.group(1)) not in {_stem(token) for token in allowed}:
        return True
    return False


def anchored_to_seeds(keyword: str, seeds: list[str], *, category: str, business_name: str, locality: str = "") -> bool:
    skip = {locality.lower()} if locality else set()
    anchors = set()
    for source in [*seeds, category, business_name]:
        for token in terms(source, skip):
            anchors.add(token)
            anchors.add(_stem(token))
    words = terms(keyword, skip)
    return any(word in anchors or _stem(word) in anchors for word in words)


def pre_serp_keyword_score(row: dict, *, known_volumes: list[int]) -> float:
    relevance = float(row.get("relevance") or 0)
    intent = float(row.get("local_intent") or 0)
    status = row.get("demand_status") or "unknown"
    if status == "measured":
        demand = _log_demand_points(row.get("volume"), known_volumes) or 0
    elif status == "broader":
        demand = (_log_demand_points(row.get("broader_volume"), known_volumes) or 0) * 0.6
    elif status == "theme":
        demand = 8
    else:
        demand = 10
    focus_bonus = 8 if row.get("focused") else 0
    return relevance + intent + demand + focus_bonus


def _strip_variant_noise(value: str) -> str:
    """Remove stone-size, language, and 'without surgery' leftovers so variants collapse."""
    text = re.sub(r"\d+\s*-?\s*mm\b", " ", value or "", flags=re.I)
    text = re.sub(r"\b\d+\b", " ", text)
    text = re.sub(r"\b(in\s+)?(hindi|english|tamil|telugu|kannada|marathi)\b", " ", text, flags=re.I)
    text = re.sub(r"\bwithout\s+surgery\b", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def near_duplicate(left: str, right: str, *, locality: str = "") -> bool:
    skip = {locality.lower()} if locality else set()
    left_terms = terms(_strip_variant_noise(left), skip)
    right_terms = terms(_strip_variant_noise(right), skip)
    if not left_terms or not right_terms:
        return (left or "").strip().lower() == (right or "").strip().lower()
    return left_terms <= right_terms or right_terms <= left_terms


def is_truncated_seed(keyword: str, seeds: list[str]) -> bool:
    """True when Ads dropped a distinctive seed word (tract infection vs urinary tract infection)."""
    key = (keyword or "").strip().lower()
    if not key:
        return False
    if any(key == (seed or "").strip().lower() for seed in seeds or []):
        return False
    keyword_terms = terms(keyword)
    if not keyword_terms:
        return False
    for seed in seeds or []:
        seed_terms = terms(seed)
        if keyword_terms < seed_terms:
            return True
    return False


def unsuitable_reason(keyword: str, seeds: list[str], *, category: str = "") -> str:
    """Why a phrase should never be scanned. Empty means keep it."""
    low = (keyword or "").lower()
    blob = " ".join([category or "", *[str(seed or "") for seed in seeds or []]]).lower()
    for word in _OTHER_CARE:
        if word in low and word not in blob:
            return "other_modality"
    if is_truncated_seed(keyword, seeds):
        return "truncated_seed"
    return ""


def drop_unsuitable(rows: list[dict], seeds: list[str], *, category: str = "") -> tuple[list[dict], list[dict]]:
    kept = []
    dropped = []
    for row in rows or []:
        keyword = row.get("keyword") or row.get("phrase") or ""
        reason = unsuitable_reason(keyword, seeds, category=category)
        if reason:
            dropped.append({"keyword": keyword, "reason": reason})
            continue
        kept.append(row)
    return kept, dropped


def theme_of(keyword: str, seeds: list[str], *, locality: str = "") -> str:
    best = ""
    best_overlap = 0
    for seed in seeds:
        overlap = len(terms(keyword, {locality.lower()} if locality else set()) & terms(seed))
        if overlap > best_overlap:
            best_overlap = overlap
            best = seed
    return best or keyword


def select_scan_keywords(
    candidates: list[dict],
    seeds: list[str],
    *,
    locality: str = "",
    category: str = "",
    business_name: str = "",
    note: str = "",
    limit: int = 20,
) -> dict:
    """Score candidates out of 100 and keep up to 20 diverse phrases. Do not pad."""
    focus, banned = _parse_note(note)
    pool = []
    seen = set()
    unused = []
    for row in candidates or []:
        keyword = re.sub(r"\s+", " ", str(row.get("keyword") or "")).strip()
        key = keyword.lower()
        if not keyword or key in seen:
            continue
        seen.add(key)
        if keyword.lower().startswith(_QUESTION) or "?" in keyword:
            continue
        if _blocked(keyword, banned):
            continue
        if is_other_brand(keyword, business_name=business_name, seeds=seeds, category=category):
            continue
        if not anchored_to_seeds(keyword, seeds, category=category, business_name=business_name, locality=locality):
            continue
        if unsuitable_reason(keyword, seeds, category=category):
            continue
        relevance = relevance_points(keyword, seeds, category=category, locality=locality)
        if relevance <= 0:
            continue
        intent = local_intent_points(keyword, locality)
        if intent <= 0:
            continue
        pool.append(
            {
                "keyword": keyword,
                "volume": row.get("volume") if isinstance(row.get("volume"), int) else None,
                "broader_volume": row.get("broader_volume") if isinstance(row.get("broader_volume"), int) else None,
                "demand_status": row.get("demand_status") or "unknown",
                "demand_location": row.get("demand_location") or "",
                "relevance": relevance,
                "local_intent": intent,
                "focused": _focused(keyword, focus),
                "theme": theme_of(keyword, seeds, locality=locality),
                "service": row.get("service") or theme_of(keyword, seeds, locality=locality),
            }
        )
    if focus:
        for term in focus:
            if term and not any(term in row["keyword"].lower() for row in pool):
                unused.append(term)
    known = []
    for row in pool:
        if row["demand_status"] == "measured" and isinstance(row["volume"], int):
            known.append(row["volume"])
        elif row["demand_status"] == "broader" and isinstance(row["broader_volume"], int):
            known.append(row["broader_volume"])
    for row in pool:
        row["pre_serp_score"] = round(pre_serp_keyword_score(row, known_volumes=known), 2)
    pool.sort(key=lambda row: (-row["pre_serp_score"], row["keyword"].lower()))
    chosen = []
    theme_counts: dict[str, int] = {}

    def add(row: dict, cap: int) -> None:
        if any(near_duplicate(row["keyword"], current["keyword"], locality=locality) for current in chosen):
            return
        theme = row["theme"]
        if theme_counts.get(theme, 0) >= cap:
            return
        chosen.append(row)
        theme_counts[theme] = theme_counts.get(theme, 0) + 1

    seen_themes = set()
    for row in pool:
        if row["theme"] in seen_themes:
            continue
        seen_themes.add(row["theme"])
        add(row, _SCAN_THEME_CAP)
        if len(chosen) >= limit:
            break
    if len(chosen) < limit:
        for row in pool:
            add(row, _SCAN_THEME_CAP)
            if len(chosen) >= limit:
                break
    return {"keywords": chosen[:limit], "not_used": unused}


def select_final_keywords(
    scanned: list[dict],
    *,
    seeds: list[str] | None = None,
    locality: str = "",
    limit: int = 10,
    per_theme: int = _FINAL_THEME_CAP,
) -> list[dict]:
    """Keep the top opportunities without filling the list with one treatment's variants."""
    seeds = seeds or []
    ranked = sorted(
        scanned or [],
        key=lambda row: (-float(row.get("opportunity_score") or 0), (row.get("phrase") or "").lower()),
    )
    chosen: list[dict] = []
    counts: dict[str, int] = {}

    def theme_key(row: dict) -> str:
        return row.get("service") or theme_of(row.get("phrase") or "", seeds, locality=locality)

    def add(row: dict, cap: int) -> None:
        phrase = row.get("phrase") or ""
        if any(near_duplicate(phrase, current.get("phrase") or "", locality=locality) for current in chosen):
            return
        key = theme_key(row)
        if counts.get(key, 0) >= cap:
            return
        chosen.append(row)
        counts[key] = counts.get(key, 0) + 1

    for row in ranked:
        add(row, per_theme)
        if len(chosen) >= limit:
            break
    if len(chosen) < limit:
        for row in ranked:
            add(row, limit)
            if len(chosen) >= limit:
                break
    return chosen[:limit]
