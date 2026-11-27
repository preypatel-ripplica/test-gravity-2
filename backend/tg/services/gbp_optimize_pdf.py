"""Client-facing GBP Optimize proposal PDF (Jinja + Playwright, GCS cache)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from backend.tg.config import settings
from backend.tg.database import merge_gbp_optimize
from backend.tg.services.gbp_optimize import drop_add_already_listed

TEMPLATE_VERSION = "v6"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

NO_SNAPSHOT_MESSAGE = "Optimize this listing first so we have recommendations to share."
RUNNING_MESSAGE = "Optimize is still running. Download will be ready when it finishes."


def pdf_fingerprint(optimize: dict) -> str:
    checked = str((optimize or {}).get("gaps_checked_at") or "").strip()
    listing_checked = str((optimize or {}).get("listing_checked_at") or "").strip()
    return f"{checked}|{listing_checked}|{TEMPLATE_VERSION}"


def _action_recommendations(optimize: dict) -> list[dict]:
    rows = []
    for item in (optimize or {}).get("service_recommendations") or []:
        if not isinstance(item, dict):
            continue
        if item.get("action") in {"ADD", "REPLACE"}:
            rows.append(item)
    return rows


def proposal_error(optimize: dict) -> str:
    data = optimize or {}
    if (data.get("gaps_status") or "") == "running":
        return RUNNING_MESSAGE
    if not str(data.get("gaps_checked_at") or "").strip():
        return NO_SNAPSHOT_MESSAGE
    recs = _action_recommendations(data)
    title = str(data.get("suggested_title") or "").strip()
    description = str(data.get("suggested_description") or "").strip()
    if not recs and not title and not description:
        return NO_SNAPSHOT_MESSAGE
    return ""


def _format_prepared(iso: str) -> str:
    raw = str(iso or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    return f"{dt.day} {dt.strftime('%B %Y')}"


def _safe_filename(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "").strip()).strip("-").lower()
    return f"{slug or 'listing'}-gbp-recommendations.pdf"


def _safe_location_id(location_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", location_id or "location").strip("-") or "location"


def proposal_filename(location_row: dict, client: dict) -> str:
    title = str((location_row or {}).get("title") or "").strip()
    fallback = str((client or {}).get("name") or "").strip()
    return _safe_filename(title or fallback)


def _client_check_detail(title: str, detail: str) -> str:
    from backend.tg.services.gbp_optimize import rewrite_service_list_detail

    text = rewrite_service_list_detail(detail)
    if "media page" in text.lower():
        label = str(title or "photo").strip().lower() or "photo"
        article = "an" if label[:1] in "aeiou" else "a"
        return f"Add {article} {label} photo on Google."
    return text


def _as_score(value) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return 0


def _completeness(listing: dict) -> dict:
    sections_raw = listing.get("sections") if isinstance(listing, dict) else None
    if not isinstance(sections_raw, list) or not sections_raw:
        return {
            "has_completeness": False,
            "completeness_score": 0,
            "completeness_sections": [],
            "incomplete_items": [],
        }
    sections = []
    incomplete = []
    for section in sections_raw:
        if not isinstance(section, dict):
            continue
        checks = section.get("checks") or []
        missing = []
        done = 0
        total = 0
        for check in checks:
            if not isinstance(check, dict):
                continue
            total += 1
            title = str(check.get("title") or "").strip()
            detail = _client_check_detail(title, str(check.get("detail") or ""))
            if check.get("ok"):
                done += 1
                continue
            if not title:
                continue
            item = {
                "title": title,
                "detail": detail,
                "section": str(section.get("label") or "").strip(),
            }
            missing.append(item)
            incomplete.append(item)
        sections.append(
            {
                "label": str(section.get("label") or "").strip() or "Listing",
                "score": _as_score(section.get("score")),
                "missing": missing,
                "done_count": done,
                "total": total,
            }
        )
    return {
        "has_completeness": bool(sections),
        "completeness_score": _as_score(listing.get("score")),
        "completeness_sections": sections,
        "incomplete_items": incomplete,
    }


def proposal_context(client: dict, location_row: dict, optimize: dict) -> dict:
    data = optimize or {}
    listing = data.get("listing") if isinstance(data.get("listing"), dict) else {}
    services: list[str] = []
    for item in ((listing.get("services") or {}).get("current") or []):
        if isinstance(item, dict):
            name = str(item.get("displayName") or item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            services.append(name)

    recommendations = []
    for item in _action_recommendations(data):
        action = item.get("action")
        recommendations.append(
            {
                "action": action,
                "label": "Add" if action == "ADD" else "Improve",
                "current_name": str(item.get("current_name") or "").strip(),
                "proposed_name": str(item.get("proposed_name") or "").strip(),
                "proposed_description": str(item.get("proposed_description") or "").strip(),
                "why": str(item.get("why") or item.get("reason") or "").strip(),
            }
        )

    recommendations = drop_add_already_listed(recommendations, listing)

    listing_title = str(listing.get("title") or "").strip()
    current_title = listing_title or str((location_row or {}).get("title") or "").strip()
    suggested_title = str(data.get("suggested_title") or "").strip()
    current_description = str(((listing.get("description") or {}).get("current") or "")).strip()
    suggested_description = str(data.get("suggested_description") or "").strip()
    clinic = current_title or str((client or {}).get("name") or "").strip() or "Your listing"
    completeness = _completeness(listing)

    return {
        "clinic_name": clinic,
        "client_name": str((client or {}).get("name") or "").strip(),
        "address": str((location_row or {}).get("address") or "").strip(),
        "prepared_on": _format_prepared(data.get("gaps_checked_at") or ""),
        "current_services": services,
        "recommendations": recommendations,
        "current_title": current_title,
        "suggested_title": suggested_title,
        "title_unchanged": not suggested_title or suggested_title == current_title,
        "current_description": current_description,
        "suggested_description": suggested_description,
        "description_unchanged": not suggested_description or suggested_description == current_description,
        **completeness,
    }


def render_proposal_html(context: dict) -> str:
    return _ENV.get_template("gbp_optimize_proposal.html").render(**context)


def _launch_chromium(playwright):
    """Same order as website monthly reports: installed Chrome, then bundled Chromium."""
    errors: list[str] = []
    for kwargs in (
        {"channel": "chrome"},
        {"channel": "chromium"},
        {},
    ):
        try:
            return playwright.chromium.launch(**kwargs)
        except Exception as exc:  # noqa: BLE001
            label = kwargs.get("channel") or "bundled"
            errors.append(f"{label}: {exc}")
    raise RuntimeError(
        "Could not launch Chrome for PDF export. "
        "Install Google Chrome or run: python -m playwright install chromium. "
        + " | ".join(errors)[:500]
    )


def html_to_pdf_bytes(html: str) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "playwright is not installed. Run: pip install playwright && python -m playwright install chromium"
        ) from exc

    try:
        with sync_playwright() as playwright:
            browser = _launch_chromium(playwright)
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
            )
            browser.close()
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not create the PDF: {exc}") from exc
    return pdf_bytes


def _gcs_enabled() -> bool:
    return bool(getattr(settings, "GCS_BUCKET_NAME", None))


def _download_cached(url: str) -> bytes | None:
    if not url.startswith("http"):
        return None
    try:
        import httpx

        response = httpx.get(url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        data = response.content or b""
        if data[:4] == b"%PDF" or len(data) > 100:
            return data
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] optimize pdf cache miss: {exc}", flush=True)
    return None


def _store_pdf(client_id: str, location_id: str, pdf_bytes: bytes, fingerprint: str) -> str:
    if not _gcs_enabled():
        return ""
    from backend.tg.services.gcs_storage import upload_bytes

    url = upload_bytes(
        f"gbp/{client_id}",
        f"optimize-{_safe_location_id(location_id)}.pdf",
        pdf_bytes,
        "application/pdf",
    )
    merge_gbp_optimize(
        client_id,
        location_id,
        {"pdf_url": url, "pdf_fingerprint": fingerprint},
    )
    return url


def build_or_fetch_proposal_pdf(
    client: dict,
    location_row: dict,
    optimize: dict,
    *,
    client_id: str,
    location_id: str,
) -> tuple[bytes, str]:
    error = proposal_error(optimize)
    if error:
        raise ValueError(error)

    filename = proposal_filename(location_row, client)
    fingerprint = pdf_fingerprint(optimize)
    cached_url = str((optimize or {}).get("pdf_url") or "").strip()
    if cached_url and str((optimize or {}).get("pdf_fingerprint") or "") == fingerprint:
        cached = _download_cached(cached_url)
        if cached:
            return cached, filename

    html = render_proposal_html(proposal_context(client, location_row, optimize))
    pdf_bytes = html_to_pdf_bytes(html)
    try:
        _store_pdf(client_id, location_id, pdf_bytes, fingerprint)
    except Exception as exc:  # noqa: BLE001
        print(f"[gbp] optimize pdf cache skipped: {exc}", flush=True)
    return pdf_bytes, filename
