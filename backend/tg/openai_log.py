"""Print OpenAI API errors to the terminal. Optional one extra retry on failure."""

from __future__ import annotations

import time


def _clip(value, limit: int = 2000) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _response_body(response) -> str:
    if response is None:
        return ""
    try:
        text = getattr(response, "text", None)
        if callable(text):
            text = text()
        if text:
            return _clip(text)
    except Exception:
        pass
    try:
        data = getattr(response, "json", None)
        if callable(data):
            return _clip(data())
    except Exception:
        pass
    return ""


def openai_error_detail(exc: BaseException | None = None, *, response=None) -> str:
    try:
        parts: list[str] = []
        resp = response
        if exc is not None:
            parts.append(_clip(f"{type(exc).__name__}: {exc}"))
            for attr in ("status_code", "code", "type", "request_id"):
                try:
                    value = getattr(exc, attr, None)
                except Exception:
                    continue
                if value not in (None, ""):
                    parts.append(f"{attr}={value}")
            try:
                body = getattr(exc, "body", None)
            except Exception:
                body = None
            if body not in (None, ""):
                parts.append(_clip(body))
            try:
                resp = resp or getattr(exc, "response", None)
            except Exception:
                resp = response
        if resp is not None:
            try:
                status = getattr(resp, "status_code", None)
            except Exception:
                status = None
            if status:
                parts.append(f"http={status}")
            extra = _response_body(resp)
            if extra and extra not in " ".join(parts):
                parts.append(extra)
        return " | ".join(parts) or "unknown OpenAI error"
    except Exception:
        return "unknown OpenAI error"


def log_openai_error(tag: str, exc: BaseException | None = None, *, response=None) -> None:
    """Print an OpenAI error. Never raises — logging must not change the request."""
    try:
        print(f"[{tag}] {openai_error_detail(exc, response=response)}", flush=True)
    except Exception:
        try:
            print(f"[{tag}] OpenAI error", flush=True)
        except Exception:
            pass


def _skip_openai_retry(exc: BaseException) -> bool:
    chunks = [str(exc)]
    for attr in ("body", "code", "type"):
        try:
            value = getattr(exc, attr, None)
        except Exception:
            value = None
        if value not in (None, ""):
            chunks.append(str(value))
    text = " ".join(chunks).lower()
    if "no credits remaining" in text or "insufficient_quota" in text:
        return True
    if "invalid_api_key" in text or "incorrect api key" in text:
        return True
    return False


def call_with_openai_retry(fn, *, tag: str, wait: float = 1.5):
    """Run fn(); on failure print and try once more, then re-raise that second error.

    Quota and invalid-key errors are not retried. A successful retry returns
    that result. The second failure is logged and raised unchanged.
    """
    try:
        return fn()
    except Exception as exc:
        log_openai_error(tag, exc)
        if _skip_openai_retry(exc):
            raise
        try:
            print(f"[{tag}] failed. retrying...", flush=True)
        except Exception:
            pass
        time.sleep(wait)
        try:
            return fn()
        except Exception as second:
            log_openai_error(tag, second)
            raise
