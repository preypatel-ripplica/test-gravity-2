"""Creator keyword search — copied from Plug /topics.search so Plug can be deleted.

Sends the same profile JSON and uses the same OpenAI web_search call + topic_search.txt
instructions. Maps scored ideas into Internal keyword rows for the Keywords UI.
"""

from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import HTTPException, status
from openai import OpenAI

from backend.tg.config import settings
from backend.tg.openai_log import log_openai_error
from backend.tg.services.topics import FETCH_HEADERS

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts" / "creator"

DEFAULT_TOPIC_COUNT = 4
TOPIC_COUNT_MIN = 4
TOPIC_COUNT_MAX = 20
MIN_TOPIC_SCORE = 91  # strictly above 90

_TOPIC_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "score": {
            "type": "integer",
            "description": (
                "Trend score 91-100 from web search interest only. "
                "Do not return a topic unless it scores above 90."
            ),
        },
        "score_reason": {
            "type": "string",
            "description": "Why this trend score, citing search evidence only.",
        },
        "trend_signal": {
            "type": "string",
            "description": "Short trend label: rising, breakout, seasonal, news, steady, fading, weak.",
        },
        "angle": {"type": "string"},
        "script": {"type": "string"},
        "hook_used": {"type": "string"},
        "cta_line": {"type": "string"},
    },
    "required": [
        "title",
        "score",
        "score_reason",
        "trend_signal",
        "angle",
        "script",
        "hook_used",
        "cta_line",
    ],
}


def clamp_topic_count(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = DEFAULT_TOPIC_COUNT
    return max(TOPIC_COUNT_MIN, min(TOPIC_COUNT_MAX, count))


def topic_search_schema(count: int = DEFAULT_TOPIC_COUNT) -> dict[str, Any]:
    n = clamp_topic_count(count)
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "topics": {
                "type": "array",
                "minItems": n,
                "maxItems": n,
                "items": copy.deepcopy(_TOPIC_ITEM_SCHEMA),
            }
        },
        "required": ["topics"],
    }


TOPIC_SCHEMA: dict[str, Any] = topic_search_schema(DEFAULT_TOPIC_COUNT)

NICHE_INFER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "niche": {
            "type": "string",
            "description": "2-6 word label for what this creator makes content about.",
        },
        "niche_details": {
            "type": "string",
            "description": "2-4 sentences: audience, topics they cover, and tone.",
        },
    },
    "required": ["niche", "niche_details"],
}

NICHE_INFER_PROMPT = """You infer a general content creator's niche from their website.

Return JSON only:
- niche: 2-6 words. What they make content about. Not a slogan. Not a company name.
  Examples: "Mumbai street food", "personal finance for millennials", "MotoGP explainers"
- niche_details: 2-4 sentences. Who it is for, what they cover, and how they talk if that is visible.

Do not assume a clinic, doctor, hospital, or medical practice unless the site actually is that.
If the homepage is thin, still give a best-effort niche from the name, URL, and any visible copy.
"""


def _load_prompt(name: str, *, topic_count: int | None = None) -> str:
    text = (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()
    if topic_count is not None:
        text = text.replace("__TOPIC_COUNT__", str(clamp_topic_count(topic_count)))
    return text


def _model() -> str:
    return (settings.OPENAI_MODEL or "gpt-6.1-sol").strip() or "gpt-6.1-sol"


def _client(timeout: float) -> OpenAI:
    if not (settings.OPENAI_API_KEY or "").strip():
        raise ValueError("OPENAI_API_KEY is not set.")
    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=float(timeout or 180.0),
        max_retries=1,
    )


