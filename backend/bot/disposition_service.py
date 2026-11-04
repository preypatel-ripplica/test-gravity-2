"""Pull CRM call outcomes onto the lead's sheet row.

The relay (the Vercel app SSB's dialer posts to) already keeps one document per
Lead_ID in its OWN Mongo: call_attempt_no increments on every re-attempt, the
newest Disposition wins, and Remarks append comma-separated. That is exactly the
shape the sheet wants, so this module only READS it. The sheet is the single
thing we write, because this backend is the only place the Google credentials
live.

Two deliberate properties:

  * The relay's Mongo client is created LAZILY and cached per URI. init_db()
    pings the main cluster during startup; a disposition cluster that is down
    must never be able to stop the backend booting.

  * No sync bookkeeping is stored anywhere. Each sweep re-scans a lookback
    window and writes a cell only when its value actually differs, so replaying
    the same disposition is a no-op and a restart or missed tick self-heals.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pymongo import MongoClient

from backend.bot.google_sheets_service import (
    build_header_index,
    column_index_to_letter,
    find_matching_row_numbers,
    get_valid_google_access_token,
    quote_sheet_name,
    read_sheet_rows,
    batch_update_sheet_values,
)
from backend.bot.models import Client, DispositionSyncConfig
from backend.bot.storage import (
    get_google_connection_by_id,
    find_run_by_lead_id,
    get_conversation_for_contact,
    set_conversation_disposition,
)
from backend.bot.utils import now_utc

# Sheet column -> disposition document field. Lead_ID and MobileNumber are
# deliberately absent: the row already carries both.
DEFAULT_COLUMNS = {
    "CallDateTime": "CallDateTime",
    "AgentID": "AgentID",
    "AgentName": "AgentName",
    "UniqueCallID": "UniqueCallID",
    "Disposition": "Disposition",
    "Remark": "Remark",
    "call_attempt_no": "call_attempt_no",
}

_clients: dict[str, MongoClient] = {}
# Newest received_at seen per client, so a steady state only reads new rows.
_watermarks: dict[str, Any] = {}


def _disposition_collection(config: DispositionSyncConfig):
    """Cached read-only handle on the relay's collection. Lazy by design."""
    client = _clients.get(config.mongo_uri)
    if client is None:
        client = MongoClient(config.mongo_uri, serverSelectionTimeoutMS=8000)
        _clients[config.mongo_uri] = client
    return client[config.db_name][config.collection]


def _google_access_token(config: DispositionSyncConfig, client_id: str) -> str:
    import os

    connection = get_google_connection_by_id(config.google_connection_id)
    if not connection:
        raise RuntimeError(f"google connection '{config.google_connection_id}' not found")
    if connection.client_id != client_id:
        raise RuntimeError("google connection does not belong to this client")

    google_client_id = os.getenv("BOT_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID")
    google_client_secret = (
        os.getenv("BOT_GOOGLE_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET")
    )
    if not google_client_id or not google_client_secret:
        raise RuntimeError(
            "BOT_GOOGLE_CLIENT_ID / BOT_GOOGLE_CLIENT_SECRET are not configured"
        )

    return get_valid_google_access_token(
        connection=connection,
        google_client_id=google_client_id,
        google_client_secret=google_client_secret,
    )


def _cell(value: Any) -> str:
    return "" if value is None else str(value)


