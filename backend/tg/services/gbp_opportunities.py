"""Title and description written only after Maps evidence exists.

The model may explain. It does not choose ranks or search volume.
The title stays the real business name.
"""

from __future__ import annotations

import json
import re

from backend.tg.services.gbp_optimize import DESCRIPTION_MAX, DESCRIPTION_MIN, _section, overall_score


def runtime_prompt(instruction: str) -> str:
    """Extra user prompt for this Optimize run. Empty text adds nothing."""
    text = re.sub(r"\s+", " ", instruction or "").strip()
    if not text:
        return ""
    return "\nAdditional user prompt at runtime:\n" + text + "\nFollow this instruction for this run.\n"


def openai_json(prompt: str) -> dict:
    """One JSON object from the configured model. Empty when the key is missing or the call fails."""
    from backend.tg.config import settings

    if not (settings.OPENAI_API_KEY or "").strip():
        return {}
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
        raw = (response.choices[0].message.content or "").strip()
        data = json.loads(raw[raw.find("{") : raw.rfind("}") + 1] or "{}")
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] optimize model failed: {exc}", flush=True)
        return {}


def draft_profile_copy(packet: dict) -> dict:
    """Return title, description, and any note about a phrase the model was not allowed to invent."""
    from backend.tg.config import settings

    business_name = re.sub(r"\s+", " ", str(packet.get("business_name") or "")).strip()
    title = business_name
    fallback = _fallback_description(packet)
    if not (settings.OPENAI_API_KEY or "").strip():
        return {"title": title, "description": fallback, "error": ""}
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            reasoning_effort=(settings.OPENAI_REASONING_EFFORT or "medium").strip() or "medium",
            messages=[
                {"role": "system", "content": "You reply with JSON only."},
                {"role": "user", "content": _prompt(packet)},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        data = json.loads(raw[raw.find("{") : raw.rfind("}") + 1] or "{}")
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] optimize copy failed: {exc}", flush=True)
        return {"title": title, "description": fallback, "error": "A description draft could not be written."}
    description = re.sub(r"\s+", " ", str(data.get("description") or "")).strip()
    if len(description) < DESCRIPTION_MIN:
        description = fallback
    title = _acceptable_title(
        business_name,
        str(data.get("title") or ""),
        category=str(packet.get("category") or ""),
        locality=str(packet.get("locality") or ""),
    )
    return {"title": title, "description": description[:DESCRIPTION_MAX], "error": ""}


def _acceptable_title(business_name: str, suggestion: str, *, category: str, locality: str) -> str:
    """Keep the real name. Allow the true category or city, and reject keyword stuffing."""
    name = re.sub(r"\s+", " ", business_name or "").strip()
    suggested = re.sub(r"\s+", " ", suggestion or "").strip()
    if not name:
        return suggested[:80]
    if not suggested or name.lower() not in suggested.lower() or len(suggested) > 80:
        return name
    from backend.tg.services.keyword_research import terms

    extra = suggested.lower().replace(name.lower(), " ")
    allowed = terms(f"{name} {category} {locality}")
    allowed |= {"clinic", "hospital", "centre", "center", "dr", "doctor"}
    if any(token not in allowed for token in terms(extra)):
        return name
    return suggested


def _prompt(packet: dict) -> str:
    safe = {
        "business_name": packet.get("business_name") or "",
        "locality": packet.get("locality") or "",
        "current_description": packet.get("current_description") or "",
        "services": packet.get("services") or [],
        "category": packet.get("category") or "",
        "recommendations": [
            {
                "action": item.get("action"),
                "current_name": item.get("current_name") or "",
                "proposed_name": item.get("proposed_name") or "",
                "reason": item.get("reason") or "",
            }
            for item in (packet.get("recommendations") or [])[:12]
        ],
        "gaps": [
            {
                "phrase": row.get("phrase") or row.get("keyword"),
                "sentence": row.get("sentence"),
                "volume": row.get("volume"),
            }
            for row in (packet.get("keywords") or [])[:10]
        ],
    }
    return (
        "Write one Google Business Profile title and description for this clinic. "
        "Use only the facts below. Do not invent treatments, awards, or ranks. "
        "The title must keep the real business name. You may add the primary category or the city, and nothing else. "
        "Put search wording in the description, using the service recommendations and confirmed services. "
        "Do not mention homeopathy, ayurveda, stone sizes, language variants, or any phrase that is not a confirmed service. "
        "Keep the description under 700 characters. "
        + runtime_prompt(packet.get("instruction") or "")
        + 'Reply as JSON {"title": "...", "description": "..."}.\n'
        + json.dumps(safe, ensure_ascii=False)
    )


