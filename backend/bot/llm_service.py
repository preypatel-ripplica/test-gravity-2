"""LLM provider adapter for the `ai_conversation` workflow node.

One thin interface — `run_ai_turn()` — that every provider hides behind. This
adapter *is* the abstraction (we deliberately do NOT use LangChain: its
chains/memory/agent layers duplicate and fight the workflow engine's own state,
history, and routing; we only need one structured chat call per turn).

Providers:
  - OpenAI (v1 default, `gpt-5-mini`) via the official `openai` SDK.
  - Gemini (alternate, `gemini-2.5-flash`) via plain REST (no extra dep).
  - A deterministic fake (AI_NODE_FAKE=1) for local smoke tests without a key.

The provider is chosen from the model name: `gemini-*` -> Gemini, else OpenAI.

Every turn returns a JSON object:
    {"reply": str, "collected": {field: value}, "done": bool, "wants_human": bool}
`collected` holds only the fields gathered so far (partial is fine); enum/date
normalization is enforced again server-side in services.py.
"""

from __future__ import annotations


import os
import json
import dataclasses

import requests


DEFAULT_MODEL = os.getenv("AI_NODE_MODEL", "gpt-5-mini")

# Approximate USD price per 1,000,000 tokens (input, output). Override the whole
# map with AI_PRICE_JSON='{"model":[in,out]}'. Cost is frozen at capture time, so
# stale prices only affect future turns.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-5.6-luna": (0.20, 1.20),   # the model the ai_conversation node runs (AI_NODE_MODEL)
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
}
_DEFAULT_PRICE = (0.50, 1.50)
# Cached prompt-prefix reads bill at this multiple of the input rate (OpenAI
# GPT-5.6+: 0.1x). Automatic prefix caching means turns 2..N of a conversation
# re-send the same system prompt + earlier history at a 90% discount.
_CACHED_INPUT_MULT = 0.1
try:
    MODEL_PRICING.update({k: tuple(v) for k, v in json.loads(os.getenv("AI_PRICE_JSON") or "{}").items()})
except Exception:  # noqa: BLE001 - bad override JSON must never break the app
    pass


def usage_cost(usage: dict | None) -> float:
    """Estimated USD cost for a turn's token usage dict
    {prompt, completion, model, cached}. `cached` (subset of prompt tokens served
    from OpenAI's prefix cache) is billed at _CACHED_INPUT_MULT x the input rate."""
    if not usage:
        return 0.0
    pin, pout = MODEL_PRICING.get((usage.get("model") or "").lower(), _DEFAULT_PRICE)
    prompt = usage.get("prompt", 0) or 0
    cached = min(usage.get("cached", 0) or 0, prompt)
    completion = usage.get("completion", 0) or 0
    return round(
        ((prompt - cached) / 1e6) * pin
        + (cached / 1e6) * pin * _CACHED_INPUT_MULT
        + (completion / 1e6) * pout,
        6,
    )


class LLMError(Exception):
    """Any provider/parse failure. The caller catches this and sends the node's
    fallback_message instead of failing the run."""


@dataclasses.dataclass
class AiToolCall:
    """One tool the LLM asked us to run this turn. `name` matches an
    AiToolSpec.name from the node config; unknown names are dropped by the
    services layer (never trusted blindly)."""
    name: str
    args: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class AiTurn:
    reply: str = ""
    done: bool = False
    collected: dict = dataclasses.field(default_factory=dict)
    wants_human: bool = False
    # Interactive reply: render `reply` with tappable WhatsApp buttons/list.
    # ask_field -> render that field's configured enum options; options -> a
    # generic choice list not tied to a field. Either yields buttons (1-3) or a
    # list (4-10); the services layer resolves and caps them.
    ask_field: str | None = None
    options: list = dataclasses.field(default_factory=list)
    # Tools to run this turn, in order, before the reply is sent.
    actions: list = dataclasses.field(default_factory=list)
    # Token usage for this turn: {prompt, completion, total, model}. None if the
    # provider gave no usage (e.g. the AI_NODE_FAKE stub).
    usage: dict | None = None


# --------------------------------------------------------------------------- #
# Prompt building
# --------------------------------------------------------------------------- #

