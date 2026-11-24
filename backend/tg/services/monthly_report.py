"""Orchestrate monthly report generate / refine / persist."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from backend.tg.database import (
    fetch_client_doc,
    fetch_monthly_report,
    fetch_monthly_report_by_month,
    list_channels_meta,
    list_monthly_reports,
    update_client_fields,
    update_monthly_report_fields,
    upsert_monthly_report,
)
from backend.tg.services.monthly_report_metrics import (
    fetch_and_compute_metrics,
    metrics_summary_for_api,
    previous_calendar_month,
)
from backend.tg.services.monthly_report_render import (
    export_html_to_pdf,
    has_metrics_cache,
    load_metrics_cache,
    render_instagram_report_html,
    render_report_html,
    report_pdf_path,
    save_metrics_cache,
)
from backend.tg.services.gcs_storage import upload_file
from backend.tg.services.openai_monthly_report import (
    apply_presentation_guards,
    generate_report_narrative,
    polish_report_narrative,
    refine_report_narrative,
    split_polish_result,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_month(yyyy_mm: str) -> str:
    cleaned = (yyyy_mm or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}", cleaned):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="report_month must be YYYY-MM.",
        )
    month = int(cleaned.split("-")[1])
    if month < 1 or month > 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="report_month month must be 01–12.",
        )
    return cleaned


def ensure_client(username: str, client_id: str) -> dict:
    client = fetch_client_doc(client_id, username=username)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def list_reports(username: str, client_id: str, *, platform: str | None = None) -> list[dict]:
    ensure_client(username, client_id)
    rows = list_monthly_reports(client_id, username=username)
    if platform:
        want = platform.strip().lower()
        rows = [row for row in rows if (row.get("platform") or "youtube") == want]
    return rows


def get_report(username: str, report_id: str) -> dict:
    report = fetch_monthly_report(report_id, username=username)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


def _resolve_metrics(report: dict) -> dict[str, Any] | None:
    """Load metrics from local file. Migrate legacy DB blob to disk once if present."""
    report_id = report["id"]
    cached = load_metrics_cache(report_id)
    if cached:
        return cached
    legacy = report.get("metrics")
    if isinstance(legacy, dict) and legacy:
        save_metrics_cache(report_id, legacy)
        update_monthly_report_fields(report_id, {}, unset=["metrics"])
        return legacy
    return None


def _public_detail(report: dict) -> dict:
    metrics = _resolve_metrics(report) or {}
    return {
        "id": report["id"],
        "client_id": report.get("client_id"),
        "report_month": report.get("report_month"),
        "previous_month": report.get("previous_month"),
        "ai_videos_started_from": report.get("ai_videos_started_from"),
        "channel_ids": list(report.get("channel_ids") or []),
        "platform": report.get("platform") or "youtube",
        "status": report.get("status") or "pending",
        "error": report.get("error"),
        "has_metrics_cache": has_metrics_cache(report["id"]) or bool(metrics),
        "narrative": report.get("narrative"),
        "metrics_summary": metrics_summary_for_api(metrics if metrics else None),
        "refine_history": list(report.get("refine_history") or [])[-10:],
        "html_url": f"/report.html/{report['id']}" if report.get("html") else None,
        "pdf_url": f"/report.pdf/{report['id']}" if report.get("pdf_path") else None,
        "created_at": report.get("created_at"),
        "updated_at": report.get("updated_at"),
    }


def report_to_detail(report: dict) -> dict:
    return _public_detail(report)


def _build_polished_narrative(
    *,
    client_name: str,
    metrics: dict[str, Any],
    base_narrative: dict[str, Any],
    client: dict | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run second AI scan over draft + raw metrics, then apply hard presentation guards."""
    from backend.tg.professions import get_profession

    polished = get_profession(client or {}).polish_monthly_report(
        client_name=client_name,
        metrics=metrics,
        base_narrative=base_narrative,
    )
    narrative, presentation = split_polish_result(polished)
    presentation = apply_presentation_guards(metrics, presentation)
    return narrative, presentation