def _parse_json(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("OpenAI returned an empty response")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("OpenAI returned non-JSON")
        return json.loads(text[start : end + 1])


def _output_text(response: Any) -> str:
    raw = getattr(response, "output_text", None) or ""
    if raw:
        return raw
    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for part in getattr(item, "content", []) or []:
            text = getattr(part, "text", None)
            if text:
                chunks.append(text)
    return "".join(chunks)


def _citation_urls(response: Any) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for item in getattr(response, "output", []) or []:
        for part in getattr(item, "content", []) or []:
            for ann in getattr(part, "annotations", None) or []:
                url = getattr(ann, "url", None) or getattr(ann, "href", None)
                if url and url not in seen:
                    seen.add(url)
                    urls.append(url)
        action = getattr(item, "action", None)
        sources = getattr(action, "sources", None) or []
        for src in sources:
            url = getattr(src, "url", None) if not isinstance(src, dict) else src.get("url")
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls[:12]


def _responses_create(
    client: OpenAI,
    *,
    messages: list[dict],
    schema: dict[str, Any],
    schema_name: str,
    use_search: bool,
    effort: str,
) -> Any:
    kwargs: dict[str, Any] = {
        "model": _model(),
        "input": messages,
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
    }
    if effort:
        kwargs["reasoning"] = {"effort": effort}
    if use_search:
        kwargs["tools"] = [
            {
                "type": "web_search",
                "user_location": {"type": "approximate", "country": "IN"},
            }
        ]
        kwargs["tool_choice"] = {"type": "web_search"}

    try:
        return client.responses.create(**kwargs)
    except Exception as first:
        log_openai_error("creator:openai", first)
        if not use_search:
            raise
        print(
            f"[creator:openai] web_search failed ({type(first).__name__}: {first}); "
            "retrying simpler tool …",
            flush=True,
        )
        kwargs["tools"] = [{"type": "web_search"}]
        kwargs["tool_choice"] = "required"
        try:
            return client.responses.create(**kwargs)
        except Exception as retry_exc:
            log_openai_error("creator:openai", retry_exc)
        kwargs["tools"] = [{"type": "web_search_preview"}]
        kwargs["tool_choice"] = "required"
        try:
            return client.responses.create(**kwargs)
        except Exception as second:
            log_openai_error("creator:openai", second)
            print(
                f"[creator:openai] preview search failed ({type(second).__name__}: {second}); "
                "retrying without json_schema …",
                flush=True,
            )
            kwargs.pop("text", None)
            kwargs["tools"] = [{"type": "web_search"}]
            return client.responses.create(**kwargs)


def _call(
    *,
    messages: list[dict],
    schema: dict[str, Any],
    schema_name: str,
    stage: str,
    use_search: bool,
    effort: str = "medium",
    timeout: float = 180.0,
) -> tuple[dict[str, Any], list[str]]:
    client = _client(timeout)
    t0 = time.perf_counter()
    print(
        f"[creator:openai] stage={stage} search={use_search} model={_model()} …",
        flush=True,
    )
    try:
        response = _responses_create(
            client,
            messages=messages,
            schema=schema,
            schema_name=schema_name,
            use_search=use_search,
            effort=effort,
        )
        raw_text = _output_text(response)
        sources = _citation_urls(response) if use_search else []
        parsed = _parse_json(raw_text)
        print(
            f"[creator:openai] stage={stage} OK in {time.perf_counter() - t0:.1f}s "
            f"chars={len(raw_text)} sources={len(sources)}",
            flush=True,
        )
        return parsed, sources
    except Exception as exc:
        log_openai_error("creator:openai", exc)
        print(
            f"[creator:openai] stage={stage} FAILED after {time.perf_counter() - t0:.1f}s: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        raise ValueError(f"OpenAI creator '{stage}' failed: {exc}") from exc


def _clean_topics(raw_topics: list, *, count: int = DEFAULT_TOPIC_COUNT) -> list[dict]:
    wanted = clamp_topic_count(count)
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw_topics or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        script = str(item.get("script") or "").strip()
        if not title or not script:
            continue
        key = title.lower()
        if key in seen:
            continue
        try:
            score = int(item.get("score"))
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(100, score))
        if score < MIN_TOPIC_SCORE:
            continue
        seen.add(key)
        out.append(
            {
                "id": str(uuid4()),
                "title": title,
                "score": score,
                "angle": str(item.get("angle") or "").strip(),
                "script": script,
                "hook_used": str(item.get("hook_used") or "").strip(),
                "cta_line": str(item.get("cta_line") or "").strip(),
                "rating": None,
            }
        )
    out.sort(key=lambda row: (-int(row.get("score") or 0), str(row.get("title") or "").lower()))
    return out[:wanted]


def _website_url(client: dict | None) -> str:
    if not client:
        return ""
    return str(client.get("website") or client.get("website_url") or "").strip()


def search_profile_error(client: dict | None) -> str | None:
    if _website_url(client) or str((client or {}).get("niche") or "").strip():
        return None
    return "Add a website or a niche in Keywords before searching."


def _normalize_website(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if not urlparse(raw).scheme:
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return raw


def _html_snippet(html: str, *, limit: int = 4000) -> tuple[str, str]:
    raw = html or ""
    title = ""
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    if match:
        title = re.sub(r"\s+", " ", match.group(1)).strip()
    if not title:
        match = re.search(
            r'(?is)<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
            raw,
        )
        if match:
            title = re.sub(r"\s+", " ", match.group(1)).strip()
    desc = ""
    match = re.search(
        r'(?is)<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']+)',
        raw,
    )
    if match:
        desc = re.sub(r"\s+", " ", match.group(1)).strip()
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", raw)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    parts = [part for part in (title, desc, text) if part]
    snippet = "\n".join(parts)[:limit].strip()
    return title, snippet


