"""Client-level tracker deliverables, start week, and did-not-track helpers."""

from __future__ import annotations

from datetime import date
from calendar import monthrange

from backend.tg.services.tracker_sheet import week_end_date, weeks_in_month

MARKING_NONE = "none"
MARKING_DID_NOT_TRACK = "did_not_track"
MARKING_MISSED = MARKING_DID_NOT_TRACK  # legacy alias
_LEGACY_MARKING = {"missed": MARKING_DID_NOT_TRACK}


def normalize_marking(value) -> str:
    text = str(value or "").strip() or MARKING_NONE
    if text in _LEGACY_MARKING:
        return _LEGACY_MARKING[text]
    if text in (MARKING_NONE, MARKING_DID_NOT_TRACK):
        return text
    return MARKING_NONE


def is_did_not_track(value) -> bool:
    return normalize_marking(value) == MARKING_DID_NOT_TRACK

DELIVERABLE_FAMILIES = ("video", "static_post", "blog", "paid_ads")
VIDEO_FORMATS = ("long", "short")
MAX_SLOTS_PER_FAMILY = 24
WEEKS_IN_TRACKER_MONTH = 4
DELIVERABLES_PERIOD_MONTH = "month"
CARD_TYPE_ORDER = ("long_video", "short", "static_post", "blog", "paid_ads")
# Remainder extras go to weeks 2 and 4 first, then 1 and 3. 4 → 1-1-1-1, 6 → 1-2-1-2.
REMAINDER_WEEK_INDEXES = (1, 3, 0, 2)

DEFAULT_DELIVERABLE_SLOTS = [
    {"type": "video", "format": "long"},
    {"type": "video", "format": "short"},
    {"type": "static_post"},
    {"type": "blog"},
]

_LEGACY_STRING_TO_SLOT = {
    "long_video": {"type": "video", "format": "long"},
    "short": {"type": "video", "format": "short"},
    "static_post": {"type": "static_post"},
    "blog": {"type": "blog"},
    "paid_ads": {"type": "paid_ads"},
    "video": {"type": "video", "format": "long"},
}


def _slot_dict(family: str, video_format: str | None = None) -> dict:
    if family == "video":
        return {"type": "video", "format": video_format if video_format in VIDEO_FORMATS else "long"}
    return {"type": family}


def normalize_slot(item) -> dict | None:
    if isinstance(item, str):
        mapped = _LEGACY_STRING_TO_SLOT.get(item.strip())
        return dict(mapped) if mapped else None
    if not isinstance(item, dict):
        return None
    family = str(item.get("type") or "").strip()
    if family in _LEGACY_STRING_TO_SLOT and family not in DELIVERABLE_FAMILIES:
        mapped = dict(_LEGACY_STRING_TO_SLOT[family])
        fmt = str(item.get("format") or mapped.get("format") or "").strip()
        if mapped.get("type") == "video":
            return _slot_dict("video", fmt or mapped.get("format"))
        return mapped
    if family not in DELIVERABLE_FAMILIES:
        return None
    if family == "video":
        return _slot_dict("video", str(item.get("format") or "long").strip())
    return _slot_dict(family)


def normalize_deliverables(raw) -> list[dict]:
    if raw is None or not isinstance(raw, (list, tuple)):
        return [dict(slot) for slot in DEFAULT_DELIVERABLE_SLOTS]
    out: list[dict] = []
    counts: dict[str, int] = {}
    for item in raw:
        slot = normalize_slot(item)
        if not slot:
            continue
        family = slot["type"]
        counts[family] = counts.get(family, 0) + 1
        if counts[family] > MAX_SLOTS_PER_FAMILY:
            continue
        out.append(slot)
    return out


def slot_to_card_type(slot: dict) -> str:
    family = slot.get("type")
    if family == "video":
        return "long_video" if slot.get("format") == "long" else "short"
    return str(family or "")


def card_type_to_slot(card_type: str) -> dict | None:
    if card_type == "long_video":
        return {"type": "video", "format": "long"}
    if card_type == "short":
        return {"type": "video", "format": "short"}
    if card_type in ("static_post", "blog", "paid_ads"):
        return {"type": card_type}
    return None


def slots_from_card_types(types) -> list[dict]:
    out: list[dict] = []
    for card_type in types or []:
        slot = card_type_to_slot(str(card_type or ""))
        if slot:
            out.append(slot)
    return out