def _fallback_description(packet: dict) -> str:
    name = packet.get("business_name") or "This clinic"
    place = packet.get("locality") or ""
    services = [str(item) for item in (packet.get("services") or []) if item][:4]
    gaps = [str(row.get("phrase") or row.get("keyword") or "") for row in (packet.get("keywords") or []) if row][:2]
    bits = [name]
    if place:
        bits.append(f"in {place}")
    if services:
        bits.append("offers " + ", ".join(services))
    text = " ".join(bits).strip() + "."
    if gaps:
        text += " Patients also look for " + " and ".join(gaps) + "."
    current = re.sub(r"\s+", " ", str(packet.get("current_description") or "")).strip()
    if len(current) >= DESCRIPTION_MIN:
        return current[:DESCRIPTION_MAX]
    return text[:DESCRIPTION_MAX]


def projected_listing_score(audit: dict, *, description: str = "", added_services: list[str] | None = None) -> dict | None:
    """Return current and potential scores only when Apply would flip a real checklist row."""
    if not audit:
        return None
    sections = []
    changed = False
    added = [item.strip() for item in (added_services or []) if item and item.strip()]
    current_services = audit.get("services", {}).get("current") or []
    current_count = len(current_services)
    description_text = re.sub(r"\s+", " ", description or "").strip()
    for section in audit.get("sections") or []:
        checks = []
        for check in section.get("checks") or []:
            row = dict(check)
            if check.get("id") == "description" and not check.get("ok") and description_text:
                row["ok"] = True
                row["detail"] = "Description is on the listing."
                changed = True
            if check.get("id") == "count" and not check.get("ok") and current_count + len(added) >= 3:
                row["ok"] = True
                row["detail"] = f"{current_count + len(added)} listed."
                changed = True
            checks.append(row)
        sections.append(_section(section.get("id"), section.get("label"), checks))
    if not changed:
        return None
    potential = overall_score(sections)
    current = int(audit.get("score") or 0)
    if potential == current:
        return None
    return {"current": current, "potential": potential, "sections": sections}


def name_is_unclear(name: str) -> bool:
    """Short custom labels such as RCT or RIRS. Ordinary multi-word service names are clear."""
    words = [word for word in re.split(r"[\s/]+", name or "") if word]
    generic = {"treatment", "surgery", "consultation", "therapy", "evaluation", "care", "test", "tests"}
    distinctive = [word for word in words if word.lower() not in generic]
    if not distinctive:
        return True
    if len(distinctive) == 1 and len(distinctive[0]) <= 5:
        return True
    return all(len(word) <= 3 for word in distinctive)


def description_is_thin(text: str) -> bool:
    return len(re.sub(r"\s+", " ", text or "").strip()) < 40


def _coverage_strong(top10: int, valid: int) -> bool:
    return bool(valid) and (top10 / valid) >= 0.5


def decide_service_action(
    match: str,
    *,
    name_clear: bool = True,
    description_thin: bool = False,
    baseline: dict | None = None,
) -> dict:
    """Turn a match into ADD, KEEP, or REPLACE. The model does not choose this action.

    `baseline` is unused while Maps rank checks are paused.
    """
    del baseline
    if match == "not_service":
        return {"action": "SKIP", "rename": False, "reason": "This search is looking for a provider, not a service name."}
    if match != "same":
        return {"action": "ADD", "rename": False, "reason": "This is not on the Google service list."}
    if not name_clear:
        return {
            "action": "REPLACE",
            "rename": True,
            "reason": "The current name is a short code or a truncation. The fuller service line should replace it.",
        }
    if description_thin:
        return {
            "action": "KEEP",
            "rename": False,
            "reason": "The service name is already clear. Fill the description and leave the name.",
        }
    return {
        "action": "KEEP",
        "rename": False,
        "reason": "The existing service already uses a clear name. A search variant is not a reason to replace it.",
    }


def _service_descriptions(location_services: list) -> dict[str, str]:
    found = {}
    for item in location_services or []:
        if isinstance(item, dict):
            name = item.get("displayName") or item.get("name") or ""
            description = item.get("description") or ""
        else:
            name, description = str(item or ""), ""
        if name:
            found[name.strip().lower()] = description or ""
    return found


def _best_service(keyword: str, services: list[str], *, locality: str = "") -> tuple[str, str]:
    from backend.tg.services.keyword_research import terms

    skip = {locality.lower()} if locality else set()
    keyword_terms = terms(keyword, skip)
    best_name = ""
    best_score = 0.0
    for name in services:
        service_terms = terms(name, skip)
        if not keyword_terms or not service_terms:
            continue
        overlap = keyword_terms & service_terms
        if not overlap:
            continue
        score = len(overlap) / min(len(keyword_terms), len(service_terms))
        if score > best_score:
            best_score = score
            best_name = name
    if best_score >= 0.6:
        return "same", best_name
    if best_score > 0:
        return "related", best_name
    return "none", ""


def _provider_search(keyword: str, category: str, locality: str = "") -> bool:
    from backend.tg.services.keyword_research import terms

    skip = {locality.lower(), "gurgaon", "gurugram", "delhi", "noida", "india", "jaipur"}
    words = terms(keyword, skip)
    category_terms = terms(category, skip)
    return bool(words and category_terms and words <= category_terms)


