"""Google Maps sample points, rank matching, and customer-facing sentences.

One keyword has 17 results. The table sentence is about the clinic and the 2 km ring.
"""

from __future__ import annotations

import math
import re

EARTH_KM = 6371.0
RADII_KM = (2, 6, 12, 18)
BEARINGS = (("north", 0), ("east", 90), ("south", 180), ("west", 270))

SENTENCES = {
    "strong": "People searching this near your clinic usually see you in the first few results.",
    "close": "You appear for this near your clinic, but other clinics are listed above you.",
    "buried": "You appear for this near your clinic, but quite far down the list.",
    "missing": "People searching this near your clinic are not seeing you in the first 20 results. Other clinics are showing instead.",
    "far": "You show up near your clinic. Farther away (about 12–18 km), people usually see other clinics first. That is mostly distance.",
    "failed": "We could not check this search this time. Try Optimize again.",
}


def ring_points(lat: float, lng: float) -> list[dict]:
    points = [{"id": "clinic", "km": 0, "direction": "clinic", "lat": float(lat), "lng": float(lng)}]
    for km in RADII_KM:
        for name, bearing in BEARINGS:
            dest_lat, dest_lng = _offset(float(lat), float(lng), km, bearing)
            points.append({"id": f"{km}-{name}", "km": km, "direction": name, "lat": dest_lat, "lng": dest_lng})
    return points


def _offset(lat: float, lng: float, km: float, bearing_deg: float) -> tuple[float, float]:
    bearing = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lng1 = math.radians(lng)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(km / EARTH_KM) + math.cos(lat1) * math.sin(km / EARTH_KM) * math.cos(bearing)
    )
    lng2 = lng1 + math.atan2(
        math.sin(bearing) * math.sin(km / EARTH_KM) * math.cos(lat1),
        math.cos(km / EARTH_KM) - math.sin(lat1) * math.sin(lat2),
    )
    return round(math.degrees(lat2), 6), round(math.degrees(lng2), 6)


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def parse_maps_items(body: dict) -> list[dict]:
    items = []
    for task in body.get("tasks") or []:
        for result in task.get("result") or []:
            if not isinstance(result, dict):
                continue
            for item in result.get("items") or []:
                if not isinstance(item, dict):
                    continue
                kind = item.get("type") or ""
                paid = kind != "maps_search"
                rank = item.get("rank_group") or item.get("rank_absolute")
                try:
                    rank_number = int(rank) if rank is not None else None
                except (TypeError, ValueError):
                    rank_number = None
                rating = item.get("rating") if isinstance(item.get("rating"), dict) else {}
                items.append(
                    {
                        "type": kind,
                        "paid": paid,
                        "rank": rank_number,
                        "title": item.get("title") or "",
                        "place_id": item.get("place_id") or "",
                        "category": item.get("category") or "",
                        "rating": rating.get("value"),
                        "reviews": rating.get("votes_count"),
                        "phone": item.get("phone") or "",
                        "lat": item.get("latitude"),
                        "lng": item.get("longitude"),
                    }
                )
    return items


def match_client_rank(items: list[dict], *, place_id: str, name: str, phone: str, lat: float | None, lng: float | None) -> dict:
    """Match organic maps_search rows. Name-only matches are rejected."""
    organic = [item for item in items if not item.get("paid") and item.get("type") in {"", "maps_search"}]
    target = (place_id or "").strip()
    if target:
        for item in organic:
            if item.get("place_id") == target and item.get("rank"):
                return {"found": True, "rank": int(item["rank"]), "matched_by": "place_id", "error": ""}
        return {"found": False, "rank": None, "matched_by": "", "error": ""}
    phone_digits = _digits(phone)
    name_low = (name or "").strip().lower()
    for item in organic:
        same_phone = phone_digits and _digits(item.get("phone") or "") == phone_digits
        same_name = name_low and (item.get("title") or "").strip().lower() == name_low
        near = False
        if lat is not None and lng is not None and item.get("lat") is not None and item.get("lng") is not None:
            near = distance_km(float(lat), float(lng), float(item["lat"]), float(item["lng"])) <= 0.3
        if same_name and same_phone and near and item.get("rank"):
            return {"found": True, "rank": int(item["rank"]), "matched_by": "name_phone_geo", "error": ""}
    return {"found": False, "rank": None, "matched_by": "", "error": ""}


