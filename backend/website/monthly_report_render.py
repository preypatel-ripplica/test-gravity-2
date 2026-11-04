"""HTML + Playwright PDF rendering for website monthly reports."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports" / "website"


def _safe_report_id(report_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", report_id)


def report_metrics_path(report_id: str) -> Path:
    return REPORTS_DIR / f"{_safe_report_id(report_id)}.metrics.json"


def save_metrics_cache(report_id: str, metrics: dict[str, Any]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = report_metrics_path(report_id)
    path.write_text(json.dumps(metrics, ensure_ascii=False), encoding="utf-8")
    return path


def load_metrics_cache(report_id: str) -> dict[str, Any] | None:
    path = report_metrics_path(report_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data else None


def has_metrics_cache(report_id: str) -> bool:
    return report_metrics_path(report_id).is_file()


def report_pdf_path(report_id: str) -> Path:
    return REPORTS_DIR / f"{_safe_report_id(report_id)}.pdf"


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(round(float(value or 0))):,}"
    except (TypeError, ValueError):
        return "0"


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{n:.1f}%"


def _fmt_signed_pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{n:+.1f}%"


def _fmt_pos(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "—"


def render_report_html(
    *,
    client_name: str,
    metrics: dict[str, Any],
    narrative: dict[str, Any],
    presentation: dict[str, Any] | None = None,
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.globals["fmt_int"] = _fmt_int
    env.globals["fmt_pct"] = _fmt_pct
    env.globals["fmt_signed_pct"] = _fmt_signed_pct
    env.globals["fmt_pos"] = _fmt_pos

    template = env.get_template("website_monthly_report.html")
    ai = metrics.get("ai") or {}
    pres = presentation or {
        "show_ai_section": bool(ai.get("available")),
        "show_pagespeed_section": bool(metrics.get("pagespeed")),
        "show_opportunity": bool(metrics.get("opportunity")),
        "suppress_chart_ids": [],
    }
    suppress = set(pres.get("suppress_chart_ids") or [])

    charts = {
        "weekly": metrics.get("weekly") or [],
        "ai_weekly": ai.get("weekly") or [],
        "devices": metrics.get("devices") or [],
        "languages": metrics.get("languages") or [],
    }

    return template.render(
        client_name=client_name,
        metrics=metrics,
        narrative=narrative or {},
        presentation=pres,
        suppress=suppress,
        charts_json=json.dumps(charts),
        report_date=metrics.get("generated_at") or "",
    )


def export_html_to_pdf(html: str, pdf_path: Path) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "playwright is not installed. Run: pip install playwright && playwright install chromium"
        ) from exc

    with sync_playwright() as p:
        browser = None
        launch_errors: list[str] = []
        for kwargs in (
            {"channel": "chrome"},
            {"channel": "chromium"},
            {},
        ):
            try:
                browser = p.chromium.launch(**kwargs)
                break
            except Exception as exc:  # noqa: BLE001
                launch_errors.append(f"{kwargs or 'bundled'}: {exc}")
        if browser is None:
            raise RuntimeError(
                "Could not launch Chromium for PDF export. "
                "Install Chrome or run: playwright install chromium. "
                + " | ".join(launch_errors)[:500]
            )
        try:
            # device_scale_factor sharpens Chart.js canvases in the printed PDF
            context = browser.new_context(
                viewport={"width": 1200, "height": 1600},
                device_scale_factor=2,
            )
            page = context.new_page()
            page.emulate_media(media="print")
            page.set_content(html, wait_until="networkidle")
            page.wait_for_function("window.__CHARTS_READY__ === true", timeout=30000)
            page.wait_for_timeout(1000)
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"},
                scale=1,
            )
            context.close()
        finally:
            browser.close()
    return pdf_path
