"""OpenAI web-search topic + script generation for Plug creators."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from openai import OpenAI

from backend.tg.config import settings

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

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

SCRIPT_REDO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "script": {"type": "string"},
        "hook_used": {"type": "string"},
        "cta_line": {"type": "string"},
    },
    "required": ["script", "hook_used", "cta_line"],
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
        if not use_search:
            raise
        print(
            f"[plug:openai] web_search failed ({type(first).__name__}: {first}); "
            "retrying simpler tool …",
            flush=True,
        )
        kwargs["tools"] = [{"type": "web_search"}]
        kwargs["tool_choice"] = "required"
        try:
            return client.responses.create(**kwargs)
        except Exception:
            pass
        kwargs["tools"] = [{"type": "web_search_preview"}]
        kwargs["tool_choice"] = "required"
        try:
            return client.responses.create(**kwargs)
        except Exception as second:
            print(
                f"[plug:openai] preview search failed ({type(second).__name__}: {second}); "
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
        f"[plug:openai] stage={stage} search={use_search} model={_model()} …",
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
            f"[plug:openai] stage={stage} OK in {time.perf_counter() - t0:.1f}s "
            f"chars={len(raw_text)} sources={len(sources)}",
            flush=True,
        )
        return parsed, sources
    except Exception as exc:
        print(
            f"[plug:openai] stage={stage} FAILED after {time.perf_counter() - t0:.1f}s: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        raise ValueError(f"OpenAI plug '{stage}' failed: {exc}") from exc


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


def search_topics(*, creator: dict, language: str, prompt: str = "") -> dict[str, Any]:
    lang = (language or "english").strip() or "english"
    extra = (prompt or "").strip()
    payload = {
        "name": creator.get("name") or "",
        "website": creator.get("website") or "",
        "instagram": creator.get("instagram") or "",
        "niche": creator.get("niche") or "",
        "niche_details": creator.get("niche_details") or "",
        "example_topics": list(creator.get("example_topics") or []),
        "example_scripts": list(creator.get("example_scripts") or []),
        "language": lang,
        "prompt": extra,
        "scoring": (
            "score is a 0-100 TREND score from web search only. "
            "Do not score niche fit. Search before scoring."
        ),
    }
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


def redo_script(
    *,
    creator: dict,
    topic: dict,
    language: str,
    prompt: str,
) -> dict[str, Any]:
    lang = (language or "english").strip() or "english"
    payload = {
        "name": creator.get("name") or "",
        "niche": creator.get("niche") or "",
        "niche_details": creator.get("niche_details") or "",
        "example_scripts": list(creator.get("example_scripts") or []),
        "language": lang,
        "prompt": (prompt or "").strip(),
        "topic": {
            "title": topic.get("title"),
            "score": topic.get("score"),
            "angle": topic.get("angle"),
            "script": topic.get("script"),
            "hook_used": topic.get("hook_used"),
            "cta_line": topic.get("cta_line"),
        },
    }
    messages = [
        {"role": "system", "content": _load_prompt("script_redo.txt")},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    parsed, _ = _call(
        messages=messages,
        schema=SCRIPT_REDO_SCHEMA,
        schema_name="plug_script_redo",
        stage="script_redo",
        use_search=False,
        effort="low",
        timeout=90.0,
    )
    script = str(parsed.get("script") or "").strip()
    if not script:
        raise ValueError("OpenAI returned an empty script")
    return {
        "script": script,
        "hook_used": str(parsed.get("hook_used") or "").strip(),
        "cta_line": str(parsed.get("cta_line") or "").strip(),
    }