def _render_and_store_artifacts(
    report_id: str,
    *,
    client_name: str,
    metrics: dict[str, Any],
    narrative: dict[str, Any],
    presentation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    html = render_report_html(
        client_name=client_name,
        metrics=metrics,
        narrative=narrative,
        presentation=presentation,
    )
    pdf_path = report_pdf_path(report_id)
    try:
        export_html_to_pdf(html, pdf_path)
        try:
            pdf_stored = upload_file("reports", pdf_path, content_type="application/pdf")
            # Clean up the local temp file since it's safely in GCS now
            pdf_path.unlink(missing_ok=True)
        except Exception as e:
            print(f"[monthly-report] GCS upload failed: {e}. Storing local path instead.", flush=True)
            pdf_stored = str(pdf_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[monthly-report] PDF export failed: {exc}", flush=True)
        pdf_stored = None
    return {"html": html, "pdf_path": pdf_stored}


def generate_report(
    username: str,
    client_id: str,
    *,
    report_month: str | None = None,
    channel_ids: list[str] | None = None,
    platform: str | None = None,
) -> dict:
    source = (platform or "youtube").strip().lower()
    if source == "instagram":
        return generate_instagram_report(
            username,
            client_id,
            report_month=report_month,
        )
    if source != "youtube":
        raise HTTPException(status_code=400, detail="platform must be youtube or instagram")
    client = ensure_client(username, client_id)
    month = _validate_month(report_month or previous_calendar_month())
    ai_start = (client.get("ai_videos_started_from") or "").strip()
    if not ai_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AI videos started from is not set for this client. Add it in Settings, then try again.",
        )
    _validate_month(ai_start)

    channels = list_channels_meta(client_id)
    if channel_ids:
        allow = set(channel_ids)
        selected = [c["id"] for c in channels if c.get("id") in allow]
    else:
        selected = [c["id"] for c in channels if c.get("id")]
    if not selected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Link at least one YouTube channel before generating a report.",
        )

    existing = fetch_monthly_report_by_month(client_id, month, username=username, platform="youtube")
    report_id = existing["id"] if existing else str(uuid.uuid4())
    now = _now()
    stub = {
        "id": report_id,
        "client_id": client_id,
        "username": username,
        "report_month": month,
        "previous_month": None,
        "ai_videos_started_from": ai_start,
        "channel_ids": selected,
        "platform": "youtube",
        "status": "pending",
        "error": None,
        "narrative": (existing or {}).get("narrative"),
        "refine_history": list((existing or {}).get("refine_history") or []),
        "html": None,
        "pdf_path": None,
        "created_at": (existing or {}).get("created_at") or now,
        "updated_at": now,
    }
    upsert_monthly_report(stub)

    try:
        metrics = fetch_and_compute_metrics(
            username=username,
            client_id=client_id,
            report_month=month,
            ai_videos_started_from=ai_start,
            channel_ids=selected,
        )
        save_metrics_cache(report_id, metrics)
        client_name = client.get("name") or "Client"
        from backend.tg.professions import get_profession

        base_narrative = get_profession(client).generate_monthly_report(
            client_name=client_name,
            metrics=metrics,
        )
        narrative, presentation = _build_polished_narrative(
            client_name=client_name,
            metrics=metrics,
            base_narrative=base_narrative,
            client=client,
        )
        artifacts = _render_and_store_artifacts(
            report_id,
            client_name=client_name,
            metrics=metrics,
            narrative=narrative,
            presentation=presentation,
        )
        update_monthly_report_fields(
            report_id,
            {
                "status": "ready",
                "error": None,
                "previous_month": metrics.get("previous_month"),
                "narrative": narrative,
                "presentation": presentation,
                "html": artifacts["html"],
                "pdf_path": artifacts["pdf_path"],
                "updated_at": _now(),
            },
            unset=["metrics"],
        )
    except HTTPException:
        update_monthly_report_fields(
            report_id,
            {"status": "failed", "error": "Generation failed", "updated_at": _now()},
            unset=["metrics"],
        )
        raise
    except Exception as exc:  # noqa: BLE001
        update_monthly_report_fields(
            report_id,
            {"status": "failed", "error": str(exc), "updated_at": _now()},
            unset=["metrics"],
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Report generation failed: {exc}",
        ) from exc

    return _public_detail(get_report(username, report_id))


