"""Review auto-reply decisions. Google has no auto-reply API; we publish via updateReply."""

from __future__ import annotations

from datetime import datetime, timezone

ANGRY_TERMS = (
    "angry",
    "rude",
    "worst",
    "scam",
    "fraud",
    "sue",
    "lawyer",
    "malpractice",
    "horrible",
    "disgusting",
    "never again",
    "terrible",
    "complaint",
    "refund",
    "liar",
)

STAR_MAP = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}

TREATMENT_TERMS = (
    "surgery",
    "surgical",
    "injection",
    "procedure",
    "operation",
    "operated",
    "prescription",
    "diagnosed",
    "diagnosis",
    "biopsy",
    "chemotherapy",
    "radiation",
    "implant",
    "transplant",
    "anesthesia",
)

SAFE_REVIEW_REPLY = (
    "Thank you for sharing this. We're sorry your experience wasn't what you hoped for. "
    "Please contact the clinic directly so the team can look into it."
)

THEME_RULES = (
    ("waiting_time", "Waiting time", ("wait", "waiting", "queue", "delayed", "delay", "long time")),
    ("doctor_communication", "Doctor communication", ("doctor", "dr.", "explained", "explain", "listen", "rude", "communication")),
    ("billing", "Billing", ("bill", "billing", "charge", "fee", "expensive", "cost", "payment", "refund")),
    ("front_desk", "Front desk", ("staff", "reception", "front desk", "receptionist", "appointment", "coordinator")),
)


def review_star(review: dict) -> int | None:
    rating = review.get("starRating")
    if isinstance(rating, str):
        if rating.isdigit():
            return int(rating)
        return STAR_MAP.get(rating.upper())
    if isinstance(rating, int):
        return rating
    return None


def classify_unanswered_review(review: dict, *, skip_one_star: bool, skip_angry: bool) -> str:
    """Return skip_one_star, skip_angry, or reply."""
    if review.get("reviewReply"):
        return "already_replied"
    if skip_one_star and review_star(review) == 1:
        return "skip_one_star"
    text = (review.get("comment") or "").lower()
    if skip_angry and any(term in text for term in ANGRY_TERMS):
        return "skip_angry"
    return "reply"


def auto_reply_action(mode: str, classification: str) -> str:
    """Return skip, draft, or publish."""
    if classification != "reply":
        return "skip"
    if mode == "human_review":
        return "draft"
    if mode == "fully_automatic":
        return "publish"
    return "skip"


def fallback_reply(review: dict, business_name: str) -> str:
    name = business_name or "our clinic"
    stars = review_star(review) or 0
    if stars and stars <= 3:
        return (
            f"Thank you for sharing this with {name}. "
            "We're sorry the visit didn't meet expectations. "
            "Please contact the clinic so we can look into it."
        )
    return (
        f"Thank you for the review of {name}. "
        "We're glad you visited and hope to see you again."
    )


def draft_review_reply(review: dict, business_name: str, instructions: str = "", keyword: str = "") -> str:
    from backend.tg.config import settings

    if not (settings.OPENAI_API_KEY or "").strip():
        return fallback_reply(review, business_name)
    extra = (instructions or "").strip()
    system = (
        "Write a short Google review reply for a clinic. "
        "Be polite, specific, and under 500 characters. "
        "Do not give medical advice, invent offers, or admit fault. "
        "Invite unhappy reviewers to contact the clinic."
    )
    if extra:
        system += f" Also follow these instructions from the business: {extra}"
    phrase = (keyword or "").strip()
    if phrase:
        system += (
            " Suggested services from Optimize: "
            f"{phrase}. "
            "If one of these fits what the patient wrote, mention that one service once inside a normal thank-you. "
            "If none of them fits this review, do not mention them."
        )
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        comment = (review.get("comment") or "").strip() or "(no written comment)"
        stars = review_star(review) or "unknown"
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            reasoning_effort=(settings.OPENAI_REASONING_EFFORT or "medium").strip() or "medium",
            messages=[
                {
                    "role": "system",
                    "content": system,
                },
                {
                    "role": "user",
                    "content": f"Business: {business_name}\nStars: {stars}\nReview: {comment}",
                },
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        return text or fallback_reply(review, business_name)
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] review draft fallback: {exc}", flush=True)
        return fallback_reply(review, business_name)


