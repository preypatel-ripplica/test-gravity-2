"""Shared helpers with no project dependencies (import-safe from any module).

Two groups live here:
  1. id / clock: now_utc, short_id.
  2. @variable templating: resolve_runtime_text + render_text and their helpers,
     used to substitute stored run variables (@name, @contact.phone, @items[0])
     into message/question text and Google Sheet cell mappings.

Keeping these dependency-free (no imports from other project modules) is the
invariant that lets any module import them without circular-import risk.
"""

from __future__ import annotations


import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def short_id() -> str:
    return uuid4().hex[:10]


# ---------------------------------------------------------------------------
# @variable templating
# ---------------------------------------------------------------------------

# Matches @name, @contact.phone, @result.items[0].name in free text. The
# lookbehind stops it firing mid-word or after a dot (e.g. an email like
# support@shop.com is left alone).
VARIABLE_PATTERN = re.compile(
    r"(?<![\w.])@([A-Za-z_][A-Za-z0-9_]*(?:(?:\.[A-Za-z_][A-Za-z0-9_]*)|(?:\[\d+\]))*)"
)

# Splits a path like "items[0].name" into name / [index] tokens.
PATH_TOKEN_PATTERN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")

# Sentinel for "path not found" (distinct from a stored value of None).
MISSING = object()


def stringify_variable_value(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)

    return str(value)


def parse_variable_path(path: str) -> list[str | int] | None:
    """Convert a variable path into pieces.

    Converts:
        result.message.text
        result.items[0].name
    Into:
        ["result", "message", "text"]
        ["result", "items", 0, "name"]
    """
    tokens: list[str | int] = []
    index = 0

    while index < len(path):
        match = PATH_TOKEN_PATTERN.match(path, index)

        if not match:
            return None

        key_token = match.group(1)
        index_token = match.group(2)

        if key_token is not None:
            tokens.append(key_token)

        elif index_token is not None:
            tokens.append(int(index_token))

        index = match.end()

        if index < len(path):
            if path[index] == ".":
                index += 1
                continue

            if path[index] == "[":
                continue

            return None

    return tokens


def get_value_by_path(
    variables: dict[str, Any],
    path: str,
) -> Any:
    tokens = parse_variable_path(path)

    if not tokens:
        return MISSING

    current: Any = variables

    for token in tokens:
        if isinstance(token, str):
            if not isinstance(current, dict):
                return MISSING

            if token not in current:
                return MISSING

            current = current[token]

        elif isinstance(token, int):
            if not isinstance(current, list):
                return MISSING

            if token < 0 or token >= len(current):
                return MISSING

            current = current[token]

    return current


def resolve_runtime_text(
    text: str,
    variables: dict[str, Any],
) -> tuple[str, list[str], list[str]]:
    """Substitute @variables in text. Returns (resolved_text, resolved_paths,
    missing_paths).

    Example:
        "Hi @name. First item is @result.items[0].name. City is @city."
      -> "Hi Rahul. First item is Shirt. City is @city."
         resolved = ["name", "result.items[0].name"]
         missing  = ["city"]

    Important: a missing variable is left as its original @variable text (never
    raises), so a bad reference degrades gracefully instead of breaking a reply.
    """
    if not isinstance(text, str):
        return text, [], []

    resolved_variables: list[str] = []
    missing_variables: list[str] = []

    def replace_variable(match: re.Match) -> str:
        variable_path = match.group(1)

        value = get_value_by_path(
            variables=variables,
            path=variable_path,
        )

        if value is MISSING:
            missing_variables.append(variable_path)
            # Keep @variable.path as-is when the value is not found.
            return match.group(0)

        resolved_variables.append(variable_path)
        return stringify_variable_value(value)

    resolved_text = VARIABLE_PATTERN.sub(replace_variable, text)

    return resolved_text, resolved_variables, missing_variables


def render_text(text: str, variables: dict[str, Any]) -> str:
    """Convenience wrapper: substitute @variables and return just the resolved
    string (dropping the resolved/missing lists). For message and question text
    where only the rendered output matters."""
    return resolve_runtime_text(text, variables)[0]