def refine_report(username: str, report_id: str, prompt: str) -> dict:
    report = get_report(username, report_id)
    if (report.get("platform") or "youtube") == "instagram":
        return refine_instagram_report(username, report_id, prompt)
    client = ensure_client(username, report["client_id"])
    cleaned = (prompt or "").strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refinement prompt is required.",
        )

    update_monthly_report_fields(
        report_id,
        {"status": "pending", "error": None, "updated_at": _now()},
        unset=["metrics"],
    )

    try:
        metrics = _resolve_metrics(report)
        if not metrics:
            ai_start = (
                report.get("ai_videos_started_from")
                or client.get("ai_videos_started_from")
                or ""
            ).strip()
            if not ai_start:
                raise ValueError("Missing ai_videos_started_from; cannot refetch metrics.")
            metrics = fetch_and_compute_metrics(
                username=username,
                client_id=report["client_id"],
                report_month=report["report_month"],
                ai_videos_started_from=ai_start,
                channel_ids=report.get("channel_ids") or None,
            )
            save_metrics_cache(report_id, metrics)

        client_name = client.get("name") or "Client"
        from backend.tg.professions import get_profession

        base_narrative = get_profession(client).refine_monthly_report(
            client_name=client_name,
            metrics=metrics,
            prior_narrative=report.get("narrative"),
            refine_prompt=cleaned,
        )
        narrative, presentation = _build_polished_narrative(
            client_name=client_name,
            metrics=metrics,
            base_narrative=base_narrative,
            client=client,
        )
        artifacts = _render_and_store_artifacts(
            report_id,
            client_name=client_name,
            metrics=metrics,
            narrative=narrative,
            presentation=presentation,
        )
        history = list(report.get("refine_history") or [])
        history.append({"prompt": cleaned, "created_at": _now()})
        update_monthly_report_fields(
            report_id,
            {
                "status": "ready",
                "error": None,
                "narrative": narrative,
                "presentation": presentation,
                "html": artifacts["html"],
                "pdf_path": artifacts["pdf_path"],
                "previous_month": metrics.get("previous_month") or report.get("previous_month"),
                "refine_history": history[-20:],
                "updated_at": _now(),
            },
            unset=["metrics"],
        )
    except HTTPException:
        update_monthly_report_fields(
            report_id,
            {"status": "failed", "error": "Refine failed", "updated_at": _now()},
            unset=["metrics"],
        )
        raise
    except Exception as exc:  # noqa: BLE001
        update_monthly_report_fields(
            report_id,
            {"status": "failed", "error": str(exc), "updated_at": _now()},
            unset=["metrics"],
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Report refine failed: {exc}",
        ) from exc

    return _public_detail(get_report(username, report_id))


def set_ai_start_for_client_named(
    username: str,
    name_substr: str,
    ai_videos_started_from: str,
) -> dict | None:
    """Utility: set AI start month on first client whose name matches (case-insensitive)."""
    from backend.tg.database import list_clients_for_user

    needle = name_substr.strip().lower()
    for client in list_clients_for_user(username):
        if needle in (client.get("name") or "").lower():
            return update_client_fields(
                client["id"],
                username,
                {"ai_videos_started_from": ai_videos_started_from},
            )
    return None