def card_types_from_slots(raw) -> list[str]:
    return [slot_to_card_type(slot) for slot in normalize_deliverables(raw)]


def allowed_card_types(raw) -> list[str]:
    seen: list[str] = []
    for card_type in card_types_from_slots(raw):
        if card_type and card_type not in seen:
            seen.append(card_type)
    return seen


def _slots_signature(raw) -> tuple[str, ...]:
    return tuple(card_types_from_slots(raw))


def is_monthly_deliverables(client: dict | None) -> bool:
    return isinstance(client, dict) and client.get("tracker_deliverables_period") == DELIVERABLES_PERIOD_MONTH


def expand_weekly_slots_to_monthly(raw) -> list[dict]:
    weekly = normalize_deliverables(raw)
    return [dict(slot) for slot in weekly for _ in range(WEEKS_IN_TRACKER_MONTH)]


def stored_monthly_slots(client: dict | None) -> list[dict]:
    raw = client.get("tracker_deliverables") if isinstance(client, dict) else None
    slots = normalize_deliverables(raw)
    if is_monthly_deliverables(client):
        return slots
    return expand_weekly_slots_to_monthly(slots)


def week_share_counts(total: int, week_count: int = WEEKS_IN_TRACKER_MONTH) -> list[int]:
    total = max(0, int(total or 0))
    week_count = max(1, int(week_count))
    base, rem = divmod(total, week_count)
    counts = [base] * week_count
    extra_at = REMAINDER_WEEK_INDEXES
    if week_count != WEEKS_IN_TRACKER_MONTH:
        extra_at = tuple(range(week_count - 1, -1, -1))
    for index in range(rem):
        counts[extra_at[index % week_count]] += 1
    return counts


def _interleave_long_short(slots: list[dict]) -> list[dict]:
    longs = [slot for slot in slots if slot_to_card_type(slot) == "long_video"]
    shorts = [slot for slot in slots if slot_to_card_type(slot) == "short"]
    mixed: list[dict] = []
    while longs or shorts:
        if longs:
            mixed.append(longs.pop(0))
        if shorts:
            mixed.append(shorts.pop(0))
    return mixed


def split_slots_across_weeks(raw) -> list[list[dict]]:
    """Split each family evenly. Videos (long+short) are one pool so 6 → 1-2-1-2, not 2-2-0-2."""
    grouped: dict[str, list[dict]] = {family: [] for family in DELIVERABLE_FAMILIES}
    unknown: list[dict] = []
    for slot in normalize_deliverables(raw):
        family = slot.get("type")
        if family in grouped:
            grouped[family].append(dict(slot))
        else:
            unknown.append(dict(slot))
    grouped["video"] = _interleave_long_short(grouped["video"])
    weeks: list[list[dict]] = [[] for _ in range(WEEKS_IN_TRACKER_MONTH)]
    for family in DELIVERABLE_FAMILIES:
        group = grouped[family]
        counts = week_share_counts(len(group))
        cursor = 0
        for week_index, count in enumerate(counts):
            weeks[week_index].extend(group[cursor:cursor + count])
            cursor += count
    if unknown:
        counts = week_share_counts(len(unknown))
        cursor = 0
        for week_index, count in enumerate(counts):
            weeks[week_index].extend(unknown[cursor:cursor + count])
            cursor += count
    return weeks


def clip_shares_for_start(shares: list[list[dict]], client: dict | None, year: int, month: int) -> list[list[dict]]:
    """Joining week 3 keeps weeks 3–4 of the even split (half a month). Week 1 keeps the full month."""
    out = [list(row) for row in shares]
    start = tracker_start_tuple(client) if isinstance(client, dict) else None
    if not start or start[0] != int(year) or start[1] != int(month):
        return out
    for index in range(max(0, start[2] - 1)):
        if index < len(out):
            out[index] = []
    return out


def next_month_tuple(year: int, month: int) -> tuple[int, int]:
    if month >= 12:
        return year + 1, 1
    return year, month + 1


def deliverable_change_from_month(client: dict | None, today: date | None = None) -> tuple[int, int]:
    year, month, _week = current_week_tuple(today)
    start = tracker_start_tuple(client) if isinstance(client, dict) else None
    if start and (start[0], start[1]) > (year, month):
        return start[0], start[1]
    return year, month


