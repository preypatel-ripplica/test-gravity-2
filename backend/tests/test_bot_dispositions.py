"""Status names and the from/to record. No database."""

from datetime import datetime, timezone

from backend.bot.dispositions import canonical_disposition, history_entry, history_for_client


def test_renames_keep_every_status_in_caps():
    assert canonical_disposition("LEAD SAID DNC") == "LEAD WILL REVERT"
    assert canonical_disposition("lead said dnc") == "LEAD WILL REVERT"
    assert canonical_disposition("Repeated") == "REPEATED"
    assert canonical_disposition("interested") == "INTERESTED"
    assert canonical_disposition("FOLLOW_UP_REQUIRED") == "FOLLOW_UP_REQUIRED"
    assert canonical_disposition("  ") is None
    assert canonical_disposition(None) is None
    # A sheet value that is not one of the listed statuses stays as written.
    assert canonical_disposition("Call back later") == "Call back later"


def test_same_status_after_rename_is_not_a_change():
    at = datetime(2026, 11, 26, tzinfo=timezone.utc)
    assert history_entry("LEAD SAID DNC", "LEAD WILL REVERT", at) is None
    assert history_entry("Repeated", "REPEATED", at) is None
    assert history_entry("FOLLOW_UP_REQUIRED", "FOLLOW_UP_REQUIRED", at) is None


def test_status_change_records_from_to_and_when():
    at = datetime(2026, 11, 26, 7, 15, tzinfo=timezone.utc)
    entry = history_entry("NOT_INTERESTED", "LEAD WILL REVERT", at, "agent")
    assert entry == {
        "from": "NOT_INTERESTED",
        "to": "LEAD WILL REVERT",
        "at": at,
        "source": "agent",
    }
    cleared = history_entry("STALLED", None, at, "sync")
    assert cleared["from"] == "STALLED"
    assert cleared["to"] is None
    assert cleared["source"] == "sync"


def test_history_for_client_uses_current_names():
    at = datetime(2026, 11, 7, 9, 0, tzinfo=timezone.utc)
    rows = history_for_client([
        {"from": "LEAD SAID DNC", "to": "Repeated", "at": at, "source": "agent"},
        "skip",
    ])
    assert rows == [{
        "from": "LEAD WILL REVERT",
        "to": "REPEATED",
        "at": at.isoformat(),
        "source": "agent",
    }]
