"""Google Sheets node runtime: mint an access token from a stored refresh
token, then insert or update rows via the Sheets REST API using plain requests.

All Google API logic lives here so the workflow engine's runner
(_run_google_sheets_node in services.py) stays thin. Any failure raises
RuntimeError, which the orchestrator turns into a GoogleSheetsExecutionResult
with status="failed" - the runner then fails the workflow run.
"""

from __future__ import annotations


import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests

from backend.bot.models import (
    GoogleConnection,
    GoogleSheetsConfig,
    WorkflowRun,
)
from backend.bot.storage import (
    get_google_connection_by_id,
    save_google_connection,
)
from backend.bot.utils import resolve_runtime_text


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS_BASE_URL = "https://sheets.googleapis.com/v4/spreadsheets"

# Sheets/token calls retry on transient failures (timeouts, connection errors,
# 429/5xx). A one-off Google blip must not fail a live run: on 10 Sep 2026 a
# single 20s read timeout on the entry sheet-insert dropped a brand-new lead
# before the welcome could go out. A persistent failure still surfaces, so the
# flow fails - the sheet write is mandatory.
SHEETS_TIMEOUT = 30
SHEETS_RETRIES = 2  # 3 attempts total, backoff 1s then 2s
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


def _sheets_request(method: str, url: str, *, error_prefix: str, **kwargs) -> requests.Response:
    """requests.request with retry + backoff on transient failures. Non-transient
    responses (2xx/4xx) return immediately so callers keep their existing
    `>= 400` handling. After exhausting retries the last transient response is
    returned (the caller raises), or a RuntimeError wraps the last network
    exception."""
    kwargs.setdefault("timeout", SHEETS_TIMEOUT)
    last_exc: Exception | None = None
    last_resp: requests.Response | None = None
    for attempt in range(SHEETS_RETRIES + 1):
        try:
            resp = requests.request(method, url, **kwargs)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc, last_resp = exc, None
        else:
            if resp.status_code not in _TRANSIENT_STATUS:
                return resp
            last_resp, last_exc = resp, None
        if attempt < SHEETS_RETRIES:
            wait = 1.0 * (attempt + 1)
            reason = last_exc if last_exc is not None else f"HTTP {last_resp.status_code}"
            print(f"GOOGLE SHEETS RETRY {attempt + 1}/{SHEETS_RETRIES}: {method} {url} "
                  f"-> {reason}; retrying in {wait:.0f}s", flush=True)
            time.sleep(wait)
    if last_resp is not None:
        return last_resp
    raise RuntimeError(f"{error_prefix}: {type(last_exc).__name__}: {last_exc}")


@dataclass
class GoogleSheetsExecutionResult:
    status: str
    metadata: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def get_valid_google_access_token(
    connection: GoogleConnection,
    google_client_id: str,
    google_client_secret: str,
) -> str:
    """Exchange the stored refresh token for a fresh access token and persist
    it on the connection. Refreshing needs the app's client id + secret even
    though the refresh token was generated once, manually."""
    response = _sheets_request(
        "POST",
        GOOGLE_TOKEN_URL,
        error_prefix="Google token refresh failed",
        data={
            "client_id": google_client_id,
            "client_secret": google_client_secret,
            "refresh_token": connection.refresh_token,
            "grant_type": "refresh_token",
        },
    )

    if response.status_code >= 400:
        raise RuntimeError(
            f"Google token refresh failed: {response.status_code} {response.text}"
        )

    token_data = response.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise RuntimeError("Google token refresh returned no access_token.")

    connection.access_token = access_token
    save_google_connection(connection)

    return access_token


# ---------------------------------------------------------------------------
# A1 range helpers
# ---------------------------------------------------------------------------

def quote_sheet_name(sheet_name: str) -> str:
    """Always single-quote the sheet name so names with spaces work: 'Sheet 1'."""
    escaped = sheet_name.replace("'", "''")
    return f"'{escaped}'"


def column_index_to_letter(index: int) -> str:
    """0 -> A, 1 -> B, 25 -> Z, 26 -> AA."""
    result = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


