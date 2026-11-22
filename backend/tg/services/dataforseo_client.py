"""Shared DataForSEO HTTP helper. Credentials stay on the server."""

from __future__ import annotations

import base64

import httpx

from backend.tg.config import settings


class DataForSeoError(Exception):
    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def auth_header() -> str:
    login = (settings.DATAFORSEO_LOGIN or "").strip()
    password = (settings.DATAFORSEO_PASSWORD or "").strip()
    if not login or not password:
        raise DataForSeoError(
            "DataForSEO credentials are missing. Add DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD.",
            status_code=400,
        )
    token = base64.b64encode(f"{login}:{password}".encode()).decode()
    return f"Basic {token}"


def post_json(url: str, payload: list | dict, *, timeout: float = 60) -> dict:
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"Authorization": auth_header(), "Content-Type": "application/json"},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise DataForSeoError(f"DataForSEO request failed: {exc}") from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise DataForSeoError(f"DataForSEO returned a non-JSON response ({response.status_code}).") from exc
    tasks = body.get("tasks") if isinstance(body, dict) else None
    task = (tasks[0] or {}) if tasks else {}
    task_message = str(task.get("status_message") or "") if isinstance(task, dict) else ""
    top_message = str(body.get("status_message") or "") if isinstance(body, dict) else str(response.text or "")
    if response.status_code >= 400 or (task.get("status_code") and int(task.get("status_code") or 0) >= 40000):
        message = task_message or top_message or "DataForSEO request was rejected."
        if response.status_code == 402 or int(task.get("status_code") or 0) == 40200 or "payment" in message.lower():
            message = "DataForSEO balance is used up, so this check could not run."
        raise DataForSeoError(message, status_code=response.status_code or 502)
    if tasks:
        cost = task.get("cost")
        if cost is not None:
            print(f"[dataforseo] cost={cost} url={url}", flush=True)
    return body