def build_system_prompt(config) -> str:
    """Assemble the system prompt from an AiConversationConfig (knowledge, field
    list, guardrails, the strict JSON output contract, then this conversation's
    goal).

    Ordering matters for cost: everything except `goal`/`language_hint` is
    identical across every conversation of a flow, so the static content is placed
    FIRST as one long stable prefix and the two per-conversation fields are appended
    LAST. OpenAI then caches that shared prefix across conversations (reads at 0.1x),
    not just within one — see llm_service.usage_cost / _CACHED_INPUT_MULT."""
    lines = [
        "You are a friendly, professional WhatsApp assistant for a medical clinic.",
    ]

    if config.knowledge and config.knowledge.strip():
        lines.append(
            "\nClinic information (answer questions using ONLY this; never invent facts):"
        )
        lines.append(config.knowledge.strip())

    lines.append(
        "\nCollect these details from the patient, conversationally, a couple at a time:"
    )
    for f in config.fields:
        bits = [f"- {f.name}"]
        if f.description:
            bits.append(f": {f.description}")
        meta = ["required" if f.required else "optional"]
        if f.type == "enum" and f.options:
            allowed = "; ".join(f.options)
            if f.allow_other:
                meta.append(
                    f"map the patient's words to exactly one of: {allowed} "
                    "(or keep their own words only if none fit)"
                )
            else:
                meta.append(f"must be exactly one of: {allowed}")
        if f.type in ("date", "time") and f.format_hint:
            meta.append(f"normalize to format {f.format_hint}")
        if f.type == "media":
            meta.append(
                "this is a FILE the patient uploads (photo/PDF); ask them to send it "
                "and do NOT put it in `collected` — the system captures uploads automatically"
            )
        bits.append(f" [{', '.join(meta)}]")
        lines.append("".join(bits))

    lines.append(
        "\nRules:\n"
        "- Keep every message short (1-3 sentences). This is WhatsApp.\n"
        "- Do NOT give medical advice, diagnoses, or promises about treatment or outcomes.\n"
        "- Only discuss this clinic and booking; politely steer back if the patient drifts.\n"
        "- Never invent facts that are not in the clinic information above."
    )
    if config.emergency_message:
        lines.append(
            f"- If the patient describes a medical emergency, tell them immediately: "
            f"{config.emergency_message}"
        )

    lines.append(
        "\nTappable choices (use whenever the answer is from a small fixed set — much "
        "better UX than asking them to type):\n"
        "- To ask for a field that has fixed options, set `ask_field` to that field's name "
        "and keep `reply` a short question — the system shows the field's options as WhatsApp "
        "buttons/list automatically, so do NOT list the options inside `reply`.\n"
        "- For a short choice NOT tied to a field (e.g. a yes/no confirmation), set `options` "
        "to a list of up to 10 short choices instead.\n"
        "- 1-3 choices render as buttons, 4-10 as a tappable list. Use plain text (no "
        "`ask_field`/`options`) for open questions like name or date."
    )

    tools = list(getattr(config, "tools", None) or [])
    if tools:
        lines.append(_build_tools_section(tools))

    lines.append(
        "\nReply with a SINGLE JSON object and nothing else, exactly this shape:\n"
        '{"reply": "<your next WhatsApp message to the patient>", '
        '"ask_field": null, '
        '"options": [], '
        '"actions": [], '
        '"collected": {"<field_name>": "<value>"}, '
        '"done": false, '
        '"wants_human": false}\n'
        "In `collected` include ONLY fields you have confidently gathered so far; "
        "omit the rest. For enum fields the value must match an allowed option; for "
        "date/time fields use the required format. Set `done` to true only when every "
        "required field is gathered OR the patient wants to stop. Set `wants_human` to "
        "true if the patient asks for a person/agent or you genuinely cannot help. "
        "Set `ask_field` to a field name OR `options` to a choice list when offering "
        "tappable choices, otherwise leave them null/empty."
    )

    # Per-conversation tail — the ONLY parts that vary between conversations, kept
    # last so everything above is a cache-shareable prefix across conversations.
    lines.append(f"\nThis specific conversation:\nYour goal: {config.goal}")
    if config.language_hint and config.language_hint.strip():
        lines.append(config.language_hint.strip())

    return "\n".join(lines)


# Args each tool type accepts. The LLM fills ONLY these — the connection id,
# spreadsheet, sheet name, action and row reference all come from the node's
# stored config, so no argument it invents can point a write somewhere else.
_TOOL_ARG_HINTS = {
    "send_message": '{"text": "<message to send>"}',
    "ask_question": (
        '{"question": "<what to ask>", "options": ["<choice>", ...], '
        '"variable": "<name to store the answer under>"}  '
        "(options may be omitted for an open question)"
    ),
    "google_sheets": '{}  (no arguments - it saves the details collected so far)',
    "generate_id": '{"variable": "<name to store the new id under>"}',
}