def sync_dispositions_for_client(client: Client) -> dict[str, int]:
    """One client's sweep. Returns counts; raises only on a hard config error."""
    config = client.disposition_sync
    stats = {"read": 0, "matched": 0, "updated": 0}
    if not config or not config.enabled or not config.mongo_uri:
        return stats
    if not config.spreadsheet_id or not config.google_connection_id:
        return stats

    columns = config.columns or DEFAULT_COLUMNS

    # Re-scan a window rather than trusting the watermark alone, so a restart or
    # a tick that died mid-write recovers without any stored state.
    floor = now_utc() - timedelta(hours=max(1, config.lookback_hours))
    since = _watermarks.get(client.id)
    cutoff = min(since, floor) if since else floor

    documents = list(
        _disposition_collection(config).find({"received_at": {"$gte": cutoff.isoformat()}})
    )
    stats["read"] = len(documents)
    if not documents:
        return stats

    token = _google_access_token(config, client.id)
    rows = read_sheet_rows(
        spreadsheet_id=config.spreadsheet_id,
        sheet_name=config.sheet_name,
        access_token=token,
    )
    if not rows:
        return stats

    header_index = build_header_index(rows[0])
    if config.key_column not in header_index:
        raise RuntimeError(
            f"sheet has no '{config.key_column}' column to match Lead_ID against")

    missing = [column for column in columns if column not in header_index]
    if missing:
        raise RuntimeError(f"sheet is missing disposition columns: {missing}")

    key_index = header_index[config.key_column]
    updates: list[dict[str, Any]] = []
    newest = since

    for document in documents:
        lead_id = document.get("Lead_ID")
        if not lead_id:
            continue

        received = document.get("received_at")
        if received and (newest is None or str(received) > str(newest)):
            newest = received

        matches = find_matching_row_numbers(rows, key_index, lead_id)
        if not matches:
            # A lead from another tenant or an older sheet - not an error.
            continue
        stats["matched"] += 1

        # CRM: also store the outcome on the conversation, found via the run
        # that generated this lead_id. Best-effort and isolated - the sheet
        # write below must never depend on it.
        try:
            run = find_run_by_lead_id(client.id, lead_id)
            conversation = (
                get_conversation_for_contact(run.whatsapp_account_id, run.contact_phone)
                if run else None
            )
            if conversation:
                set_conversation_disposition(
                    conversation.id,
                    disposition=_cell(document.get("Disposition")) or None,
                    disposition_remark=_cell(document.get("Remark")) or None,
                    disposition_updated_at=now_utc(),
                )
                stats["crm_updated"] = stats.get("crm_updated", 0) + 1
        except Exception as error:  # noqa: BLE001
            print(f"DISPOSITION -> CRM write failed for {lead_id}: {error}", flush=True)

        for column, field in columns.items():
            column_index = header_index[column]
            wanted = _cell(document.get(field))

            row = rows[matches[0] - 1]
            current = _cell(row[column_index]) if column_index < len(row) else ""
            if current == wanted:
                continue  # already correct - don't spend a write on it

            letter = column_index_to_letter(column_index)
            updates.append({
                "range": f"{quote_sheet_name(config.sheet_name)}!{letter}{matches[0]}",
                "values": [[wanted]],
            })

    if updates:
        batch_update_sheet_values(
            spreadsheet_id=config.spreadsheet_id,
            updates=updates,
            value_input_option="RAW",
            access_token=token,
        )
        stats["updated"] = len(updates)

    if newest:
        _watermarks[client.id] = (
            newest if hasattr(newest, "isoformat") else now_utc()
        )
    return stats


def sync_all_dispositions() -> None:
    """Sweep every client with the sync enabled. Never raises - one client's
    broken config or unreachable cluster must not stop the others, nor the
    heartbeat that also runs the inactivity timeout."""
    from backend.bot.storage import list_clients

    try:
        _, clients = list_clients(status="active", limit=200, offset=0)
    except Exception as error:  # noqa: BLE001
        print(f"DISPOSITION SYNC: could not list clients: {error}", flush=True)
        return

    for client in clients:
        config = getattr(client, "disposition_sync", None)
        if not config or not config.enabled:
            continue
        try:
            stats = sync_dispositions_for_client(client)
            if stats["updated"]:
                print(f"DISPOSITION SYNC {client.id}: read={stats['read']} "
                      f"matched={stats['matched']} cells={stats['updated']}", flush=True)
        except Exception as error:  # noqa: BLE001
            print(f"DISPOSITION SYNC FAILED for {client.id}: "
                  f"{type(error).__name__}: {error}", flush=True)
