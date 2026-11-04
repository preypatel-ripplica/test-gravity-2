"""Entry draft generation for website CMS (OpenAI when configured)."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from backend.main import config
from backend.website.schema_presets import normalize_schema_value


def _fill_from_schema(schema: dict[str, Any], prompt: str = "") -> dict[str, Any]:
    """Offline fallback: return a deep copy of the normalized schema shell."""
    draft = deepcopy(normalize_schema_value(schema or {}))
    if isinstance(draft, dict) and prompt.strip():
        if "title" in draft and not draft.get("title"):
            draft["title"] = prompt.strip()[:120]
        if "excerpt" in draft and not draft.get("excerpt"):
            draft["excerpt"] = prompt.strip()[:240]
        if "summary" in draft and not draft.get("summary"):
            draft["summary"] = prompt.strip()[:240]
    return draft if isinstance(draft, dict) else {}


def generate_entry_draft(
    *,
    schema: dict[str, Any],
    collection: dict[str, Any],
    samples: list[dict[str, Any]],
    prompt: str = "",
) -> dict[str, Any]:
    """
    Returns `{ entry, model, notes }` like CMS_NEW generate.
    Uses OPENAI_API_KEY when set; otherwise schema shell + prompt title fill.
    """
    if not (config.OPENAI_API_KEY or "").strip():
        return {
            "entry": _fill_from_schema(schema, prompt),
            "model": None,
            "notes": "OPENAI_API_KEY not set — returned schema template. Fill OPENAI_API_KEY for AI drafts.",
        }

    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        sample_entries = []
        for row in samples[:5]:
            payload = row.get("entry") or row.get("data") or {}
            if isinstance(payload, dict):
                sample_entries.append(payload)

        system = (
            "You are a CMS content writer. Return ONLY valid JSON for one content entry "
            "matching the provided schema shape. Do not wrap in markdown."
        )
        user_payload = {
            "collection": {
                "name": collection.get("name"),
                "slug": collection.get("slug"),
                "ai_context": collection.get("ai_context") or {},
            },
            "schema": schema,
            "samples": sample_entries,
            "prompt": prompt or "Write a high-quality draft for this collection.",
        }
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL or "gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_payload)},
            ],
            temperature=0.7,
        )
        text = (response.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("model did not return an object")
        return {
            "entry": parsed,
            "model": config.OPENAI_MODEL,
            "notes": "Generated with OpenAI",
        }
    except Exception as exc:  # noqa: BLE001 — fall back cleanly
        from backend.tg.openai_log import log_openai_error
        log_openai_error("website:openai", exc)
        return {
            "entry": _fill_from_schema(schema, prompt),
            "model": None,
            "notes": f"AI generation failed ({exc}); returned schema template.",
        }