def _build_tools_section(tools) -> str:
    lines = ["\nTools you can call. Put them in `actions` as "
             '{"tool": "<name>", "args": {...}}, and they run in order:']
    for tool in tools:
        bits = [f"- {tool.name}"]
        if tool.description:
            bits.append(f": {tool.description}")
        hint = _TOOL_ARG_HINTS.get(tool.type)
        if hint:
            bits.append(f"\n    args: {hint}")
        lines.append("".join(bits))
    lines.append(
        "Tool rules:\n"
        "- Call a save/record tool as soon as you learn something worth keeping — do not "
        "wait until the end, because the patient may stop replying at any point.\n"
        "- Ask AT MOST ONE question per turn (via `ask_field`, `options`, or one "
        "ask_question tool). Two questions in one turn means the second answer is lost.\n"
        "- Only pass values you actually have. Never invent a value to fill an argument.\n"
        "- Tools are silent to the patient unless they send a message; `reply` is still "
        "what they read."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Turn execution
# --------------------------------------------------------------------------- #

def run_ai_turn(system_prompt: str, history: list[dict], model: str | None = None,
                timeout: int = 20) -> AiTurn:
    """history = [{"role": "user"|"assistant", "content": str}, ...] oldest-first."""
    model = model or DEFAULT_MODEL
    provider = _provider_for_model(model)
    try:
        raw, usage = provider(system_prompt, history, model, timeout)
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001 - any SDK/HTTP error becomes LLMError
        raise LLMError(f"{type(exc).__name__}: {exc}")
    turn = _parse_turn(raw)
    turn.usage = usage
    return turn


def _provider_for_model(model: str):
    if os.getenv("AI_NODE_FAKE") == "1":
        return _fake_chat
    if (model or "").lower().startswith("gemini"):
        return _gemini_chat
    return _openai_chat


def _parse_turn(text: str) -> AiTurn:
    data = _extract_json(text)
    if not isinstance(data, dict):
        raise LLMError("LLM response was not a JSON object.")
    collected = data.get("collected")
    if not isinstance(collected, dict):
        collected = {}
    reply = data.get("reply")
    ask_field = data.get("ask_field")
    options = data.get("options")
    if not isinstance(options, list):
        options = []
    return AiTurn(
        reply=reply if isinstance(reply, str) else "",
        done=bool(data.get("done")),
        collected=collected,
        wants_human=bool(data.get("wants_human")),
        ask_field=ask_field if isinstance(ask_field, str) and ask_field.strip() else None,
        options=[str(o) for o in options if str(o).strip()],
        actions=_parse_actions(data.get("actions")),
    )


def _parse_actions(raw) -> list:
    """Tolerant parse of the `actions` array: anything malformed is dropped
    rather than raised, so one bad tool call never costs the whole turn (the
    patient would get the fallback message for what is really a typo)."""
    if not isinstance(raw, list):
        return []
    calls = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("tool") or item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        args = item.get("args")
        calls.append(AiToolCall(name=name.strip(),
                                args=args if isinstance(args, dict) else {}))
    return calls


def _extract_json(text: str):
    if not text or not text.strip():
        raise LLMError("Empty LLM response.")
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        newline = stripped.find("\n")
        if newline != -1 and stripped[:newline].strip().lower() in ("json", ""):
            stripped = stripped[newline + 1:]
    try:
        return json.loads(stripped)
    except Exception:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(stripped[start:end + 1])
            except Exception as exc:  # noqa: BLE001
                raise LLMError(f"Could not parse JSON from LLM: {exc}")
        raise LLMError("No JSON object found in LLM response.")


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #

def _openai_chat(system_prompt, history, model, timeout) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMError("OPENAI_API_KEY not set.")
    try:
        from openai import OpenAI
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"openai SDK not installed: {exc}")

    client = OpenAI(api_key=api_key, timeout=timeout)
    messages = [{"role": "system", "content": system_prompt}, *history]
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
    )
    u = getattr(response, "usage", None)
    cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
    usage = {
        "prompt": getattr(u, "prompt_tokens", 0) or 0,
        "completion": getattr(u, "completion_tokens", 0) or 0,
        "total": getattr(u, "total_tokens", 0) or 0,
        "cached": cached,
        "model": model,
    }
    return (response.choices[0].message.content or ""), usage


def _gemini_chat(system_prompt, history, model, timeout) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise LLMError("GEMINI_API_KEY not set.")

    contents = [
        {
            "role": "model" if turn["role"] == "assistant" else "user",
            "parts": [{"text": turn["content"]}],
        }
        for turn in history
    ]
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"responseMimeType": "application/json"},
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={api_key}"
    )
    response = requests.post(url, json=body, timeout=timeout)
    if response.status_code >= 400:
        raise LLMError(f"Gemini HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"Gemini returned an unexpected shape: {exc}")
    um = data.get("usageMetadata") or {}
    usage = {
        "prompt": um.get("promptTokenCount", 0),
        "completion": um.get("candidatesTokenCount", 0),
        "total": um.get("totalTokenCount", 0),
        "model": model,
    }
    return text, usage


def _fake_chat(system_prompt, history, model, timeout) -> str:
    """Deterministic stub for local smoke tests (AI_NODE_FAKE=1). Echoes the last
    user turn and never completes on its own — drive completion from the test."""
    last_user = next(
        (turn["content"] for turn in reversed(history) if turn["role"] == "user"),
        "",
    )
    return json.dumps({
        "reply": f"(test) You said: {last_user!r}. Tell me more.",
        "collected": {},
        "done": False,
        "wants_human": False,
    }), {"prompt": 0, "completion": 0, "total": 0, "model": model}