def _month_window(yyyy_mm: str):
    from datetime import timedelta

    year, month = (int(part) for part in yyyy_mm.split("-"))
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end - timedelta(seconds=1)


def _shift_month(yyyy_mm: str, delta: int = -1) -> str:
    year, month = (int(part) for part in yyyy_mm.split("-"))
    month += delta
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return f"{year:04d}-{month:02d}"


def _instagram_pct(current: float, previous: float) -> float | None:
    if previous in (None, 0):
        return None
    try:
        return round(((float(current) - float(previous)) / float(previous)) * 100.0, 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _instagram_totals(payload: dict[str, Any], month: str) -> dict[str, Any]:
    raw = payload.get("metrics") or {}
    reel_summary = payload.get("reel_summary") or {}
    return {
        "report_month": month,
        "views": raw.get("views") or 0,
        "reach": raw.get("reach") or 0,
        "accounts_engaged": raw.get("accounts_engaged") or 0,
        "total_interactions": raw.get("total_interactions") or 0,
        "likes": raw.get("likes") or 0,
        "comments": raw.get("comments") or 0,
        "shares": raw.get("shares") or 0,
        "saves": raw.get("saves") or 0,
        "profile_views": raw.get("profile_views") or 0,
        "follows": raw.get("follows_and_unfollows") or 0,
        "reel_count": reel_summary.get("count") or len(payload.get("reels") or []),
    }


def _instagram_charts(time_series: dict[str, Any] | None) -> list[dict[str, Any]]:
    series = time_series or {}
    views = series.get("views") or []
    reach = series.get("reach") or []
    if not views and not reach:
        return []
    labels = []
    view_values = []
    reach_values = []
    points = views or reach
    for idx, point in enumerate(points):
        stamp = (point.get("end_time") or "")[:10]
        labels.append(stamp[5:] if len(stamp) >= 10 else stamp or str(idx + 1))
        view_values.append(int((views[idx] or {}).get("value") or 0) if idx < len(views) else 0)
        reach_values.append(int((reach[idx] or {}).get("value") or 0) if idx < len(reach) else 0)
    datasets = []
    if views:
        datasets.append({"label": "Views", "data": view_values})
    if reach:
        datasets.append({"label": "Reach", "data": reach_values})
    return [{"id": "ig_daily", "title": "Daily views and reach", "type": "line", "labels": labels, "datasets": datasets}]


def _instagram_fallback_narrative(client_name: str, metrics: dict[str, Any]) -> dict[str, Any]:
    current = metrics.get("current") or {}
    return {
        "executive_summary": (
            f"{client_name} on Instagram in {metrics.get('report_month')}: "
            f"{current.get('views', 0)} views, reach {current.get('reach', 0)}, "
            f"{current.get('total_interactions', 0)} interactions."
        ),
        "strong_callout": f"{current.get('reel_count', 0)} reels in the month.",
        "highlights": [
            f"Views {current.get('views', 0)}",
            f"Reach {current.get('reach', 0)}",
            f"Reels {current.get('reel_count', 0)}",
        ],
        "previous_month_blurb": "",
        "reel_story": "",
        "next_steps": "Keep posting the formats that earned saves, shares, and follows.",
    }


def _instagram_ai_narrative(
    client: dict,
    client_name: str,
    metrics: dict[str, Any],
    *,
    refine_prompt: str | None = None,
    prior_narrative: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from backend.tg.professions import get_profession
    from backend.tg.services.openai_content_plan import _call_openai

    profession = get_profession(client)
    prompt = profession.prompt("instagram_monthly_report.txt")
    user = (
        f"Client: {client_name}\n"
        f"Month: {metrics.get('report_month')}\n"
        f"Metrics JSON: {metrics}"
    )
    if refine_prompt:
        user += f"\nPrior narrative JSON: {prior_narrative or {}}\nRefine instruction: {refine_prompt}"
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user},
    ]
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "executive_summary": {"type": "string"},
            "strong_callout": {"type": "string"},
            "highlights": {"type": "array", "items": {"type": "string"}},
            "previous_month_blurb": {"type": "string"},
            "reel_story": {"type": "string"},
            "next_steps": {"type": "string"},
        },
        "required": [
            "executive_summary",
            "strong_callout",
            "highlights",
            "previous_month_blurb",
            "reel_story",
            "next_steps",
        ],
    }
    return _call_openai(
        messages=messages,
        schema=schema,
        schema_name="instagram_monthly_report",
        effort="medium",
        stage="instagram-monthly-report",
        timeout=180.0,
    )