# ---------------------------------------------------------------------------
# Read headers / rows
# ---------------------------------------------------------------------------

def read_sheet_headers(
    spreadsheet_id: str,
    sheet_name: str,
    access_token: str,
) -> list[str]:
    range_name = f"{quote_sheet_name(sheet_name)}!1:1"
    url = f"{SHEETS_BASE_URL}/{spreadsheet_id}/values/{range_name}"

    response = _sheets_request(
        "GET",
        url,
        error_prefix="Failed to read sheet headers",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Failed to read sheet headers: {response.status_code} {response.text}"
        )

    values = response.json().get("values", [])
    if not values or not values[0]:
        raise RuntimeError("Sheet header row is empty. Please add headers in row 1.")

    return values[0]


def build_header_index(headers: list[str]) -> dict[str, int]:
    """Map exact header text -> column index. Duplicate headers are rejected."""
    header_to_index: dict[str, int] = {}
    for index, header in enumerate(headers):
        if header in header_to_index:
            raise RuntimeError(f"Duplicate header found in sheet: '{header}'")
        header_to_index[header] = index
    return header_to_index


def read_sheet_rows(
    spreadsheet_id: str,
    sheet_name: str,
    access_token: str,
) -> list[list[Any]]:
    range_name = f"{quote_sheet_name(sheet_name)}!A:ZZZ"
    url = f"{SHEETS_BASE_URL}/{spreadsheet_id}/values/{range_name}"

    response = _sheets_request(
        "GET",
        url,
        error_prefix="Failed to read sheet rows",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Failed to read sheet rows: {response.status_code} {response.text}"
        )

    return response.json().get("values", [])


# ---------------------------------------------------------------------------
# Resolve mappings (via @variable resolver)
# ---------------------------------------------------------------------------

# NOW()/TODAY() are volatile in Sheets - Google recomputes them on every open,
# so a literal "=NOW()" mapping resets every row's timestamp to "today". We write
# a STATIC timestamp instead. Timezone matches what NOW() showed (IST clients).
GOOGLE_SHEETS_TIMEZONE = os.getenv("GOOGLE_SHEETS_TIMEZONE", "Asia/Kolkata")


