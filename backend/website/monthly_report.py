"""Orchestrate website monthly report generate / refine / finalize."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from backend.main.db import projects_col, website_monthly_reports_col
from backend.website.gsc_monthly import fetch_gsc_monthly_bundle, previous_calendar_month
from backend.website.monthly_report_render import (
    export_html_to_pdf,
    has_metrics_cache,
    load_metrics_cache,
    render_report_html,
    report_pdf_path,
    save_metrics_cache,
)
from backend.website.openai_monthly_report import (
    apply_presentation_guards,
    fallback_narrative,
    generate_report_narrative,
    polish_report_narrative,
    refine_report_narrative,
    split_polish_result,
)
from backend.website.pagespeed import fetch_pagespeed
from backend.website import seo_trackers


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_label() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.day} {now.strftime('%B %Y')}"


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


def _client_name(project_id: str) -> str:
    """Prefer tracker brand_name (clinic/site) over CRM client name for PDF titles."""
    config = seo_trackers.get_tracker_config(project_id)
    brand = str(config.get("brand_name") or "").strip()
    if brand:
        return brand
    project = projects_col().find_one({"id": project_id}, {"_id": 0, "name": 1}) or {}
    return project.get("name") or "Client"


def _col():
    return website_monthly_reports_col()


def list_reports(project_id: str) -> list[dict[str, Any]]:
    rows = list(
        _col()
        .find({"project_id": project_id}, {"_id": 0, "html": 0})
        .sort("report_month", -1)
    )
    return [_public_summary(r) for r in rows]


def get_report(report_id: str, *, project_id: str | None = None) -> dict[str, Any]:
    query: dict[str, Any] = {"id": report_id}
    if project_id:
        query["project_id"] = project_id
    report = _col().find_one(query, {"_id": 0})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


def _public_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": report["id"],
        "project_id": report.get("project_id"),
        "report_month": report.get("report_month"),
        "previous_month": report.get("previous_month"),
        "status": report.get("status") or "pending",
        "error": report.get("error"),
        "created_at": report.get("created_at"),
        "updated_at": report.get("updated_at"),
        "has_pdf": bool(report.get("pdf_path")),
    }


def _public_detail(report: dict[str, Any]) -> dict[str, Any]:
    metrics = load_metrics_cache(report["id"]) or {}
    cur = metrics.get("current") or {}
    ai = metrics.get("ai") or {}
    return {
        **_public_summary(report),
        "narrative": report.get("narrative"),
        "presentation": report.get("presentation"),
        "refine_history": list(report.get("refine_history") or [])[-10:],
        "has_metrics_cache": has_metrics_cache(report["id"]),
        "html_url": f"/website.reports.monthly.html/{report['id']}"
        if report.get("html")
        else None,
        "pdf_url": f"/website.reports.monthly.pdf/{report['id']}"
        if report.get("pdf_path") and report.get("status") == "ready"
        else None,
        "metrics_summary": {
            "current": cur,
            "previous": metrics.get("previous"),
            "mom": metrics.get("mom"),
            "ai_impressions": ai.get("current_impressions"),
            "property": metrics.get("property"),
            "site_host": metrics.get("site_host"),
        },
    }


def _upsert(doc: dict[str, Any]) -> None:
    _col().update_one({"id": doc["id"]}, {"$set": doc}, upsert=True)


def _update(report_id: str, fields: dict[str, Any], *, unset: list[str] | None = None) -> None:
    ops: dict[str, Any] = {"$set": fields}
    if unset:
        ops["$unset"] = {k: "" for k in unset}
    _col().update_one({"id": report_id}, ops)


def _build_metrics(project_id: str, report_month: str) -> dict[str, Any]:
    metrics = fetch_gsc_monthly_bundle(project_id, report_month)
    config = seo_trackers.get_tracker_config(project_id)
    site_url = (
        seo_trackers.resolve_site_url(config)
        or seo_trackers.site_url_from_gsc_property(metrics.get("property"))
        or metrics.get("site_url")
        or ""
    )
    if site_url and not str(config.get("site_url") or "").strip():
        # Persist derived homepage so Overview / future reports keep PageSpeed working
        try:
            seo_trackers.save_tracker_config(project_id, {"site_url": site_url})
        except Exception:
            pass
    if site_url and not metrics.get("site_url"):
        metrics["site_url"] = site_url
    # Lighthouse via PageSpeed Insights — strategy from tracker config (default mobile).
    # Report copy never labels the device; title is "PageSpeed Insights - Lighthouse test".
    strategy = str(config.get("pagespeed_strategy") or "mobile")
    try:
        metrics["pagespeed"] = fetch_pagespeed(site_url, strategy=strategy)
    except HTTPException as exc:
        metrics["pagespeed"] = None
        metrics["pagespeed_error"] = str(exc.detail)
    metrics["generated_at"] = _now_label()
    return metrics


def _build_narrative(client_name: str, metrics: dict[str, Any], base: dict[str, Any] | None = None):
    try:
        if base is None:
            base = generate_report_narrative(client_name=client_name, metrics=metrics)
        polished = polish_report_narrative(
            client_name=client_name, metrics=metrics, base_narrative=base
        )
        narrative, presentation = split_polish_result(polished)
    except Exception:
        narrative = base or fallback_narrative(metrics)
        presentation = {}
    presentation = apply_presentation_guards(metrics, presentation)
    return narrative, presentation


def _render_html(
    *,
    client_name: str,
    metrics: dict[str, Any],
    narrative: dict[str, Any],
    presentation: dict[str, Any],
) -> str:
    return render_report_html(
        client_name=client_name,
        metrics=metrics,
        narrative=narrative,
        presentation=presentation,
    )


def generate_report(project_id: str, report_month: str) -> dict[str, Any]:
    month = _validate_month(report_month)
    existing = _col().find_one(
        {"project_id": project_id, "report_month": month}, {"_id": 0}
    )
    report_id = existing["id"] if existing else str(uuid.uuid4())
    now = _now()
    stub = {
        "id": report_id,
        "project_id": project_id,
        "report_month": month,
        "previous_month": previous_calendar_month(month),
        "status": "pending",
        "error": None,
        "narrative": (existing or {}).get("narrative"),
        "presentation": (existing or {}).get("presentation"),
        "refine_history": list((existing or {}).get("refine_history") or []),
        "html": None,
        "pdf_path": None,
        "created_at": (existing or {}).get("created_at") or now,
        "updated_at": now,
    }
    _upsert(stub)

    try:
        metrics = _build_metrics(project_id, month)
        save_metrics_cache(report_id, metrics)
        client_name = _client_name(project_id)
        narrative, presentation = _build_narrative(client_name, metrics)
        html = _render_html(
            client_name=client_name,
            metrics=metrics,
            narrative=narrative,
            presentation=presentation,
        )
        _update(
            report_id,
            {
                "status": "draft",
                "error": None,
                "previous_month": metrics.get("previous_month"),
                "narrative": narrative,
                "presentation": presentation,
                "html": html,
                "pdf_path": None,
                "updated_at": _now(),
            },
        )
    except HTTPException as exc:
        _update(report_id, {"status": "error", "error": str(exc.detail), "updated_at": _now()})
        raise
    except Exception as exc:  # noqa: BLE001
        _update(report_id, {"status": "error", "error": str(exc), "updated_at": _now()})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Report generation failed: {exc}",
        ) from exc

    return _public_detail(get_report(report_id, project_id=project_id))


def refine_report(project_id: str, report_id: str, prompt: str) -> dict[str, Any]:
    report = get_report(report_id, project_id=project_id)
    if report.get("status") == "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Finalized reports are locked. Use Revise to create a new draft.",
        )
    cleaned = (prompt or "").strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refinement prompt is required.",
        )

    _update(report_id, {"status": "pending", "error": None, "updated_at": _now()})
    try:
        metrics = load_metrics_cache(report_id)
        if not metrics:
            metrics = _build_metrics(project_id, report["report_month"])
            save_metrics_cache(report_id, metrics)

        client_name = _client_name(project_id)
        try:
            base = refine_report_narrative(
                client_name=client_name,
                metrics=metrics,
                prior_narrative=report.get("narrative"),
                refine_prompt=cleaned,
            )
        except Exception:
            base = report.get("narrative") or fallback_narrative(metrics)

        narrative, presentation = _build_narrative(client_name, metrics, base=base)
        html = _render_html(
            client_name=client_name,
            metrics=metrics,
            narrative=narrative,
            presentation=presentation,
        )
        history = list(report.get("refine_history") or [])
        history.append({"prompt": cleaned, "created_at": _now()})
        _update(
            report_id,
            {
                "status": "draft",
                "error": None,
                "narrative": narrative,
                "presentation": presentation,
                "html": html,
                "pdf_path": None,
                "refine_history": history[-20:],
                "updated_at": _now(),
            },
        )
    except HTTPException as exc:
        _update(report_id, {"status": "error", "error": str(exc.detail), "updated_at": _now()})
        raise
    except Exception as exc:  # noqa: BLE001
        _update(report_id, {"status": "error", "error": str(exc), "updated_at": _now()})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Report refine failed: {exc}",
        ) from exc

    return _public_detail(get_report(report_id, project_id=project_id))


def finalize_report(project_id: str, report_id: str) -> dict[str, Any]:
    report = get_report(report_id, project_id=project_id)
    if report.get("status") not in {"draft", "ready"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Report must be in draft before finalizing.",
        )
    metrics = load_metrics_cache(report_id)
    if not metrics:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Metrics cache missing — regenerate the report.",
        )
    html = report.get("html")
    if not html:
        client_name = _client_name(project_id)
        html = _render_html(
            client_name=client_name,
            metrics=metrics,
            narrative=report.get("narrative") or {},
            presentation=report.get("presentation") or {},
        )

    pdf_path = report_pdf_path(report_id)
    try:
        export_html_to_pdf(html, pdf_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PDF export failed: {exc}",
        ) from exc

    stored_path = str(pdf_path)
    try:
        from backend.tg.services.gcs_storage import upload_file

        stored_path = upload_file("website-reports", pdf_path, content_type="application/pdf")
    except Exception:
        stored_path = str(pdf_path)

    _update(
        report_id,
        {
            "status": "ready",
            "error": None,
            "html": html,
            "pdf_path": stored_path,
            "updated_at": _now(),
        },
    )
    return _public_detail(get_report(report_id, project_id=project_id))


def revise_report(project_id: str, report_id: str) -> dict[str, Any]:
    """Unlock a finalized report back to draft for further conversational edits."""
    report = get_report(report_id, project_id=project_id)
    if report.get("status") != "ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only finalized reports can be revised.",
        )
    _update(
        report_id,
        {
            "status": "draft",
            "pdf_path": None,
            "updated_at": _now(),
        },
    )
    return _public_detail(get_report(report_id, project_id=project_id))


def report_html(report_id: str, *, project_id: str | None = None) -> str:
    report = get_report(report_id, project_id=project_id)
    html = report.get("html") or ""
    if not html:
        raise HTTPException(status_code=404, detail="HTML preview not available")
    return html


def report_pdf_local_path(report_id: str, *, project_id: str | None = None) -> str:
    report = get_report(report_id, project_id=project_id)
    if report.get("status") != "ready" or not report.get("pdf_path"):
        raise HTTPException(status_code=404, detail="PDF not finalized yet")
    path = report["pdf_path"]
    # If GCS URL, prefer local cache path
    local = report_pdf_path(report_id)
    if local.is_file():
        return str(local)
    if path.startswith("http"):
        raise HTTPException(
            status_code=404,
            detail="PDF is stored remotely; download via stored URL is not wired — regenerate finalize locally.",
        )
    return path
