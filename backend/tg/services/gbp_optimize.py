"""Profile completeness score, keyword actions, and guarded AI drafts.

The score is our checklist. It is not a Google ranking.
"""

from __future__ import annotations

import json
import re
from datetime import date

PHOTO_EXPECTATIONS = (
    ("COVER", "Cover"),
    ("INTERIOR", "Interior"),
    ("TEAMS", "Team"),
    ("AT_WORK", "At work"),
)

DESCRIPTION_MIN = 80
SERVICE_MIN = 3
DESCRIPTION_MAX = 750

_STOP = {
    "clinic",
    "doctor",
    "doctors",
    "treatment",
    "treatments",
    "service",
    "services",
    "medical",
    "patient",
    "patients",
    "care",
    "health",
    "specialist",
    "consultation",
    "consult",
    "consults",
    "near",
    "with",
    "from",
    "that",
    "this",
    "your",
    "best",
}

_QUESTION_STARTS = ("how ", "what ", "why ", "when ", "where ", "who ", "can ", "is ", "does ", "do ")
_PLACES = {
    "gurgaon",
    "gurugram",
    "delhi",
    "noida",
    "mumbai",
    "bengaluru",
    "bangalore",
    "hyderabad",
    "pune",
    "chennai",
    "kolkata",
    "india",
    "haryana",
    "sector",
}
MEDIA_LABELS = {
    "COVER": "Cover",
    "PROFILE": "Profile",
    "LOGO": "Logo",
    "EXTERIOR": "Exterior",
    "INTERIOR": "Interior",
    "PRODUCT": "Product",
    "AT_WORK": "At work",
    "FOOD_AND_DRINK": "Food and drink",
    "MENU": "Menu",
    "COMMON_AREA": "Common area",
    "ROOMS": "Rooms",
    "TEAMS": "Team",
    "ADDITIONAL": "Additional",
}


def _text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokens(value: str, places: set[str] | None = None) -> list[str]:
    skip = _STOP | _PLACES | (places or set())
    return [part for part in re.findall(r"[a-z0-9]+", value.lower()) if len(part) > 3 and part not in skip]


def service_names(location: dict) -> list[str]:
    names = []
    for item in location.get("serviceItems") or []:
        label = ((item.get("freeFormServiceItem") or {}).get("label") or {})
        structured = item.get("structuredServiceItem") or {}
        name = _text(label.get("displayName") or structured.get("description") or structured.get("serviceTypeId"))
        if name:
            names.append(name)
    return names


def current_services(location: dict) -> list[dict]:
    rows = []
    for item in location.get("serviceItems") or []:
        label = ((item.get("freeFormServiceItem") or {}).get("label") or {})
        structured = item.get("structuredServiceItem") or {}
        name = _text(label.get("displayName") or structured.get("description") or "")
        if not name:
            continue
        rows.append({"displayName": name, "description": _text(label.get("description"))})
    return rows


def photo_categories(media: list[dict]) -> set[str]:
    found = set()
    for item in media or []:
        category = ((item.get("locationAssociation") or {}).get("category") or "").upper()
        if category:
            found.add(category)
    return found


def keyword_month_window(today: date) -> tuple[date, date]:
    """Three calendar months ending with the current month."""
    index = today.year * 12 + (today.month - 1) - 2
    year, month_index = divmod(index, 12)
    return date(year, month_index + 1, 1), today


def locality_of(location: dict) -> str:
    address = location.get("storefrontAddress") or {}
    return _text(address.get("locality"))


def _contains_name(keyword: str, business_name: str) -> bool:
    name = _text(business_name).lower()
    low = keyword.lower()
    if len(name) >= 3 and name in low:
        return True
    skip = _STOP | _PLACES | {"doctor", "clinic", "hospital", "centre", "center"}
    tokens = [part for part in re.findall(r"[a-z0-9]+", name) if len(part) > 3 and part not in skip]
    return any(token in low for token in tokens)