def fetch_homepage_snippet(website_url: str) -> dict[str, str]:
    url = _normalize_website(website_url)
    if not url:
        return {"website_url": "", "page_title": "", "page_snippet": ""}
    try:
        with httpx.Client(follow_redirects=True, timeout=15.0, headers=FETCH_HEADERS) as client:
            response = client.get(url)
            response.raise_for_status()
            title, snippet = _html_snippet(response.text or "")
    except Exception as exc:
        print(f"[creator:topics] homepage fetch failed for {url!r}: {exc}", flush=True)
        return {"website_url": url, "page_title": "", "page_snippet": ""}
    return {"website_url": url, "page_title": title, "page_snippet": snippet}


def infer_niche_from_website(
    *,
    website_url: str,
    name: str = "",
    existing_niche: str = "",
) -> dict[str, str]:
    url = _normalize_website(website_url)
    home = fetch_homepage_snippet(url) if url else {
        "website_url": "",
        "page_title": "",
        "page_snippet": "",
    }
    payload = {
        "name": (name or "").strip(),
        "website": url,
        "existing_niche": (existing_niche or "").strip(),
        "page_title": home.get("page_title") or "",
        "homepage_text": home.get("page_snippet") or "",
    }
    use_search = not bool(payload["homepage_text"])
    try:
        parsed, _sources = _call(
            messages=[
                {"role": "system", "content": NICHE_INFER_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            schema=NICHE_INFER_SCHEMA,
            schema_name="creator_niche_infer",
            stage="infer_niche",
            use_search=use_search,
            effort="low",
            timeout=60.0,
        )
    except Exception as exc:
        print(f"[creator:topics] infer niche failed: {exc}", flush=True)
        return {**home, "niche": "", "niche_details": ""}
    return {
        **home,
        "niche": str(parsed.get("niche") or "").strip(),
        "niche_details": str(parsed.get("niche_details") or "").strip(),
    }


def fill_niche_from_website(client: dict) -> tuple[dict, dict]:
    """Fill empty niche / niche_details from the website. Does not overwrite filled fields."""
    profile = dict(client or {})
    website = _website_url(profile)
    need_niche = not str(profile.get("niche") or "").strip()
    need_details = not str(profile.get("niche_details") or "").strip()
    meta = {
        "inferred_niche": None,
        "inferred_niche_details": None,
        "page_title": None,
        "page_snippet": None,
    }
    if not website or (not need_niche and not need_details):
        return profile, meta
    print(f"[creator:topics] infer niche from website {website!r}", flush=True)
    inferred = infer_niche_from_website(
        website_url=website,
        name=str(profile.get("name") or ""),
        existing_niche=str(profile.get("niche") or "").strip(),
    )
    if inferred.get("page_title"):
        meta["page_title"] = inferred["page_title"]
    if inferred.get("page_snippet"):
        meta["page_snippet"] = inferred["page_snippet"][:400]
        profile["_website_snippet"] = inferred["page_snippet"]
    if need_niche and inferred.get("niche"):
        profile["niche"] = inferred["niche"]
        meta["inferred_niche"] = inferred["niche"]
    if need_details and inferred.get("niche_details"):
        profile["niche_details"] = inferred["niche_details"]
        meta["inferred_niche_details"] = inferred["niche_details"]
    return profile, meta


def _language(client: dict) -> str:
    for row in client.get("youtube_languages") or []:
        if isinstance(row, dict):
            key = str(row.get("key") or "").strip()
            if key:
                return key
        elif str(row or "").strip():
            return str(row).strip()
    return "english"


def _instagram(client: dict) -> str:
    raw = str(client.get("instagram") or "").strip()
    if raw:
        return raw
    client_id = str(client.get("id") or "").strip()
    if not client_id:
        return ""
    try:
        from backend.tg.database import get_instagram_connection

        conn = get_instagram_connection(client_id) or {}
        return str(conn.get("instagram_username") or "").strip()
    except Exception:
        return ""


def build_search_payload(
    client: dict,
    *,
    language: str,
    prompt: str = "",
    topic_count: int = DEFAULT_TOPIC_COUNT,
) -> dict[str, Any]:
    extra = (prompt or "").strip()
    count = clamp_topic_count(topic_count)
    website = _website_url(client)
    snippet = str(client.get("_website_snippet") or "").strip()
    return {
        "name": client.get("name") or "",
        "website": website,
        "website_snippet": snippet[:1500],
        "instagram": _instagram(client),
        "niche": client.get("niche") or "",
        "niche_details": client.get("niche_details") or "",
        "example_topics": list(client.get("example_topics") or []),
        "example_scripts": list(client.get("example_scripts") or []),
        "language": (language or "english").strip() or "english",
        "prompt": extra,
        "topic_count": count,
        "scoring": (
            f"Return exactly {count} topics. "
            "score is a 91-100 TREND score from web search only. "
            "Do not include any topic scoring 90 or below. "
            "Do not score niche fit. Search before scoring. "
            "If niche is empty, infer it from website / website_snippet first."
        ),
    }


def weight_for_score(score: int | float) -> str:
    value = float(score or 0)
    if value >= 70:
        return "high"
    if value >= 50:
        return "medium"
    return "low"


def keywords_from_search(raw_topics: list) -> list[dict]:
    from backend.tg.services.topics import apply_stored_recommendation_scores, make_topic

    rows: list[dict] = []
    for item in raw_topics or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("text") or "").strip()
        if not title:
            continue
        try:
            score = int(item.get("score") if item.get("score") is not None else item.get("recommendation_score") or 0)
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(100, score))
        topic = make_topic(title, weight_for_score(score), "auto")
        if item.get("id"):
            topic["id"] = str(item["id"])
        topic["recommendation_score"] = float(score)
        rows.append(topic)
    return apply_stored_recommendation_scores(rows)


