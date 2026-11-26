"""Lead status names and the from/to record kept when one changes.

The names the clinic picks are stored as written. Two older names are read as
their current names so a lead saved before the rename still matches the list:
"LEAD SAID DNC" is "LEAD WILL REVERT", and "Repeated" is "REPEATED".
"""

from __future__ import annotations

from typing import Any

# Older spellings, compared after uppercasing, and the name we store now.
_RENAMES = {
    "LEAD SAID DNC": "LEAD WILL REVERT",
    "LEAD WILL REVERT": "LEAD WILL REVERT",
    "REPEATED": "REPEATED",
}

# The statuses the leads list offers. Anything else (a sheet value the clinic
# typed by hand) is kept as written.
_CANONICAL = {
    "DID_NOT_CONNECT",
    "FOLLOW_UP_REQUIRED",
    "INTERESTED",
    "APPOINTMENT_REQUESTED",
    "NOT_INTERESTED",
    "REPEATED",
    "STALLED",
    "LEAD WILL REVERT",
}


def canonical_disposition(value: str | None) -> str | None:
    """The status name to store and show. Empty becomes None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    key = text.upper()
    if key in _RENAMES:
        return _RENAMES[key]
    if key in _CANONICAL:
        return key
    return text


def history_entry(previous: str | None, new: str | None, at, source: str = "agent") -> dict[str, Any] | None:
    """One status change, or None when the name did not actually change.

    `new` may already be canonical. `previous` may still be an older spelling;
    both sides are compared after renaming so rewriting "LEAD SAID DNC" to
    "LEAD WILL REVERT" is not recorded as a change.
    """
    old = canonical_disposition(previous)
    nxt = canonical_disposition(new)
    if old == nxt:
        return None
    return {"from": old, "to": nxt, "at": at, "source": source or "agent"}


def history_for_client(items) -> list[dict[str, Any]]:
    """Status changes in the shape the leads page reads."""
    out: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        at = item.get("at")
        if hasattr(at, "isoformat"):
            at = at.isoformat()
        out.append({
            "from": canonical_disposition(item.get("from")),
            "to": canonical_disposition(item.get("to")),
            "at": at,
            "source": item.get("source") or "agent",
        })
    return out