def competitors_from_items(items: list[dict], client_rank: int | None, *, place_id: str) -> list[dict]:
    rows = []
    for item in items:
        if item.get("paid") or not item.get("place_id"):
            continue
        if place_id and item.get("place_id") == place_id:
            continue
        rank = item.get("rank")
        if client_rank and rank and int(rank) >= int(client_rank):
            continue
        if not client_rank and rank and int(rank) > 10:
            continue
        rows.append(
            {
                "place_id": item.get("place_id"),
                "name": item.get("title") or "",
                "category": item.get("category") or "",
                "rating": item.get("rating"),
                "reviews": item.get("reviews"),
                "rank": rank,
            }
        )
    return rows


def _band(rank: int | None) -> str:
    if not rank:
        return "missing"
    if rank <= 3:
        return "strong"
    if rank <= 10:
        return "close"
    if rank <= 20:
        return "buried"
    return "missing"


def point_gap(point: dict) -> int | None:
    """Map one Maps observation to gap points. A failed request is not a rank."""
    if point.get("error"):
        return None
    if not point.get("found") or not point.get("rank"):
        return 100
    rank = int(point["rank"])
    if rank <= 10:
        return 0
    if rank <= 15:
        return 50
    if rank <= 20:
        return 80
    return 100


RING_WEIGHTS = ((0, 0.20), (2, 0.30), (6, 0.25), (12, 0.15), (18, 0.10))


def weighted_visibility_gap(points: list[dict]) -> float | None:
    """One 0–100 gap. Centre 20%, 2 km 30%, 6 km 25%, 12 km 15%, 18 km 10%.

    Errored points are left out. Weights are renormalized over rings that returned data.
    """
    groups: dict[int, list[int]] = {}
    for point in points or []:
        gap = point_gap(point)
        if gap is None:
            continue
        groups.setdefault(int(point.get("km") or 0), []).append(gap)
    if not groups:
        return None
    total = 0.0
    weight_sum = 0.0
    for km, weight in RING_WEIGHTS:
        if km not in groups:
            continue
        average = sum(groups[km]) / len(groups[km])
        total += average * weight
        weight_sum += weight
    if not weight_sum:
        return None
    return total / weight_sum


def top10_coverage(points: list[dict]) -> dict:
    valid = [point for point in points or [] if not point.get("error")]
    top = [point for point in valid if point.get("found") and point.get("rank") and int(point["rank"]) <= 10]
    return {"top10": len(top), "valid": len(valid)}


def sentence_for_gap(points: list[dict]) -> dict:
    """Customer sentence from the weighted gap, not from one ring alone."""
    gap = weighted_visibility_gap(points)
    clinic = next((point for point in points or [] if point.get("km") == 0), None)
    clinic_rank = clinic.get("rank") if clinic and clinic.get("found") and not clinic.get("error") else None
    if gap is None:
        return {"key": "failed", "sentence": SENTENCES["failed"], "clinic_rank": clinic_rank, "weighted_gap": None}
    far = [point_gap(point) for point in points or [] if point.get("km") in {12, 18}]
    far = [value for value in far if value is not None]
    centre_gap = point_gap(clinic) if clinic else None
    far_gap = sum(far) / len(far) if far else None
    if centre_gap == 0 and far_gap is not None and far_gap >= 50:
        key = "far"
    elif gap <= 10:
        key = "strong"
    elif gap <= 35:
        key = "close"
    elif gap <= 60:
        key = "buried"
    else:
        key = "missing"
    sentence = SENTENCES[key]
    if key in {"close", "buried"} and clinic_rank:
        sentence = f"{sentence} At your clinic you were {_ordinal(clinic_rank)}."
    return {"key": key, "sentence": sentence, "clinic_rank": clinic_rank, "weighted_gap": round(gap, 2)}


def score_opportunity(
    *,
    weighted_gap: float | None,
    local_intent: float,
    demand_points: float,
    competitor_points: float,
    feasibility: float,
) -> float:
    """Final score out of 100. Visibility is 35% of a 0–100 gap."""
    visibility = 0 if weighted_gap is None else max(0.0, min(100.0, weighted_gap)) * 0.35
    intent = max(0.0, min(30.0, local_intent)) / 30 * 20
    return round(visibility + intent + demand_points + competitor_points + feasibility, 2)