def _render_and_store_instagram_artifacts(
    report_id: str,
    *,
    client_name: str,
    metrics: dict[str, Any],
    narrative: dict[str, Any],
) -> dict[str, Any]:
    html = render_instagram_report_html(
        client_name=client_name,
        metrics=metrics,
        narrative=narrative,
    )
    pdf_path = report_pdf_path(report_id)
    try:
        export_html_to_pdf(html, pdf_path)
        try:
            pdf_stored = upload_file("instagram-reports", pdf_path, content_type="application/pdf")
            pdf_path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[instagram-report] GCS upload failed: {exc}", flush=True)
            pdf_stored = str(pdf_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[instagram-report] PDF export failed: {exc}", flush=True)
        pdf_stored = None
    return {"html": html, "pdf_path": pdf_stored}


async def _fetch_instagram_month(connection: dict, month: str) -> dict[str, Any]:
    from backend.tg.plug.instagram_analytics import fetch_plug_analytics

    since_dt, until_dt = _month_window(month)
    return await fetch_plug_analytics(
        ig_id=connection["instagram_user_id"],
        token=connection["access_token"],
        since_dt=since_dt,
        until_dt=until_dt,
    )


def generate_instagram_report(
    username: str,
    client_id: str,
    *,
    report_month: str | None = None,
) -> dict:
    import asyncio

    from backend.tg.database import get_instagram_connection
    from backend.tg.routes.social import _refresh_instagram_token_if_needed, _require_instagram_connection

    client = ensure_client(username, client_id)
    month = _validate_month(report_month or previous_calendar_month())
    prev_month = _shift_month(month, -1)
    try:
        connection = asyncio.run(
            _refresh_instagram_token_if_needed(
                client_id,
                _require_instagram_connection(client_id),
            )
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect Instagram before generating an Instagram report.",
        ) from exc

    existing = fetch_monthly_report_by_month(client_id, month, username=username, platform="instagram")
    report_id = existing["id"] if existing else str(uuid.uuid4())
    now = _now()
    upsert_monthly_report(
        {
            "id": report_id,
            "client_id": client_id,
            "username": username,
            "report_month": month,
            "previous_month": prev_month,
            "platform": "instagram",
            "channel_ids": [connection.get("instagram_user_id") or "instagram"],
            "status": "pending",
            "error": None,
            "narrative": (existing or {}).get("narrative"),
            "refine_history": list((existing or {}).get("refine_history") or []),
            "html": None,
            "pdf_path": None,
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
    )
    try:
        async def _load():
            current_payload = await _fetch_instagram_month(connection, month)
            try:
                previous_payload = await _fetch_instagram_month(connection, prev_month)
            except Exception:
                previous_payload = {}
            return current_payload, previous_payload

        current_payload, previous_payload = asyncio.run(_load())
        current = _instagram_totals(current_payload, month)
        previous = _instagram_totals(previous_payload or {}, prev_month) if previous_payload else {}
        metrics = {
            "platform": "instagram",
            "report_month": month,
            "previous_month": prev_month if previous else None,
            "instagram_username": connection.get("instagram_username")
            or get_instagram_connection(client_id).get("instagram_username"),
            "current": current,
            "previous": previous,
            "mom": {
                "views_pct": _instagram_pct(current.get("views") or 0, previous.get("views") or 0),
                "reach_pct": _instagram_pct(current.get("reach") or 0, previous.get("reach") or 0),
                "interactions_pct": _instagram_pct(
                    current.get("total_interactions") or 0,
                    previous.get("total_interactions") or 0,
                ),
            },
            "reels": list(current_payload.get("reels") or [])[:12],
            "charts": _instagram_charts(current_payload.get("time_series")),
            "fetched_at": _now(),
        }
        save_metrics_cache(report_id, metrics)
        client_name = client.get("name") or "Client"
        try:
            narrative = _instagram_ai_narrative(client, client_name, metrics)
        except Exception as exc:  # noqa: BLE001
            print(f"[instagram-report] narrative fallback: {exc}", flush=True)
            narrative = _instagram_fallback_narrative(client_name, metrics)
        artifacts = _render_and_store_instagram_artifacts(
            report_id,
            client_name=client_name,
            metrics=metrics,
            narrative=narrative,
        )
        update_monthly_report_fields(
            report_id,
            {
                "status": "ready",
                "error": None,
                "previous_month": metrics.get("previous_month"),
                "narrative": narrative,
                "html": artifacts["html"],
                "pdf_path": artifacts["pdf_path"],
                "platform": "instagram",
                "updated_at": _now(),
            },
            unset=["metrics"],
        )
    except HTTPException:
        update_monthly_report_fields(
            report_id,
            {"status": "failed", "error": "Generation failed", "updated_at": _now()},
            unset=["metrics"],
        )
        raise
    except Exception as exc:  # noqa: BLE001
        update_monthly_report_fields(
            report_id,
            {"status": "failed", "error": str(exc), "updated_at": _now()},
            unset=["metrics"],
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Instagram report generation failed: {exc}",
        ) from exc
    return _public_detail(get_report(username, report_id))


def refine_instagram_report(username: str, report_id: str, prompt: str) -> dict:
    report = get_report(username, report_id)
    client = ensure_client(username, report["client_id"])
    cleaned = (prompt or "").strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refinement prompt is required.",
        )
    update_monthly_report_fields(
        report_id,
        {"status": "pending", "error": None, "updated_at": _now()},
        unset=["metrics"],
    )
    try:
        metrics = _resolve_metrics(report)
        if not metrics:
            raise ValueError("Instagram metrics cache missing. Generate the report again.")
        client_name = client.get("name") or "Client"
        try:
            narrative = _instagram_ai_narrative(
                client,
                client_name,
                metrics,
                refine_prompt=cleaned,
                prior_narrative=report.get("narrative"),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[instagram-report] refine fallback: {exc}", flush=True)
            narrative = report.get("narrative") or _instagram_fallback_narrative(client_name, metrics)
        artifacts = _render_and_store_instagram_artifacts(
            report_id,
            client_name=client_name,
            metrics=metrics,
            narrative=narrative,
        )
        history = list(report.get("refine_history") or [])
        history.append({"prompt": cleaned, "created_at": _now()})
        update_monthly_report_fields(
            report_id,
            {
                "status": "ready",
                "error": None,
                "narrative": narrative,
                "html": artifacts["html"],
                "pdf_path": artifacts["pdf_path"],
                "previous_month": metrics.get("previous_month") or report.get("previous_month"),
                "refine_history": history[-20:],
                "platform": "instagram",
                "updated_at": _now(),
            },
            unset=["metrics"],
        )
    except HTTPException:
        update_monthly_report_fields(
            report_id,
            {"status": "failed", "error": "Refine failed", "updated_at": _now()},
            unset=["metrics"],
        )
        raise
    except Exception as exc:  # noqa: BLE001
        update_monthly_report_fields(
            report_id,
            {"status": "failed", "error": str(exc), "updated_at": _now()},
            unset=["metrics"],
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Instagram report refine failed: {exc}",
        ) from exc
    return _public_detail(get_report(username, report_id))