def _static_value_for_volatile_formula(value: Any) -> Optional[str]:
    """If a resolved mapping value is a volatile date formula (=NOW()/=TODAY()),
    return a static timestamp string (ISO, so USER_ENTERED parses it into a real,
    unchanging date). Returns None for any other value (left untouched)."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper().replace(" ", "")
    if normalized not in ("=NOW()", "=TODAY()"):
        return None
    try:
        now = datetime.now(ZoneInfo(GOOGLE_SHEETS_TIMEZONE))
    except Exception:
        now = datetime.now()
    return now.strftime("%Y-%m-%d") if normalized == "=TODAY()" else now.strftime("%Y-%m-%d %H:%M:%S")


def resolve_mapping_value(
    template_value: Any,
    variables: dict[str, Any],
) -> tuple[Any, list[str], list[str]]:
    """Resolve @variables in a string mapping value. Non-string values (numbers,
    bools) pass through untouched. Missing @variables stay literal (non-fatal)."""
    if isinstance(template_value, str):
        return resolve_runtime_text(text=template_value, variables=variables)
    return template_value, [], []


def resolve_google_sheet_mappings(
    mappings,
    variables: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    resolved_mappings: list[dict[str, Any]] = []
    all_missing: list[str] = []
    seen_columns: set[str] = set()

    for mapping in mappings:
        column = mapping.column
        if not column or not column.strip():
            raise RuntimeError("Google Sheets mapping column cannot be empty.")
        if column in seen_columns:
            raise RuntimeError(f"Duplicate mapping column found: '{column}'")
        seen_columns.add(column)

        resolved_value, resolved_vars, missing_vars = resolve_mapping_value(
            template_value=mapping.value,
            variables=variables,
        )
        # Freeze volatile date formulas to a static timestamp so the column
        # doesn't reset to "today" every time the sheet is opened.
        static_value = _static_value_for_volatile_formula(resolved_value)
        if static_value is not None:
            resolved_value = static_value
        all_missing.extend(missing_vars)

        resolved_mappings.append(
            {
                "column": column,
                "resolved_value": resolved_value,
                "missing_variables": missing_vars,
            }
        )

    return resolved_mappings, all_missing


def validate_mapping_columns_exist(
    header_to_index: dict[str, int],
    resolved_mappings: list[dict[str, Any]],
):
    for mapping in resolved_mappings:
        column = mapping["column"]
        if column not in header_to_index:
            raise RuntimeError(
                f"Column '{column}' was not found in sheet header row."
            )


# ---------------------------------------------------------------------------
# Insert
# ---------------------------------------------------------------------------

def append_sheet_row(
    spreadsheet_id: str,
    sheet_name: str,
    row: list[Any],
    value_input_option: str,
    access_token: str,
) -> dict[str, Any]:
    range_name = f"{quote_sheet_name(sheet_name)}!A:ZZZ"
    url = f"{SHEETS_BASE_URL}/{spreadsheet_id}/values/{range_name}:append"

    response = _sheets_request(
        "POST",
        url,
        error_prefix="Failed to append row",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        params={
            "valueInputOption": value_input_option,
            "insertDataOption": "INSERT_ROWS",
        },
        json={"majorDimension": "ROWS", "values": [row]},
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Failed to append row: {response.status_code} {response.text}"
        )
    return response.json()


def execute_insert_row(
    config: GoogleSheetsConfig,
    headers: list[str],
    header_to_index: dict[str, int],
    resolved_mappings: list[dict[str, Any]],
    access_token: str,
) -> dict[str, Any]:
    row: list[Any] = [""] * len(headers)
    for mapping in resolved_mappings:
        row[header_to_index[mapping["column"]]] = mapping["resolved_value"]

    append_sheet_row(
        spreadsheet_id=config.spreadsheet_id,
        sheet_name=config.sheet_name,
        row=row,
        value_input_option=config.value_input_option,
        access_token=access_token,
    )
    return {"action": "insert_row", "inserted_row_count": 1}


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def find_matching_row_numbers(
    rows: list[list[Any]],
    reference_column_index: int,
    reference_value: Any,
) -> list[int]:
    """1-based sheet row numbers whose reference cell equals reference_value.
    Row 1 (header) is skipped. Compared as strings - Sheets returns strings."""
    matched: list[int] = []
    reference_value_str = str(reference_value)

    for zero_based_index, row in enumerate(rows):
        sheet_row_number = zero_based_index + 1
        if sheet_row_number == 1:
            continue
        cell_value = ""
        if reference_column_index < len(row):
            cell_value = row[reference_column_index]
        if str(cell_value) == reference_value_str:
            matched.append(sheet_row_number)

    return matched


def batch_update_sheet_values(
    spreadsheet_id: str,
    updates: list[dict[str, Any]],
    value_input_option: str,
    access_token: str,
) -> dict[str, Any]:
    url = f"{SHEETS_BASE_URL}/{spreadsheet_id}/values:batchUpdate"

    response = _sheets_request(
        "POST",
        url,
        error_prefix="Failed to batch update rows",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"valueInputOption": value_input_option, "data": updates},
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Failed to batch update rows: {response.status_code} {response.text}"
        )
    return response.json()


def execute_update_row(
    config: GoogleSheetsConfig,
    header_to_index: dict[str, int],
    resolved_mappings: list[dict[str, Any]],
    variables: dict[str, Any],
    access_token: str,
) -> dict[str, Any]:
    if not config.reference:
        raise RuntimeError("reference is required when action is update_row.")

    reference_column = config.reference.column
    if reference_column not in header_to_index:
        raise RuntimeError(
            f"Reference column '{reference_column}' was not found in sheet header row."
        )

    reference_value, _resolved, _missing = resolve_mapping_value(
        template_value=config.reference.value,
        variables=variables,
    )

    rows = read_sheet_rows(
        spreadsheet_id=config.spreadsheet_id,
        sheet_name=config.sheet_name,
        access_token=access_token,
    )

    matched_row_numbers = find_matching_row_numbers(
        rows=rows,
        reference_column_index=header_to_index[reference_column],
        reference_value=reference_value,
    )
    if not matched_row_numbers:
        raise RuntimeError(
            f"No rows found where '{reference_column}' equals '{reference_value}'."
        )

    updates: list[dict[str, Any]] = []
    for row_number in matched_row_numbers:
        for mapping in resolved_mappings:
            column_letter = column_index_to_letter(header_to_index[mapping["column"]])
            updates.append(
                {
                    "range": f"{quote_sheet_name(config.sheet_name)}!{column_letter}{row_number}",
                    "majorDimension": "ROWS",
                    "values": [[mapping["resolved_value"]]],
                }
            )

    batch_update_sheet_values(
        spreadsheet_id=config.spreadsheet_id,
        updates=updates,
        value_input_option=config.value_input_option,
        access_token=access_token,
    )
    return {
        "action": "update_row",
        "matched_rows": matched_row_numbers,
        "updated_rows_count": len(matched_row_numbers),
        "updated_cells_count": len(updates),
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def execute_google_sheets_node(
    run: WorkflowRun,
    config: GoogleSheetsConfig,
) -> GoogleSheetsExecutionResult:
    """Full node execution. Never raises - all failures come back as a result
    with status="failed" so the workflow engine can decide what to do."""
    base_metadata = {
        "action": config.action,
        "google_connection_id": config.google_connection_id,
        "spreadsheet_id": config.spreadsheet_id,
        "sheet_name": config.sheet_name,
    }

    try:
        if not config.mappings:
            raise RuntimeError("At least one mapping is required.")

        connection = get_google_connection_by_id(config.google_connection_id)
        if not connection:
            raise RuntimeError(
                f"Google connection '{config.google_connection_id}' was not found."
            )
        if connection.client_id != run.client_id:
            raise RuntimeError("Google connection does not belong to this client.")
        if connection.status != "connected":
            raise RuntimeError("Google connection is not connected.")

        client_id = os.getenv("BOT_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID")
        client_secret = (
            os.getenv("BOT_GOOGLE_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET")
        )
        if not client_id or not client_secret:
            raise RuntimeError(
                "BOT_GOOGLE_CLIENT_ID / BOT_GOOGLE_CLIENT_SECRET are not configured."
            )

        access_token = get_valid_google_access_token(
            connection=connection,
            google_client_id=client_id,
            google_client_secret=client_secret,
        )

        headers = read_sheet_headers(
            spreadsheet_id=config.spreadsheet_id,
            sheet_name=config.sheet_name,
            access_token=access_token,
        )
        header_to_index = build_header_index(headers)

        resolved_mappings, missing_variables = resolve_google_sheet_mappings(
            mappings=config.mappings,
            variables=run.variables,
        )
        validate_mapping_columns_exist(
            header_to_index=header_to_index,
            resolved_mappings=resolved_mappings,
        )

        if config.action == "insert_row":
            action_result = execute_insert_row(
                config=config,
                headers=headers,
                header_to_index=header_to_index,
                resolved_mappings=resolved_mappings,
                access_token=access_token,
            )
        elif config.action == "update_row":
            action_result = execute_update_row(
                config=config,
                header_to_index=header_to_index,
                resolved_mappings=resolved_mappings,
                variables=run.variables,
                access_token=access_token,
            )
        else:
            raise RuntimeError(f"Unsupported Google Sheets action '{config.action}'.")

        metadata = {
            **base_metadata,
            "headers_count": len(headers),
            "missing_variables": missing_variables,
            **action_result,
        }

        if config.save_result_in:
            run.variables[config.save_result_in] = {
                "action": config.action,
                "spreadsheet_id": config.spreadsheet_id,
                "sheet_name": config.sheet_name,
                "inserted_row_count": metadata.get("inserted_row_count"),
                "updated_rows_count": metadata.get("updated_rows_count"),
                "matched_rows": metadata.get("matched_rows"),
            }

        return GoogleSheetsExecutionResult(status="success", metadata=metadata)

    except Exception as error:
        return GoogleSheetsExecutionResult(
            status="failed",
            error=str(error),
            metadata=base_metadata,
        )
