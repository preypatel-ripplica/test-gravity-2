"""Creator keyword search — copied from Plug /topics.search so Plug can be deleted.

Sends the same profile JSON and uses the same OpenAI web_search call + topic_search.txt
instructions. Maps the 4 scored ideas into Internal keyword rows for the Keywords UI.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from openai import OpenAI

from backend.tg.config import settings
from backend.tg.openai_log import log_openai_error

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts" / "creator"

TOPIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "topics": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "score": {
                        "type": "integer",
                        "description": "Trend score 0-100 from web search interest only.",
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
            },
        }
    },
    "required": ["topics"],
}


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


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


def _clean_topics(raw_topics: list) -> list[dict]:
    out: list[dict] = []
    for item in raw_topics or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        script = str(item.get("script") or "").strip()
        if not title or not script:
            continue
        try:
            score = int(item.get("score"))
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(100, score))
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
    if len(out) != 4:
        raise ValueError(f"Expected 4 topics, got {len(out)}")
    return out


def search_profile_error(client: dict | None) -> str | None:
    missing: list[str] = []
    if not client or not str(client.get("niche") or "").strip():
        missing.append("niche")
    if not client or not str(client.get("niche_details") or "").strip():
        missing.append("details about niche")
    if not missing:
        return None
    if missing == ["niche"]:
        return "Add niche in Keywords before searching."
    if missing == ["details about niche"]:
        return "Add details about niche in Keywords before searching."
    return "Add niche and details about niche in Keywords before searching."


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


def build_search_payload(client: dict, *, language: str, prompt: str = "") -> dict[str, Any]:
    extra = (prompt or "").strip()
    return {
        "name": client.get("name") or "",
        "website": client.get("website") or client.get("website_url") or "",
        "instagram": _instagram(client),
        "niche": client.get("niche") or "",
        "niche_details": client.get("niche_details") or "",
        "example_topics": list(client.get("example_topics") or []),
        "example_scripts": list(client.get("example_scripts") or []),
        "language": (language or "english").strip() or "english",
        "prompt": extra,
        "scoring": (
            "score is a 0-100 TREND score from web search only. "
            "Do not score niche fit. Search before scoring."
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


def search_topics(*, client: dict, language: str = "english", prompt: str = "") -> dict[str, Any]:
    lang = (language or "english").strip() or "english"
    extra = (prompt or "").strip()
    payload = build_search_payload(client, language=lang, prompt=extra)
    messages = [
        {"role": "system", "content": _load_prompt("topic_search.txt")},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    parsed, sources = _call(
        messages=messages,
        schema=TOPIC_SCHEMA,
        schema_name="plug_topic_search",
        stage="topic_search",
        use_search=True,
        effort="medium",
        timeout=180.0,
    )
    return {
        "language": lang,
        "prompt": extra,
        "topics": _clean_topics(parsed.get("topics")),
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
    if kwargs.get("description") is not None:
        profile["description"] = kwargs.get("description")
    detail = search_profile_error(profile)
    if detail:
        raise ValueError(detail)

    print("[creator:topics] search START (web_search, no sitemap)", flush=True)
    result = search_topics(
        client=profile,
        language=_language(profile),
        prompt=user_prompt or kwargs.get("user_prompt") or "",
    )
    topics = keywords_from_search(result["topics"])
    print(
        f"[creator:topics] search DONE topics={len(topics)} sources={len(result.get('sources') or [])}",
        flush=True,
    )
    meta = {
        "generator": "openai",
        "openai_stages": ["topic_search"],
        "pages_scraped": 0,
        "page_title": None,
        "page_snippet": None,
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
    description: str | None = None,
    topics: list | None = None,
    user_prompt: str | None = None,
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
    )
    client = fetch_client_doc(client_id, username=username) or client
    existing_now = normalize_topics(fetch_topics(client_id))
    manuals_now = [t for t in existing_now if t.get("source") == "manual"]
    if topics is not None:
        manuals_now = manuals
    client["topics"] = merge_topics(manuals_now, auto, previous=existing_now)
    replace_topics(client_id, client["topics"])
    print(
        f"[creator:topics] refresh SAVED topics={len(client['topics'])} "
        f"(manual={len(manuals_now)} auto={len(auto)})",
        flush=True,
    )
    return {"client": client, "scrape_meta": scrape_meta}