def monthly_counts_changed(client: dict | None, new_slots, today: date | None = None) -> bool:
    year, month, _week = current_week_tuple(today)
    current = monthly_slots_for_month(client, year, month)
    return _slots_signature(current) != _slots_signature(new_slots)


def _history_entry_is_monthly(item: dict) -> bool:
    if item.get("period") == DELIVERABLES_PERIOD_MONTH:
        return True
    week = item.get("week")
    return week in (None, 0, "")


def normalize_weekly_deliverable_history(raw) -> list[dict]:
    rows: list[dict] = []
    for item in raw or []:
        if not isinstance(item, dict) or _history_entry_is_monthly(item):
            continue
        try:
            year = int(item.get("year"))
            month = int(item.get("month"))
            week = int(item.get("week"))
        except (TypeError, ValueError):
            continue
        if year < 2000 or year > 2100 or month < 1 or month > 12 or week < 1 or week > 4:
            continue
        rows.append({
            "year": year,
            "month": month,
            "week": week,
            "slots": normalize_deliverables(item.get("slots")),
        })
    rows.sort(key=lambda row: (row["year"], row["month"], row["week"]))
    collapsed: list[dict] = []
    for row in rows:
        key = (row["year"], row["month"], row["week"])
        if collapsed and (collapsed[-1]["year"], collapsed[-1]["month"], collapsed[-1]["week"]) == key:
            collapsed[-1] = row
        else:
            collapsed.append(row)
    return collapsed


def normalize_monthly_deliverable_history(raw) -> list[dict]:
    rows: list[dict] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        try:
            year = int(item.get("year"))
            month = int(item.get("month"))
        except (TypeError, ValueError):
            continue
        if year < 2000 or year > 2100 or month < 1 or month > 12:
            continue
        slots = normalize_deliverables(item.get("slots"))
        if not _history_entry_is_monthly(item):
            slots = expand_weekly_slots_to_monthly(item.get("slots"))
        rows.append({"year": year, "month": month, "slots": slots})
    rows.sort(key=lambda row: (row["year"], row["month"]))
    collapsed: list[dict] = []
    for row in rows:
        key = (row["year"], row["month"])
        if collapsed and (collapsed[-1]["year"], collapsed[-1]["month"]) == key:
            collapsed[-1] = row
        else:
            collapsed.append(row)
    return collapsed


def normalize_deliverable_history(raw) -> list[dict]:
    return normalize_weekly_deliverable_history(raw)


def deliverable_history(client: dict | None) -> list[dict]:
    if not isinstance(client, dict):
        return [{
            "year": 2000,
            "month": 1,
            "week": 1,
            "slots": normalize_deliverables(None),
        }]
    rows = normalize_weekly_deliverable_history(client.get("tracker_deliverable_history"))
    if rows:
        return rows
    start = tracker_start_tuple(client) or (2000, 1, 1)
    return [{
        "year": start[0],
        "month": start[1],
        "week": start[2],
        "slots": normalize_deliverables(client.get("tracker_deliverables")),
    }]


def monthly_history(client: dict | None) -> list[dict]:
    if not isinstance(client, dict):
        return [{
            "year": 2000,
            "month": 1,
            "slots": stored_monthly_slots(None),
        }]
    rows = normalize_monthly_deliverable_history(client.get("tracker_deliverable_history"))
    if rows:
        return rows
    start = tracker_start_tuple(client) or (2000, 1, 1)
    return [{
        "year": start[0],
        "month": start[1],
        "slots": stored_monthly_slots(client),
    }]


def monthly_slots_for_month(client: dict | None, year: int, month: int) -> list[dict]:
    key = (int(year), int(month))
    chosen = None
    for entry in monthly_history(client):
        entry_key = (entry["year"], entry["month"])
        if entry_key <= key:
            chosen = entry
        else:
            break
    if chosen:
        return [dict(slot) for slot in chosen["slots"]]
    return stored_monthly_slots(client)


def normalize_week_slot_plan(raw) -> list[dict]:
    rows: list[dict] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        try:
            year = int(item.get("year"))
            month = int(item.get("month"))
            week = int(item.get("week"))
        except (TypeError, ValueError):
            continue
        if year < 2000 or year > 2100 or month < 1 or month > 12 or week < 1 or week > 4:
            continue
        rows.append({
            "year": year,
            "month": month,
            "week": week,
            "slots": normalize_deliverables(item.get("slots")),
        })
    rows.sort(key=lambda row: (row["year"], row["month"], row["week"]))
    collapsed: list[dict] = []
    for row in rows:
        key = (row["year"], row["month"], row["week"])
        if collapsed and (collapsed[-1]["year"], collapsed[-1]["month"], collapsed[-1]["week"]) == key:
            collapsed[-1] = row
        else:
            collapsed.append(row)
    return collapsed