def prefer_listed_name(concept: str, services: list[str], *, locality: str = "") -> str:
    """Never keep a truncated Ads leftover when a listed service already names the offering."""
    from backend.tg.services.keyword_research import terms

    skip = {locality.lower()} if locality else set()
    concept_terms = terms(concept, skip)
    if not concept_terms:
        return concept
    best = concept
    best_len = len(concept or "")
    for name in services or []:
        service_terms = terms(name, skip)
        if concept_terms <= service_terms and len(name) >= best_len:
            best = name
            best_len = len(name)
    return best


def _concept_name(keyword: str, seeds: list[str], services: list[str], *, locality: str = "") -> str:
    from backend.tg.services.keyword_research import terms

    skip = {locality.lower()} if locality else set()
    best = ""
    best_overlap = 0
    for source in [*services, *seeds]:
        overlap = len(terms(keyword, skip) & terms(source, skip))
        if overlap > best_overlap:
            best_overlap = overlap
            best = source
    return best or keyword


def build_service_recommendations(
    keywords: list[dict],
    services: list[str],
    *,
    category: str = "",
    seeds: list[str] | None = None,
    business_name: str = "",
    locality: str = "",
    service_descriptions: dict | None = None,
    baselines: dict | None = None,
    hints: dict | None = None,
) -> list[dict]:
    """One row per service concept. Actions come from decide_service_action, not from the model."""
    seeds = seeds or []
    descriptions = {str(key).lower(): value for key, value in (service_descriptions or {}).items()}
    del baselines
    groups: dict[str, dict] = {}
    for row in keywords or []:
        keyword = row.get("phrase") or row.get("keyword") or ""
        if not keyword:
            continue
        hint = (hints or {}).get(keyword.lower()) if keyword else None
        if hint and hint.get("match") in {"same", "related", "none", "not_service", "uncertain"}:
            match = hint["match"]
            current = str(hint.get("current_service") or "")
            if current and not any(current.lower() == name.lower() for name in services):
                current = ""
                if match == "same":
                    match = "none"
            concept = str(hint.get("concept") or current or "")
        elif _provider_search(keyword, category, locality):
            match, current = "not_service", ""
            concept = ""
        else:
            match, current = _best_service(keyword, services, locality=locality)
            concept = current or _concept_name(keyword, seeds, services, locality=locality)
            if match == "related":
                seed_name = _concept_name(keyword, seeds, [], locality=locality)
                if seed_name and not any(seed_name.lower() == name.lower() for name in services):
                    concept = seed_name
                    current = ""
                    match = "none"
                elif current:
                    match = "same"
            if match == "none" and any(concept.lower() == name.lower() for name in services):
                match, current = "same", concept
        concept = prefer_listed_name(concept or current or keyword, services, locality=locality)
        if not current:
            for name in services:
                if name.lower() == (concept or "").lower():
                    current = name
                    if match == "none":
                        match = "same"
                    break
        key = (current or concept or keyword).lower()
        group = groups.setdefault(key, {"keywords": [], "match": match, "current": current, "concept": concept})
        group["keywords"].append(row)
        if match == "same" and group["match"] != "same":
            group["match"] = match
            group["current"] = current
    recommendations = []
    for group in groups.values():
        if group["match"] == "not_service":
            continue
        current = group["current"]
        concept = group["concept"] or current
        description = descriptions.get((current or "").lower(), "")
        thin = description_is_thin(description)
        clear = True if not current else not name_is_unclear(current)
        decision = decide_service_action(group["match"], name_clear=clear, description_thin=thin)
        if decision["action"] in {"SKIP", "KEEP"}:
            continue
        rename = decision["rename"]
        lead = group["keywords"][0]
        keyword_name = lead.get("phrase") or lead.get("keyword") or ""
        if decision["action"] == "ADD":
            proposed = concept or keyword_name
        elif decision["action"] == "REPLACE":
            proposed = concept if concept and concept.lower() != (current or "").lower() else keyword_name
        else:
            proposed = current or concept
        recommendations.append(
            {
                "action": decision["action"],
                "rename": rename,
                "current_name": current,
                "proposed_name": proposed,
                "proposed_description": "",
                "reason": decision["reason"],
                "why": "",
                "volume": lead.get("volume"),
                "broader_volume": lead.get("broader_volume"),
                "demand_status": lead.get("demand_status") or "",
                "demand_location": lead.get("demand_location") or "",
                "keywords": [item.get("phrase") or item.get("keyword") for item in group["keywords"]],
                "needs_protection": False,
            }
        )
    order = {"ADD": 0, "REPLACE": 1, "KEEP": 2}
    recommendations.sort(key=lambda item: (order.get(item["action"], 9), item.get("proposed_name") or ""))
    return recommendations


def apply_projection(audit: dict, projection: dict) -> dict:
    updated = dict(audit)
    updated["score"] = projection["potential"]
    updated["sections"] = projection["sections"]
    return updated