def search_topics(
    *,
    client: dict,
    language: str = "english",
    prompt: str = "",
    topic_count: int = DEFAULT_TOPIC_COUNT,
) -> dict[str, Any]:
    lang = (language or "english").strip() or "english"
    extra = (prompt or "").strip()
    count = clamp_topic_count(topic_count)
    payload = build_search_payload(client, language=lang, prompt=extra, topic_count=count)
    schema = topic_search_schema(count)
    system = _load_prompt("topic_search.txt", topic_count=count)

    def _run(user_payload: dict[str, Any], stage: str) -> tuple[list[dict], list[str]]:
        parsed, sources = _call(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            schema=schema,
            schema_name="plug_topic_search",
            stage=stage,
            use_search=True,
            effort="medium",
            timeout=max(180.0, min(360.0, 90.0 + count * 15.0)),
        )
        return _clean_topics(parsed.get("topics"), count=count), sources

    topics, sources = _run(payload, "topic_search")
    if len(topics) < count:
        retry_payload = dict(payload)
        retry_payload["scoring"] = (
            f"Previous results included topics scoring 90 or below and were discarded. "
            f"Return exactly {count} NEW topics. Every score MUST be 91-100. "
            "Only currently hot/rising ideas. Search again if needed."
        )
        print(
            f"[creator:topics] retrying search: got {len(topics)}/{count} above {MIN_TOPIC_SCORE - 1}",
            flush=True,
        )
        retry_topics, retry_sources = _run(retry_payload, "topic_search_retry")
        seen = {str(row.get("title") or "").lower() for row in topics}
        for row in retry_topics:
            key = str(row.get("title") or "").lower()
            if key in seen:
                continue
            topics.append(row)
            seen.add(key)
            if len(topics) >= count:
                break
        if retry_sources:
            sources = list(dict.fromkeys([*sources, *retry_sources]))
        topics.sort(key=lambda row: (-int(row.get("score") or 0), str(row.get("title") or "").lower()))
        topics = topics[:count]
    if len(topics) != count:
        raise ValueError(
            f"Expected {count} topics scoring above 90, got {len(topics)}. Try again."
        )
    return {
        "language": lang,
        "prompt": extra,
        "topic_count": count,
        "topics": topics,
        "sources": sources,
    }