def week_slot_plan_for(client: dict | None, year: int, month: int, week: int) -> list[dict] | None:
    if not isinstance(client, dict):
        return None
    key = (int(year), int(month), int(week))
    for entry in normalize_week_slot_plan(client.get("tracker_week_slot_plan")):
        if (entry["year"], entry["month"], entry["week"]) == key:
            return [dict(slot) for slot in entry["slots"]]
    return None


def merge_week_slot_plan(existing, extra) -> list[dict]:
    index = {
        (row["year"], row["month"], row["week"]): row
        for row in normalize_week_slot_plan(existing)
    }
    for row in normalize_week_slot_plan(extra):
        index[(row["year"], row["month"], row["week"])] = row
    return [index[key] for key in sorted(index)]


def _legacy_slots_for_week(client: dict | None, year: int, month: int, week: int) -> list[dict]:
    key = (int(year), int(month), int(week))
    chosen = None
    for entry in deliverable_history(client):
        entry_key = (entry["year"], entry["month"], entry["week"])
        if entry_key <= key:
            chosen = entry
        else:
            break
    if chosen:
        return [dict(slot) for slot in chosen["slots"]]
    return normalize_deliverables(client.get("tracker_deliverables") if isinstance(client, dict) else None)


def slots_for_week(client: dict | None, year: int, month: int, week: int) -> list[dict]:
    if week_is_before_start(client, year, month, week):
        return []
    planned = week_slot_plan_for(client, year, month, week)
    if planned is not None:
        return planned
    week_i = int(week)
    if is_monthly_deliverables(client) and 1 <= week_i <= WEEKS_IN_TRACKER_MONTH:
        shares = clip_shares_for_start(
            split_slots_across_weeks(monthly_slots_for_month(client, year, month)),
            client,
            year,
            month,
        )
        return [dict(slot) for slot in shares[week_i - 1]]
    return _legacy_slots_for_week(client, year, month, week)


def current_week_tuple(today: date | None = None) -> tuple[int, int, int]:
    today = today or date.today()
    return today.year, today.month, week_of_day(today.day)


LEGACY_TRACKER_START = (2026, 10, 1)


def remaining_weeks_this_month(client: dict | None, today: date | None = None) -> list[int]:
    year, month, week = current_week_tuple(today)
    remaining = list(range(week, WEEKS_IN_TRACKER_MONTH + 1))
    start = tracker_start_tuple(client) if isinstance(client, dict) else None
    if start and start[0] == year and start[1] == month:
        remaining = [item for item in remaining if item >= start[2]]
    return remaining


def even_month_slot_plan(new_slots, year: int, month: int, weeks=None, client: dict | None = None) -> list[dict]:
    shares = clip_shares_for_start(split_slots_across_weeks(new_slots), client, year, month)
    week_ids = list(weeks) if weeks is not None else list(range(1, WEEKS_IN_TRACKER_MONTH + 1))
    return [
        {"year": int(year), "month": int(month), "week": week, "slots": [dict(slot) for slot in shares[week - 1]]}
        for week in week_ids
        if 1 <= int(week) <= WEEKS_IN_TRACKER_MONTH
    ]


def remaining_week_slot_plan(client: dict | None, new_slots, today: date | None = None) -> list[dict]:
    """Give each remaining week its even monthly share (4 → 1-1-1-1, 6 → 1-2-1-2)."""
    year, month, _week = current_week_tuple(today)
    remaining = remaining_weeks_this_month(client, today)
    if not remaining:
        return []
    return even_month_slot_plan(new_slots, year, month, remaining, client=client)


def record_deliverable_change(client: dict | None, new_slots, today: date | None = None) -> list[dict]:
    """Store monthly totals from this month. Weeks before tracker start stay empty."""
    slots = normalize_deliverables(new_slots)
    history = monthly_history(client)
    from_month = deliverable_change_from_month(client, today)
    last = history[-1]
    if (
        _slots_signature(last["slots"]) == _slots_signature(slots)
        and (last["year"], last["month"]) <= from_month
    ):
        return history
    entry = {"year": from_month[0], "month": from_month[1], "slots": slots}
    if (last["year"], last["month"]) == from_month:
        history[-1] = entry
    else:
        history.append(entry)
    return history