def _lean(reviews: list[dict]) -> str:
    stars = [review_star(review) or 0 for review in reviews]
    positive = sum(1 for star in stars if star >= 4)
    negative = sum(1 for star in stars if 0 < star <= 2)
    if negative > positive:
        return "needs_attention"
    if positive > negative:
        return "positive"
    return "mixed"


def theme_fallback(reviews: list[dict]) -> list[dict]:
    buckets = {key: [] for key, _label, _words in THEME_RULES}
    other = []
    for review in reviews or []:
        text = (review.get("comment") or "").lower()
        if not text:
            continue
        matched = False
        for key, _label, words in THEME_RULES:
            if any(word in text for word in words):
                buckets[key].append(review)
                matched = True
        if not matched:
            other.append(review)
    rows = []
    for key, label, _words in THEME_RULES:
        items = buckets[key]
        if not items:
            continue
        rows.append({"id": key, "label": label, "count": len(items), "lean": _lean(items)})
    if other:
        rows.append({"id": "other", "label": "Other", "count": len(other), "lean": _lean(other)})
    return rows


def normalize_model_themes(raw) -> list[dict] | None:
    if not isinstance(raw, list):
        return None
    allowed = {key for key, _label, _words in THEME_RULES} | {"other"}
    labels = {key: label for key, label, _words in THEME_RULES}
    labels["other"] = "Other"
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        theme_id = item.get("id")
        if theme_id not in allowed:
            continue
        lean = item.get("lean") if item.get("lean") in {"positive", "mixed", "needs_attention"} else "mixed"
        try:
            count = int(item.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            continue
        rows.append({"id": theme_id, "label": labels[theme_id], "count": count, "lean": lean})
    return rows or None


def sensitive_reason(review: dict) -> str | None:
    """Why an unanswered review needs a person. None when it can stay in the normal list."""
    if review.get("reviewReply"):
        return None
    if review_star(review) == 1:
        return "skip_one_star"
    text = (review.get("comment") or "").lower()
    if any(term in text for term in ANGRY_TERMS):
        return "skip_angry"
    if any(term in text for term in TREATMENT_TERMS):
        return "mentions_treatment"
    return None


def _review_time(review: dict) -> datetime | None:
    raw = review.get("createTime") or review.get("updateTime") or ""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def unanswered_stats(reviews: list[dict], now: datetime | None = None) -> dict:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    unanswered = [review for review in reviews or [] if not review.get("reviewReply")]
    oldest = None
    oldest_at = None
    for review in unanswered:
        parsed = _review_time(review)
        if parsed and (oldest is None or parsed < oldest):
            oldest = parsed
            oldest_at = review.get("createTime") or review.get("updateTime")
    days = (moment - oldest).days if oldest else 0
    return {"count": len(unanswered), "oldest_days": max(days, 0), "oldest_at": oldest_at}


def build_sensitive_queue(reviews: list[dict], skipped_drafts: list[dict] | None = None) -> list[dict]:
    items = []
    seen = set()
    for review in reviews or []:
        reason = sensitive_reason(review)
        if not reason:
            continue
        name = review.get("name") or ""
        seen.add(name)
        items.append(
            {
                "review_name": name,
                "comment": review.get("comment") or "",
                "star_rating": review.get("starRating"),
                "reason": reason,
                "create_time": review.get("createTime") or review.get("updateTime") or "",
                "suggested_reply": SAFE_REVIEW_REPLY,
            }
        )
    for draft in skipped_drafts or []:
        name = draft.get("review_name") or ""
        if not name or name in seen or draft.get("status") != "skipped":
            continue
        if draft.get("reason") not in {"skip_one_star", "skip_angry"}:
            continue
        seen.add(name)
        items.append(
            {
                "review_name": name,
                "comment": draft.get("comment") or "",
                "star_rating": draft.get("star_rating"),
                "reason": draft.get("reason"),
                "create_time": draft.get("updated_at") or "",
                "suggested_reply": SAFE_REVIEW_REPLY,
            }
        )
    return items


def normalize_dynamic_themes(raw) -> list[dict] | None:
    """Keep up to six categories named from the reviews themselves."""
    if not isinstance(raw, list):
        return None
    rows = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = " ".join(str(item.get("label") or "").split()).strip()
        key = label.lower()
        if not label or key in seen:
            continue
        lean = item.get("lean") if item.get("lean") in {"positive", "mixed", "needs_attention"} else "mixed"
        try:
            count = int(item.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            continue
        seen.add(key)
        rows.append({"id": key.replace(" ", "_")[:80], "label": label[:160], "count": count, "lean": lean})
        if len(rows) >= 11:
            break
    return rows or None


def named_group_limit(total: int) -> int:
    """Room for Others as the last group: 6 groups up to 150 reviews, 12 above that."""
    return 5 if total <= 150 else 11


def themes_from_assignments(reviews: list[dict], payload: dict) -> dict | None:
    """Count categories from the review numbers the model assigned, so the totals add up."""
    if not isinstance(payload, dict) or not reviews:
        return None
    categories = payload.get("categories")
    if not isinstance(categories, list):
        return None
    total = len(reviews)
    limit = named_group_limit(total)
    used: set[int] = set()
    named = []
    for item in categories:
        if not isinstance(item, dict) or len(named) >= limit:
            break
        label = " ".join(str(item.get("label") or "").split()).strip()
        if not label or label.lower() == "others":
            continue
        indexes = []
        for number in item.get("reviews") or []:
            try:
                index = int(number)
            except (TypeError, ValueError):
                continue
            if 1 <= index <= total and index not in used:
                used.add(index)
                indexes.append(index)
        if not indexes:
            continue
        advice = " ".join(str(item.get("advice") or "").split()).strip()
        named.append((label, advice, indexes))
    others = [index for index in range(1, total + 1) if index not in used]
    rows = []
    for label, advice, indexes in named:
        items = [reviews[index - 1] for index in indexes]
        row = {
            "id": label.lower().replace(" ", "_")[:80],
            "label": label,
            "count": len(items),
            "lean": _lean(items),
        }
        if advice:
            row["advice"] = advice
        rows.append(row)
    if others:
        items = [reviews[index - 1] for index in others]
        rows.append(
            {
                "id": "others",
                "label": "Others",
                "count": len(items),
                "lean": _lean(items),
                "advice": "These reviews do not fit the groups above.",
            }
        )
    if not rows:
        return None
    summary = " ".join(str(payload.get("summary") or "").split()).strip()
    return {"summary": summary, "themes": rows}


def dynamic_review_themes(reviews: list[dict]) -> list[dict]:
    """Name 5 or 6 groups from these reviews. Falls back to the word list if the model is unavailable."""
    from backend.tg.config import settings

    source = list(reviews or [])
    if not source:
        return {"summary": "", "themes": []}
    if not (settings.OPENAI_API_KEY or "").strip():
        return {"summary": "", "themes": theme_fallback(source)}
    group_count = 6 if len(source) <= 150 else 12
    compact = []
    for index, review in enumerate(source, start=1):
        comment = (review.get("comment") or "").strip()
        compact.append(
            {
                "n": index,
                "stars": review_star(review),
                "comment": comment[:300] or "(no written comment)",
            }
        )
    try:
        import json

        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            reasoning_effort=(settings.OPENAI_REASONING_EFFORT or "medium").strip() or "medium",
            messages=[
                {"role": "system", "content": "You reply with JSON only."},
                {
                    "role": "user",
                    "content": (
                        f"There are {len(compact)} reviews, numbered n. "
                        f"Use at most {group_count - 1} groups. "
                        "Write the summary and each note in easy, short words, as if talking to the clinic owner. "
                        "Say what patients like, what needs a fix, and one next step. "
                        "Name each group from what people actually wrote. Keep the full name. Do not cut a name off. "
                        "Each group needs label, advice (one short sentence), and reviews (the n numbers). "
                        "Do not add an Others group. Any review you do not place will be counted as Others. "
                        "Reply as JSON {\"summary\": \"...\", \"categories\": [{\"label\", \"advice\", \"reviews\": [1, 2]}]}.\n"
                        + json.dumps(compact, ensure_ascii=False)
                    ),
                },
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        data = json.loads(raw[raw.find("{") : raw.rfind("}") + 1] or "{}")
        assigned = themes_from_assignments(source, data)
        if assigned and assigned.get("themes"):
            return assigned
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] review themes failed: {exc}", flush=True)
    return {"summary": "", "themes": theme_fallback(source)}


def build_review_insights(reviews: list[dict], skipped_drafts: list[dict] | None = None, model_themes=None, now: datetime | None = None) -> dict:
    themes = normalize_model_themes(model_themes)
    if themes is None:
        themes = theme_fallback(reviews)
    return {
        "themes": themes,
        "sensitive": build_sensitive_queue(reviews, skipped_drafts),
        "waiting": unanswered_stats(reviews, now),
    }


def suggested_service_names(optimize: dict) -> list[str]:
    """Service names Optimize offered to add or improve. Empty when there are none."""
    names = []
    for item in (optimize or {}).get("service_recommendations") or []:
        if item.get("action") not in {"ADD", "REPLACE"}:
            continue
        name = str(item.get("proposed_name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names[:12]


def _gap_phrase_for_reply(client_id: str, location_id: str, review: dict) -> str:
    """On every 7th eligible reply, hand the suggested service names to the reply writer.

    An empty suggestion list does not inject anything and does not use up the 7th slot.
    """
    from backend.tg.database import advance_review_counter, get_gbp_optimize, remember_reply_keyword
    from backend.tg.services.gbp_visibility import eligible_for_keyword

    if not eligible_for_keyword(review):
        return ""
    names = suggested_service_names(get_gbp_optimize(client_id, location_id))
    include = advance_review_counter(client_id, location_id, phrase_fits=bool(names))
    if include and names:
        remember_reply_keyword(client_id, location_id, ", ".join(names))
        return ", ".join(names)
    return ""


def handle_one_review(client_id: str, location: dict, connection: dict, review: dict, creds) -> dict:
    """Skip, draft, or publish one review. Does not call Google when the action is draft or skip."""
    from backend.tg.database import get_gbp_review_draft, save_gbp_review_draft
    from backend.tg.services.gbp_api import update_review_reply

    review_name = review.get("name") or ""
    review_id = review_name.split("/")[-1] or "unknown"
    location_id = location.get("location_id") or ""
    draft_id = f"{client_id}:{location_id}:{review_id}"
    existing = get_gbp_review_draft(draft_id)
    if existing and existing.get("status") in {"pending_approval", "published", "skipped"}:
        return {"draft_id": draft_id, "status": "unchanged"}

    classification = classify_unanswered_review(
        review,
        skip_one_star=bool(connection.get("skip_one_star", True)),
        skip_angry=bool(connection.get("skip_angry", True)),
    )
    action = auto_reply_action(connection.get("auto_reply_mode") or "off", classification)
    now = datetime.now(timezone.utc).isoformat()
    base = {
        "client_id": client_id,
        "location_id": location_id,
        "review_name": review_name,
        "star_rating": review.get("starRating"),
        "comment": review.get("comment") or "",
        "updated_at": now,
    }
    if action == "skip":
        if classification == "already_replied":
            return {"draft_id": draft_id, "status": "already_replied"}
        save_gbp_review_draft(draft_id, {**base, "status": "skipped", "reason": classification})
        return {"draft_id": draft_id, "status": "skipped", "reason": classification}

    keyword = _gap_phrase_for_reply(client_id, location_id, review)
    reply = draft_review_reply(
        review,
        location.get("title") or "",
        connection.get("agent_instructions") or "",
        keyword=keyword,
    )
    if action == "draft":
        save_gbp_review_draft(
            draft_id,
            {**base, "status": "pending_approval", "reply": reply, "reason": None},
        )
        return {"draft_id": draft_id, "status": "pending_approval"}

    update_review_reply(creds, review_name, reply)
    save_gbp_review_draft(
        draft_id,
        {**base, "status": "published", "reply": reply, "published_at": now},
    )
    return {"draft_id": draft_id, "status": "published"}