def generate_creator_keywords(
    *,
    client: dict | None = None,
    client_id: str | None = None,
    user_prompt: str | None = None,
    **kwargs,
) -> tuple[list[dict], dict]:
    """Suggest-mode entry: return (topics, scrape_meta) like generate_auto_topics."""
    profile = dict(client or {})
    cid = client_id or kwargs.get("client_id") or profile.get("id")
    if cid:
        from backend.tg.database import fetch_client_doc

        stored = fetch_client_doc(cid) or {}
        stored.update({k: v for k, v in profile.items() if v not in (None, "", [], {})})
        profile = stored
        profile["id"] = cid
    if kwargs.get("client_name") and not profile.get("name"):
        profile["name"] = kwargs.get("client_name")
    if kwargs.get("website_url") is not None:
        profile["website_url"] = kwargs.get("website_url")
    if kwargs.get("niche") is not None:
        profile["niche"] = kwargs.get("niche")
    if kwargs.get("niche_details") is not None:
        profile["niche_details"] = kwargs.get("niche_details")
    if kwargs.get("example_topics") is not None:
        profile["example_topics"] = kwargs.get("example_topics")
    if kwargs.get("description") is not None:
        profile["description"] = kwargs.get("description")
    profile, infer_meta = fill_niche_from_website(profile)
    detail = search_profile_error(profile)
    if detail:
        raise ValueError(detail)

    topic_count = clamp_topic_count(
        kwargs.get("topic_count") if kwargs.get("topic_count") is not None else DEFAULT_TOPIC_COUNT
    )
    print(
        f"[creator:topics] search START (web_search, no sitemap) count={topic_count} "
        f"niche={profile.get('niche')!r}",
        flush=True,
    )
    result = search_topics(
        client=profile,
        language=_language(profile),
        prompt=user_prompt or kwargs.get("user_prompt") or "",
        topic_count=topic_count,
    )
    topics = keywords_from_search(result["topics"])
    print(
        f"[creator:topics] search DONE topics={len(topics)} sources={len(result.get('sources') or [])}",
        flush=True,
    )
    stages = ["topic_search"]
    if infer_meta.get("inferred_niche") or infer_meta.get("inferred_niche_details"):
        stages = ["infer_niche", *stages]
    meta = {
        "generator": "openai",
        "openai_stages": stages,
        "pages_scraped": 1 if infer_meta.get("page_snippet") else 0,
        "page_title": infer_meta.get("page_title"),
        "page_snippet": infer_meta.get("page_snippet"),
        "inferred_niche": infer_meta.get("inferred_niche"),
        "inferred_niche_details": infer_meta.get("inferred_niche_details"),
        "niche": (profile.get("niche") or "").strip() or None,
        "niche_details": (profile.get("niche_details") or "").strip() or None,
        "openai_rationale": (
            f"{len(topics)} topics from live web search in niche "
            f"{(profile.get('niche') or '').strip()!r}."
        ),
        "openai_error": None,
        "sources": result.get("sources") or [],
    }
    return topics, meta