def tracker_start_tuple(client: dict | None) -> tuple[int, int, int] | None:
    if not isinstance(client, dict):
        return None
    try:
        year = int(client.get("tracker_start_year"))
        month = int(client.get("tracker_start_month"))
        week = int(client.get("tracker_start_week"))
    except (TypeError, ValueError):
        return None
    if year < 2000 or year > 2100 or month < 1 or month > 12 or week < 1 or week > 4:
        return None
    return year, month, week


def week_is_before_start(client: dict | None, year: int, month: int, week: int) -> bool:
    start = tracker_start_tuple(client)
    if not start:
        return False
    return (int(year), int(month), int(week)) < start


def week_is_before_current(year: int, month: int, week: int, today: date | None = None) -> bool:
    return (int(year), int(month), int(week)) < current_week_tuple(today)


def has_delay_proof(row: dict | None, *, require_files: bool | None = None) -> bool:
    if not isinstance(row, dict):
        return False
    reason = str(row.get("delay_reason") or "").strip()
    if not reason:
        return False
    if require_files is None:
        from backend.main.config import TRACKER_DELAY_PROOF_REQUIRED
        require_files = TRACKER_DELAY_PROOF_REQUIRED
    if not require_files:
        return True
    proofs = row.get("delay_proofs") or []
    if not isinstance(proofs, list):
        return False
    return any(
        isinstance(item, dict) and str(item.get("url") or "").strip()
        for item in proofs
    )


def week_start_day(week: int) -> int:
    if int(week) <= 1:
        return 1
    if int(week) == 2:
        return 8
    if int(week) == 3:
        return 15
    return 22


def due_date_is_before_current_week(due_date: str, today: date | None = None) -> bool:
    raw = str(due_date or "").strip()[:10]
    if len(raw) < 10 or raw[4] != "-" or raw[7] != "-":
        return False
    today = today or date.today()
    year, month, week = current_week_tuple(today)
    start = date(year, month, week_start_day(week))
    try:
        year_n, month_n, day_n = (int(part) for part in raw.split("-"))
        return date(year_n, month_n, day_n) < start
    except ValueError:
        return False


def week_of_day(day: int) -> int:
    if day <= 7:
        return 1
    if day <= 14:
        return 2
    if day <= 21:
        return 3
    return 4


def week_has_ended(year: int, month: int, week: int, today: date | None = None) -> bool:
    today = today or date.today()
    end = week_end_date(year, month, week)
    if not end:
        return True
    y, m, d = (int(part) for part in end.split("-"))
    return date(y, m, d) < today


def last_ended_week(today: date | None = None) -> tuple[int, int, int] | None:
    today = today or date.today()
    year, month, week = today.year, today.month, week_of_day(today.day)
    if week_has_ended(year, month, week, today):
        return year, month, week
    if week > 1:
        prev = week - 1
        while prev >= 1:
            if prev in weeks_in_month(year, month):
                return year, month, prev
            prev -= 1
    month -= 1
    if month < 1:
        month = 12
        year -= 1
    available = weeks_in_month(year, month)
    if not available:
        return None
    return year, month, available[-1]


def iter_weeks_inclusive(
    start: tuple[int, int, int],
    end: tuple[int, int, int],
):
    year, month = start[0], start[1]
    while (year, month) <= (end[0], end[1]):
        for week in weeks_in_month(year, month):
            key = (year, month, week)
            if key < start:
                continue
            if key > end:
                return
            yield key
        month += 1
        if month > 12:
            month = 1
            year += 1


def parse_onboarding_date(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        date.fromisoformat(text)
    except ValueError:
        raise ValueError("onboarding_date must be YYYY-MM-DD") from None
    return text


def week_option_bounds(year: int, month: int) -> list[dict]:
    last = monthrange(year, month)[1]
    rows = [
        {"week": 1, "start": 1, "end": min(7, last)},
        {"week": 2, "start": 8, "end": min(14, last)},
        {"week": 3, "start": 15, "end": min(21, last)},
        {"week": 4, "start": 22, "end": last},
    ]
    return [row for row in rows if row["start"] <= last]
