"""Website Reports API — Google SEO connect, settings, properties, GSC Performance, monthly PDF."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import Field

from backend.main.access_guards import require_domain_access
from backend.main.auth import current_user
from backend.main.models import Domain
from backend.main.project_scope import WithProjectId
from backend.website import monthly_report as monthly_report_service
from backend.website import seo_trackers

router = APIRouter(tags=["website-reports"])
DOMAIN = Domain.WEBSITE
OAUTH_MESSAGE_TYPE = "website-google-oauth"


class SettingsUpdateBody(WithProjectId):
    tracker_config: dict[str, Any] = Field(default_factory=dict)


class GscPerformanceBody(WithProjectId):
    months: int = Field(default=3, ge=1, le=16)
    row_limit: int = Field(default=25, ge=1, le=250)


class MonthlyGenerateBody(WithProjectId):
    report_month: str


class MonthlyReportIdBody(WithProjectId):
    report_id: str


class MonthlyRefineBody(MonthlyReportIdBody):
    prompt: str = ""


def _oauth_popup_html(
    *,
    status: str,
    email: str = "",
    message: str = "",
    http_status: int = 200,
) -> HTMLResponse:
    email_js = repr(email)
    message_js = repr(message)
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html><body>
<script>
window.opener && window.opener.postMessage({{
  type: {OAUTH_MESSAGE_TYPE!r},
  status: {status!r},
  email: {email_js},
  message: {message_js}
}}, '*');
window.close();
</script>
<p>{'Google connected. You can close this window.' if status == 'connected' else (message or 'Google connection failed.')}</p>
</body></html>""",
        status_code=http_status,
    )


@router.post("/website.reports.google.connect.start")
def google_connect_start(body: WithProjectId, auth=Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    return seo_trackers.create_google_connect_url(body.project_id)


@router.get("/website.reports.google.callback")
def google_connect_callback(request: Request):
    error = request.query_params.get("error")
    if error:
        return _oauth_popup_html(status="error", message=error, http_status=400)
    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    if not code or not state:
        return HTMLResponse(
            "<html><body>Missing OAuth code or state.</body></html>",
            status_code=400,
        )
    try:
        result = seo_trackers.exchange_google_callback(code, state)
        return _oauth_popup_html(
            status="connected",
            email=result.get("connected_email", "") or "",
        )
    except HTTPException as exc:
        return _oauth_popup_html(
            status="error",
            message=str(exc.detail),
            http_status=exc.status_code,
        )


@router.post("/website.reports.google.disconnect")
def google_disconnect(body: WithProjectId, auth=Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    return seo_trackers.disconnect_google(body.project_id)


@router.post("/website.reports.settings.get")
def settings_get(body: WithProjectId, auth=Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    return {
        "tracker_config": seo_trackers.tracker_config_response(
            seo_trackers.get_tracker_config(body.project_id)
        ),
        "google_connection": seo_trackers.google_connection_status(body.project_id),
    }


@router.post("/website.reports.settings.update")
def settings_update(body: SettingsUpdateBody, auth=Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    config = seo_trackers.save_tracker_config(body.project_id, body.tracker_config or {})
    return {"tracker_config": seo_trackers.tracker_config_response(config)}


@router.post("/website.reports.properties.list")
def properties_list(body: WithProjectId, auth=Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    return seo_trackers.list_google_properties(body.project_id)


@router.post("/website.reports.gsc.performance")
def gsc_performance(body: GscPerformanceBody, auth=Depends(current_user)):
    """Search Console Performance tab: totals, daily series, top queries & pages."""
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    return seo_trackers.fetch_gsc_performance(
        body.project_id,
        months=body.months,
        row_limit=body.row_limit,
    )


@router.post("/website.reports.monthly.list")
def monthly_list(body: WithProjectId, auth=Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    return {"reports": monthly_report_service.list_reports(body.project_id)}


@router.post("/website.reports.monthly.get")
def monthly_get(body: MonthlyReportIdBody, auth=Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    return monthly_report_service._public_detail(
        monthly_report_service.get_report(body.report_id, project_id=body.project_id)
    )


@router.post("/website.reports.monthly.generate")
def monthly_generate(body: MonthlyGenerateBody, auth=Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    return monthly_report_service.generate_report(body.project_id, body.report_month)


@router.post("/website.reports.monthly.refine")
def monthly_refine(body: MonthlyRefineBody, auth=Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    return monthly_report_service.refine_report(
        body.project_id, body.report_id, body.prompt
    )


@router.post("/website.reports.monthly.finalize")
def monthly_finalize(body: MonthlyReportIdBody, auth=Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    return monthly_report_service.finalize_report(body.project_id, body.report_id)


@router.post("/website.reports.monthly.revise")
def monthly_revise(body: MonthlyReportIdBody, auth=Depends(current_user)):
    require_domain_access(auth["user_id"], body.project_id, DOMAIN)
    return monthly_report_service.revise_report(body.project_id, body.report_id)


@router.get("/website.reports.monthly.html/{report_id}")
def monthly_html(report_id: str, auth=Depends(current_user)):
    report = monthly_report_service.get_report(report_id)
    require_domain_access(auth["user_id"], report["project_id"], DOMAIN)
    return HTMLResponse(content=monthly_report_service.report_html(report_id))


@router.get("/website.reports.monthly.pdf/{report_id}")
def monthly_pdf(report_id: str, auth=Depends(current_user)):
    report = monthly_report_service.get_report(report_id)
    require_domain_access(auth["user_id"], report["project_id"], DOMAIN)
    if report.get("status") != "ready" or not report.get("pdf_path"):
        raise HTTPException(status_code=404, detail="PDF not finalized yet")
    pdf_path = report["pdf_path"]
    filename = f"{report.get('report_month') or 'report'}-website-report.pdf"

    # Prefer the local finalized file so downloads are never stuck on a CDN-cached
    # older GCS object after a re-finalize overwrote the same key.
    from backend.website.monthly_report_render import report_pdf_path

    cached = report_pdf_path(report_id)
    if cached.is_file():
        return FileResponse(
            path=str(cached),
            media_type="application/pdf",
            filename=filename,
            headers={"Cache-Control": "no-store"},
        )

    if str(pdf_path).startswith("http"):
        import httpx

        client = httpx.Client(timeout=60)

        def iterfile():
            with client.stream("GET", pdf_path) as response:
                yield from response.iter_bytes()

        return StreamingResponse(
            iterfile(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )
    local = Path(pdf_path)
    if not local.is_file():
        raise HTTPException(status_code=404, detail="PDF file missing")
    return FileResponse(
        path=str(local),
        media_type="application/pdf",
        filename=filename,
        headers={"Cache-Control": "no-store"},
    )