def classify_keyword(keyword: str, business_name: str, locality: str) -> str:
    text = _text(keyword)
    low = text.lower()
    if _contains_name(low, business_name):
        return "brand"
    if "near me" in low or (locality and locality.lower() in low):
        return "area"
    if "?" in text or low.startswith(_QUESTION_STARTS):
        return "question"
    return "service"


def _covered(keyword: str, description: str, services: list[str]) -> bool:
    blob = f"{description} {' '.join(services)}".lower()
    low = keyword.lower()
    if low and low in blob:
        return True
    tokens = _tokens(keyword)
    return bool(tokens) and all(token in blob for token in tokens)


def keyword_action(keyword: str, theme: str, description: str, services: list[str]) -> str:
    if theme == "question":
        return "post_idea"
    if theme == "brand" or _covered(keyword, description, services):
        return "already_covered"
    if theme == "service" and _tokens(keyword):
        return "suggest_service"
    return "already_covered"


_ACTION_LABELS = {
    "already_covered": "Already covered",
    "suggest_service": "Suggest as a service",
    "post_idea": "Post idea",
}


def keyword_rows(keywords: list[dict], *, business_name: str, locality: str, description: str, services: list[str]) -> list[dict]:
    rows = []
    for item in keywords or []:
        keyword = _text(item.get("keyword"))
        if not keyword:
            continue
        theme = classify_keyword(keyword, business_name, locality)
        action = keyword_action(keyword, theme, description, services)
        rows.append(
            {
                "keyword": keyword,
                "impressions": item.get("impressions") or 0,
                "theme": theme,
                "action": action,
                "action_label": _ACTION_LABELS[action],
            }
        )
    rows.sort(key=lambda row: row["impressions"], reverse=True)
    return rows


def keyword_service_ideas(rows: list[dict], existing: list[str]) -> list[dict]:
    """Turn an uncovered search into a service name. Location and name searches are skipped earlier."""
    existing_keys = {item.lower() for item in existing}
    ideas = []
    seen = set()
    for row in rows or []:
        if row.get("action") != "suggest_service":
            continue
        tokens = _tokens(row.get("keyword") or "")
        if not tokens:
            continue
        name = " ".join(token.capitalize() for token in tokens)
        key = name.lower()
        if key in existing_keys or key in seen or _covered(name, "", existing):
            continue
        seen.add(key)
        ideas.append(
            {
                "name": name[:120],
                "reason": "People searched for this, and it is not already a listed service.",
                "evidence": row.get("keyword") or "",
            }
        )
        if len(ideas) >= 8:
            break
    return ideas


def evidence_texts(*, specialty: str, client_description: str, topics: list, keywords: list[str]) -> list[str]:
    texts = [_text(specialty), _text(client_description)]
    for topic in topics or []:
        if isinstance(topic, dict):
            texts.append(_text(topic.get("text") or topic.get("name") or topic.get("title")))
        else:
            texts.append(_text(topic))
    texts.extend(_text(item) for item in keywords or [])
    return [item for item in texts if item]


def service_is_allowed(name: str, evidence: list[str]) -> bool:
    tokens = _tokens(name)
    if not tokens:
        return False
    blob = " ".join(evidence).lower()
    return all(token in blob for token in tokens)


def drop_add_already_listed(recommendations: list, listing: dict | None) -> list:
    """Hide ADD rows whose name is already on the live service list."""
    names = set()
    for item in (((listing or {}).get("services") or {}).get("current") or []):
        if isinstance(item, dict):
            name = str(item.get("displayName") or item.get("name") or "").strip().casefold()
        else:
            name = str(item or "").strip().casefold()
        if name:
            names.add(name)
    kept = []
    for item in recommendations or []:
        if not isinstance(item, dict):
            continue
        if item.get("action") == "ADD":
            proposed = str(item.get("proposed_name") or "").strip().casefold()
            if proposed and proposed in names:
                continue
        kept.append(item)
    return kept


def rewrite_service_list_detail(detail: str) -> str:
    """Keep old snapshots from saying 'this clinic actually offers'."""
    text = str(detail or "").strip()
    if "clinic actually offers" not in text.lower():
        return text
    count_part = text.split(".")[0].strip()
    if "listed" in count_part.lower():
        return f"{count_part}. Add more services to this listing."
    return "Add more services to this listing."