def refresh_creator_keywords(
    username: str,
    client_id: str,
    *,
    website_url: str | None = None,
    niche: str | None = None,
    niche_details: str | None = None,
    example_topics: list | None = None,
    description: str | None = None,
    topics: list | None = None,
    user_prompt: str | None = None,
    topic_count: int | None = None,
    **_ignored,
) -> dict:
    """Refresh-mode entry: persist profile, search, merge manuals, save."""
    from backend.tg.database import (
        fetch_client_doc,
        fetch_topics,
        replace_topics,
        update_client_fields,
    )
    from backend.tg.services.topics import merge_topics, normalize_topics

    print(f"[creator:topics] refresh START client_id={client_id}", flush=True)
    client = fetch_client_doc(client_id, username=username)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{client_id}' not found.",
        )

    fields: dict = {}
    if website_url is not None:
        fields["website_url"] = website_url.strip() or None
    if niche is not None:
        fields["niche"] = niche.strip() or None
    if niche_details is not None:
        fields["niche_details"] = niche_details.strip() or None
    if example_topics is not None:
        fields["example_topics"] = [
            str(topic).strip()
            for topic in example_topics
            if topic is not None and str(topic).strip()
        ]
    if description is not None:
        fields["description"] = description.strip() or None
    if fields:
        client = update_client_fields(client_id, username, fields) or client
    client["topics"] = fetch_topics(client_id)

    existing = normalize_topics(topics if topics is not None else client.get("topics"))
    manuals = [t for t in existing if t.get("source") == "manual"]

    auto, scrape_meta = generate_creator_keywords(
        client=client,
        client_id=client_id,
        user_prompt=user_prompt,
        topic_count=topic_count,
        niche=niche if niche is not None else client.get("niche"),
        niche_details=niche_details if niche_details is not None else client.get("niche_details"),
        example_topics=example_topics if example_topics is not None else client.get("example_topics"),
    )
    client = fetch_client_doc(client_id, username=username) or client
    existing_now = normalize_topics(fetch_topics(client_id))
    manuals_now = [t for t in existing_now if t.get("source") == "manual"]
    if topics is not None:
        manuals_now = manuals
    client["topics"] = merge_topics(manuals_now, auto, previous=existing_now)
    replace_topics(client_id, client["topics"])
    inferred_fields: dict = {}
    if scrape_meta.get("inferred_niche"):
        inferred_fields["niche"] = scrape_meta["inferred_niche"]
    if scrape_meta.get("inferred_niche_details"):
        inferred_fields["niche_details"] = scrape_meta["inferred_niche_details"]
    if inferred_fields:
        client = update_client_fields(client_id, username, inferred_fields) or client
        client["topics"] = merge_topics(manuals_now, auto, previous=existing_now)
        print(
            f"[creator:topics] saved inferred niche={inferred_fields.get('niche')!r}",
            flush=True,
        )
    print(
        f"[creator:topics] refresh SAVED topics={len(client['topics'])} "
        f"(manual={len(manuals_now)} auto={len(auto)})",
        flush=True,
    )
    return {"client": client, "scrape_meta": scrape_meta}