def competitor_strength(points: list[dict]) -> float:
    """Up to 15 points when other businesses keep appearing above this clinic."""
    valid = [point for point in points or [] if not point.get("error")]
    if not valid:
        return 7.5
    hot = sum(1 for point in valid if point.get("competitors"))
    return round(15 * hot / len(valid), 2)


def feasibility_points(*, covered: bool, name_clear: bool, centre_rank: int | None, far_weak: bool) -> tuple[int, str]:
    """Fixed points. The caller writes the words; this only picks the number."""
    if centre_rank and centre_rank <= 10 and far_weak:
        return 3, "Ranking is weaker far from the clinic. That is mostly distance."
    if not covered:
        return 15, "The offering behind this search is not on the service list."
    if not name_clear:
        return 12, "The current service name is hard for a patient to understand."
    return 6, "This offering is already listed, so a rename is unlikely to be the fix."


def customer_sentence(points: list[dict]) -> dict:
    """Turn 17 point results into one sentence about nearby visibility."""
    clinic = next((point for point in points if point.get("km") == 0), None)
    near = [point for point in points if point.get("km") == 2]
    far = [point for point in points if point.get("km") in {12, 18}]
    watched = [point for point in [clinic, *near] if point]
    if not watched or any(point.get("error") for point in watched):
        return {"key": "failed", "sentence": SENTENCES["failed"], "clinic_rank": None}
    clinic_rank = clinic.get("rank") if clinic and clinic.get("found") else None
    near_ranks = [point.get("rank") if point.get("found") else None for point in near]
    nearby_missing = clinic_rank is None or sum(1 for rank in near_ranks if not rank) >= 3
    nearby_bands = [_band(clinic_rank)] + [_band(rank) for rank in near_ranks]
    far_weak = far and sum(1 for point in far if not point.get("found") or (point.get("rank") or 99) > 10) >= max(1, len(far) // 2)
    nearby_top10 = clinic_rank is not None and clinic_rank <= 10 and sum(1 for rank in near_ranks if rank and rank <= 10) >= 2
    if nearby_missing:
        key = "missing"
    elif nearby_top10 and far_weak and all(band in {"strong", "close"} for band in nearby_bands if band != "missing"):
        key = "far"
    elif clinic_rank and clinic_rank <= 3 and sum(1 for rank in near_ranks if rank and rank <= 3) >= 3:
        key = "strong"
    elif any(band == "buried" for band in nearby_bands):
        key = "buried"
    else:
        key = "close"
    sentence = SENTENCES[key]
    if key == "close" and clinic_rank:
        sentence = f"{sentence} At your clinic you were {_ordinal(clinic_rank)}."
    return {"key": key, "sentence": sentence, "clinic_rank": clinic_rank}


def _ordinal(number: int) -> str:
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def merge_competitors(points: list[dict]) -> list[dict]:
    found = {}
    for point in points:
        weight = 3 if point.get("km") == 0 else 2 if point.get("km") == 2 else 1
        for row in point.get("competitors") or []:
            key = row.get("place_id") or row.get("name")
            if not key:
                continue
            current = found.setdefault(
                key,
                {**row, "points": 0, "nearby_points": 0},
            )
            current["points"] += 1
            if point.get("km") in {0, 2}:
                current["nearby_points"] += weight
    rows = list(found.values())
    rows.sort(key=lambda row: (-int(row.get("nearby_points") or 0), -int(row.get("points") or 0), row.get("name") or ""))
    return rows[:8]


def phrase_fits_review(phrase: str, review: dict) -> bool:
    comment = (review.get("comment") or "").lower()
    if not comment or not phrase:
        return False
    tokens = _review_tokens(phrase)
    if not tokens:
        return False
    return any(token in comment or token.rstrip("s") in comment for token in tokens)


def _review_tokens(phrase: str) -> list[str]:
    skip = {"near", "clinic", "doctor", "best", "with", "from", "this", "that", "your"}
    return [part for part in re.findall(r"[a-z0-9]+", phrase.lower()) if len(part) > 3 and part not in skip]


def eligible_for_keyword(review: dict) -> bool:
    stars = str(review.get("starRating") or "")
    if stars in {"ONE", "1"}:
        return False
    text = (review.get("comment") or "").lower()
    angry = ("worst", "rude", "scam", "never again", "refund", "terrible", "horrible")
    return not any(term in text for term in angry)