def soften_audit_listing(listing: dict) -> dict:
    if not isinstance(listing, dict) or not listing.get("sections"):
        return listing
    sections = []
    for section in listing.get("sections") or []:
        if not isinstance(section, dict):
            sections.append(section)
            continue
        checks = []
        for check in section.get("checks") or []:
            if not isinstance(check, dict):
                checks.append(check)
                continue
            checks.append({**check, "detail": rewrite_service_list_detail(check.get("detail") or "")})
        sections.append({**section, "checks": checks})
    return {**listing, "sections": sections}


def _section(section_id: str, label: str, checks: list[dict]) -> dict:
    passed = sum(1 for check in checks if check["ok"])
    score = round(100 * passed / len(checks)) if checks else 100
    return {"id": section_id, "label": label, "score": score, "checks": checks}


def checklist(
    location: dict,
    *,
    appointment_uri: str,
    appointment_error: str,
    media: list[dict],
    keywords: list[dict] | None = None,
) -> list[dict]:
    phone = _text((location.get("phoneNumbers") or {}).get("primaryPhone"))
    website = _text(location.get("websiteUri"))
    description = _text((location.get("profile") or {}).get("description"))
    hours = (location.get("regularHours") or {}).get("periods") or []
    primary = (location.get("categories") or {}).get("primaryCategory") or {}
    services = service_names(location)
    present = photo_categories(media)
    has_description = bool(description)

    business = [
        {"id": "phone", "ok": bool(phone), "title": "Phone number", "detail": phone or "Add the clinic phone number."},
        {"id": "website", "ok": bool(website), "title": "Website", "detail": website or "Add the clinic website."},
        {
            "id": "hours",
            "ok": bool(hours),
            "title": "Opening hours",
            "detail": "Hours are listed." if hours else "Add at least one open day.",
        },
        {
            "id": "description",
            "ok": has_description,
            "title": "Description",
            "detail": "Description is on the listing." if has_description else "Add a description.",
        },
        {
            "id": "appointment",
            "ok": bool(_text(appointment_uri)),
            "title": "Appointment link",
            "detail": appointment_uri or appointment_error or "Add the booking link patients should use.",
        },
    ]
    categories = [
        {
            "id": "primary",
            "ok": bool(primary.get("name")),
            "title": "Primary category",
            "detail": primary.get("displayName") or "Choose the category that best matches this clinic.",
        }
    ]
    service_checks = [
        {
            "id": "count",
            "ok": len(services) >= SERVICE_MIN,
            "title": "Service list",
            "detail": (
                f"{len(services)} listed."
                if len(services) >= SERVICE_MIN
                else f"{len(services)} listed. Add more services to this listing."
            ),
        },
    ]
    photos = []
    for key, label in PHOTO_EXPECTATIONS:
        found = key in present
        photos.append(
            {
                "id": key,
                "ok": found,
                "title": label,
                "detail": "On the listing." if found else f"Upload a real {label.lower()} photo on the Media page.",
            }
        )
    return [
        _section("business", "Business information", business),
        _section("categories", "Categories", categories),
        _section("services", "Services", service_checks),
        _section("photos", "Photos", photos),
    ]


def overall_score(sections: list[dict]) -> int:
    if not sections:
        return 0
    return round(sum(int(section.get("score") or 0) for section in sections) / len(sections))


def photo_gaps(media: list[dict]) -> dict:
    found = photo_categories(media)
    present = [{"id": key, "label": MEDIA_LABELS.get(key, key.replace("_", " ").title())} for key in sorted(found)]
    missing = [{"id": key, "label": label} for key, label in PHOTO_EXPECTATIONS if key not in found]
    return {"present": present, "missing": missing}


def cited_source(evidence: str, sources: list[str]) -> str:
    """Return the real source the model quoted. An invented sentence returns nothing."""
    raw = evidence or ""
    quoted = [_text(part) for part in re.findall(r'"([^"]+)"', raw)]
    quoted.extend(_text(part) for part in re.findall(r"'([^']+)'", raw))
    candidates = [item for item in quoted if item] or [_text(raw)]
    for candidate in candidates:
        low = candidate.lower()
        if len(low) < 3:
            continue
        for source in sources:
            source_low = source.lower()
            if low == source_low or low in source_low:
                return source
    return ""


def _parse_json(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def sanitize_service_suggestions(raw: list, *, evidence: list[str], existing: list[str]) -> list[dict]:
    existing_keys = {item.lower() for item in existing}
    kept = []
    seen = set()
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        key = name.lower()
        if not name or key in existing_keys or key in seen:
            continue
        if not service_is_allowed(name, evidence) or _covered(name, "", existing):
            continue
        source = cited_source(str(item.get("evidence") or ""), evidence)
        if not source:
            continue
        seen.add(key)
        kept.append(
            {
                "name": name[:120],
                "reason": _text(item.get("reason"))[:240],
                "evidence": source[:240],
            }
        )
        if len(kept) >= 8:
            break
    return kept


def sanitize_category_suggestion(raw: dict | None, hits: list[dict]) -> dict | None:
    if not isinstance(raw, dict):
        return None
    wanted = _text(raw.get("primary_name") or raw.get("name"))
    if not wanted:
        return None
    match = next((hit for hit in hits or [] if _text(hit.get("name")) == wanted), None)
    if not match:
        return None
    return {
        "name": match.get("name"),
        "displayName": match.get("displayName") or match.get("display_name") or match.get("name"),
        "reason": _text(raw.get("reason"))[:240],
    }


def profile_update_from_approval(
    *,
    description: str | None = None,
    services: list[dict] | None = None,
    primary_category: str | None = None,
    additional_categories: list[str] | None = None,
    service_category: str | None = None,
) -> tuple[list[str], dict]:
    """Build a profile patch that cannot rename the business or change the address."""
    mask: list[str] = []
    body: dict = {}
    if description is not None:
        mask.append("profile")
        body["profile"] = {"description": _text(description)[:DESCRIPTION_MAX]}
    if services is not None:
        mask.append("serviceItems")
        category = _text(service_category)
        items = []
        for item in services:
            name = _text(item.get("displayName") or item.get("name"))
            if not name:
                continue
            items.append(
                {
                    "freeFormServiceItem": {
                        "category": category,
                        "label": {
                            "displayName": name[:120],
                            "description": _text(item.get("description"))[:300],
                        },
                    }
                }
            )
        body["serviceItems"] = items
    if primary_category:
        mask.append("categories")
        body["categories"] = {
            "primaryCategory": {"name": primary_category},
            "additionalCategories": [{"name": name} for name in (additional_categories or []) if name],
        }
    return mask, body


def _draft_prompt(*, location, specialty, client_description, topics, keywords, category_hits) -> str:
    services = service_names(location)
    topic_lines = []
    for topic in topics or []:
        if isinstance(topic, dict):
            topic_lines.append(_text(topic.get("text")))
        else:
            topic_lines.append(_text(topic))
    hits = [
        {"name": hit.get("name"), "displayName": hit.get("displayName") or hit.get("display_name")}
        for hit in (category_hits or [])[:8]
        if hit.get("name")
    ]
    payload = {
        "business_name": location.get("title") or "",
        "locality": locality_of(location),
        "current_description": (location.get("profile") or {}).get("description") or "",
        "current_services": services,
        "specialty": specialty or "",
        "client_description": client_description or "",
        "topics": [item for item in topic_lines if item][:20],
        "search_keywords": [item.get("keyword") for item in (keywords or [])[:20] if item.get("keyword")],
        "category_choices": hits,
    }
    return (
        "You optimize a clinic Google Business Profile. Use only the facts in the JSON. "
        "Do not invent treatments, awards, or locations. Do not change or mention a new business name. "
        "Write a description under 700 characters that a patient can understand. "
        "Suggest services only when the name is supported by the specialty, client description, topics, or search keywords. "
        "Each service needs name, reason, and evidence quoting the source fact. "
        "If a category_choices name fits better than the current listing, set primary_name to that exact name. "
        "Otherwise set primary_name to an empty string. "
        "Reply as JSON with keys description, services, primary_name, reason.\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def request_profile_draft(**kwargs) -> tuple[dict, str]:
    """Return (parsed model JSON, error). Never raises for a missing or failed model call."""
    from backend.tg.config import settings

    if not (settings.OPENAI_API_KEY or "").strip():
        return {}, "A description draft could not be written because the AI key is not configured."
    prompt = _draft_prompt(**kwargs)
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            reasoning_effort=(settings.OPENAI_REASONING_EFFORT or "medium").strip() or "medium",
            messages=[
                {"role": "system", "content": "You reply with JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        return _parse_json(response.choices[0].message.content or ""), ""
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] profile draft failed: {exc}", flush=True)
        return {}, "A description draft could not be written."


def build_audit(
    *,
    location: dict,
    media: list[dict],
    appointment_uri: str = "",
    appointment_error: str = "",
    specialty: str = "",
    client_description: str = "",
    topics: list | None = None,
    keywords: list[dict] | None = None,
    keywords_error: str = "",
    category_hits: list[dict] | None = None,
    model_draft: dict | None = None,
    draft_error: str = "",
    pending: bool = False,
) -> dict:
    keywords = keywords or []
    services = service_names(location)
    description = _text((location.get("profile") or {}).get("description"))
    primary_category = (location.get("categories") or {}).get("primaryCategory") or {}
    coverage_text = " ".join(
        part
        for part in (description, location.get("title") or "", primary_category.get("displayName") or "")
        if part
    )
    sections = checklist(
        location,
        appointment_uri=appointment_uri,
        appointment_error=appointment_error,
        media=media,
        keywords=keywords,
    )
    evidence = evidence_texts(
        specialty=specialty,
        client_description=client_description,
        topics=topics or [],
        keywords=[item.get("keyword") or "" for item in keywords],
    )
    draft = model_draft or {}
    suggested = sanitize_service_suggestions(draft.get("services") or [], evidence=evidence, existing=services)
    rows = keyword_rows(
        keywords,
        business_name=location.get("title") or "",
        locality=locality_of(location),
        description=coverage_text,
        services=services,
    )
    seen_names = {item["name"].lower() for item in suggested}
    for idea in keyword_service_ideas(rows, services):
        if idea["name"].lower() in seen_names:
            continue
        suggested.append(idea)
        seen_names.add(idea["name"].lower())
    primary = primary_category
    additional = (location.get("categories") or {}).get("additionalCategories") or []
    suggestion_text = _text(draft.get("description"))[:DESCRIPTION_MAX]
    return {
        "score": overall_score(sections),
        "score_label": "Gravity completeness",
        "pending": bool(pending or (location.get("metadata") or {}).get("hasPendingEdits")),
        "sections": sections,
        "fields": {
            "phone": _text((location.get("phoneNumbers") or {}).get("primaryPhone")),
            "website": _text(location.get("websiteUri")),
            "appointment": _text(appointment_uri),
        },
        "description": {
            "current": description,
            "suggestion": suggestion_text,
            "error": "" if suggestion_text else (draft_error or "A description draft could not be written."),
        },
        "services": {
            "current": current_services(location),
            "primary_category": primary.get("name") or "",
            "suggested": suggested[:8],
        },
        "categories": {
            "primary": {"name": primary.get("name") or "", "displayName": primary.get("displayName") or ""},
            "additional": [
                {"name": item.get("name") or "", "displayName": item.get("displayName") or item.get("name") or ""}
                for item in additional
                if item.get("name")
            ],
            "suggestion": sanitize_category_suggestion(
                {"primary_name": draft.get("primary_name"), "reason": draft.get("reason")},
                category_hits or [],
            ),
        },
        "photos": photo_gaps(media),
        "keywords": rows,
        "keywords_error": keywords_error,
    }
