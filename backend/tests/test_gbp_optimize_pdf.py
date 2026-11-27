"""GBP Optimize client proposal PDF: context, route, and GCS cache fingerprint."""

from fastapi.testclient import TestClient

from backend.main.app import app
from backend.tg.auth import get_current_user
from backend.tg.services.gbp_optimize_pdf import (
    TEMPLATE_VERSION,
    _launch_chromium,
    build_or_fetch_proposal_pdf,
    pdf_fingerprint,
    proposal_context,
    proposal_error,
    proposal_filename,
    render_proposal_html,
)


def _client():
    app.dependency_overrides[get_current_user] = lambda: {"username": "owner"}
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def _optimize(**overrides):
    data = {
        "gaps_status": "ready",
        "gaps_checked_at": "2026-11-26T08:30:00+00:00",
        "suggested_title": "Smile Dental Jaipur",
        "suggested_description": "We treat teeth, gums, and smiles for families in Jaipur.",
        "listing": {
            "score": 72,
            "description": {"current": "A dental clinic."},
            "services": {
                "current": [
                    {"displayName": "Cleaning"},
                    {"displayName": "Fillings"},
                ]
            },
            "sections": [
                {
                    "id": "business",
                    "label": "Business information",
                    "score": 80,
                    "checks": [
                        {"ok": True, "title": "Phone number", "detail": "9876543210"},
                        {"ok": False, "title": "Appointment link", "detail": "Add the booking link patients should use."},
                    ],
                },
                {
                    "id": "photos",
                    "label": "Photos",
                    "score": 50,
                    "checks": [
                        {"ok": True, "title": "Cover", "detail": "On the listing."},
                        {"ok": False, "title": "Interior", "detail": "Upload a real interior photo on the Media page."},
                    ],
                },
            ],
        },
        "service_recommendations": [
            {
                "action": "ADD",
                "proposed_name": "Root canal",
                "proposed_description": "Relieve pain and save the tooth.",
                "why": "People nearby search for this.",
            },
            {
                "action": "REPLACE",
                "current_name": "Cleaning",
                "proposed_name": "Teeth cleaning",
                "reason": "Clearer name for patients.",
            },
            {"action": "KEEP", "proposed_name": "Ignored"},
        ],
    }
    data.update(overrides)
    return data


def test_proposal_context_lists_services_and_add_improve():
    context = proposal_context(
        {"name": "Smile Group"},
        {"title": "Smile Dental", "address": "Jaipur"},
        _optimize(),
    )
    assert context["clinic_name"] == "Smile Dental"
    assert context["address"] == "Jaipur"
    assert context["prepared_on"] == "26 November 2026"
    assert context["current_services"] == ["Cleaning", "Fillings"]
    assert [item["label"] for item in context["recommendations"]] == ["Add", "Improve"]
    assert context["recommendations"][0]["proposed_name"] == "Root canal"
    assert context["recommendations"][1]["current_name"] == "Cleaning"
    assert context["recommendations"][1]["proposed_name"] == "Teeth cleaning"
    assert context["title_unchanged"] is False
    assert context["description_unchanged"] is False
    assert context["has_completeness"] is True
    assert context["completeness_score"] == 72
    assert [item["label"] for item in context["completeness_sections"]] == ["Business information", "Photos"]
    assert [item["score"] for item in context["completeness_sections"]] == [80, 50]
    assert [item["title"] for item in context["incomplete_items"]] == ["Appointment link", "Interior"]
    assert context["incomplete_items"][1]["detail"] == "Add an interior photo on Google."


def test_proposal_context_empty_services_and_unchanged_title():
    context = proposal_context(
        {"name": "Clinic"},
        {"title": "Clinic"},
        _optimize(
            suggested_title="Clinic",
            suggested_description="",
            listing={"description": {"current": ""}, "services": {"current": []}},
            service_recommendations=[],
        ),
    )
    assert context["current_services"] == []
    assert context["recommendations"] == []
    assert context["title_unchanged"] is True
    assert context["description_unchanged"] is True
    assert context["has_completeness"] is False
    assert context["incomplete_items"] == []


def test_proposal_filename_slugs_title():
    assert proposal_filename({"title": "Smile Dental Jaipur"}, {"name": "X"}) == "smile-dental-jaipur-gbp-recommendations.pdf"


def test_proposal_error_before_optimize_and_while_running():
    assert proposal_error({}) == "Optimize this listing first so we have recommendations to share."
    assert "still running" in proposal_error({"gaps_status": "running", "gaps_checked_at": "now"})
    assert proposal_error(_optimize()) == ""


def test_launch_chromium_prefers_installed_chrome():
    calls = []

    class Chromium:
        def launch(self, **kwargs):
            calls.append(kwargs)
            if kwargs.get("channel") != "chrome":
                raise RuntimeError("bundled missing")
            return "browser"

    class Playwright:
        chromium = Chromium()

    assert _launch_chromium(Playwright()) == "browser"
    assert calls == [{"channel": "chrome"}]


def test_render_proposal_html_includes_client_copy():
    html = render_proposal_html(
        proposal_context(
            {"name": "Smile Group"},
            {"title": "Smile Dental", "address": "Jaipur"},
            _optimize(),
        )
    )
    assert "Google Business Profile recommendations" in html
    assert "Smile Dental" in html
    assert "Cleaning" in html
    assert "Add Root canal" in html
    assert "Teeth cleaning" in html
    assert "Please look through" in html
    assert "Nothing goes live" in html
    assert "PlugAI" in html
    assert "Test Gravity" not in html
    assert "How to reply" not in html
    assert "Listing completeness" in html
    assert "72" in html
    assert "Appointment link" in html
    assert "Add an interior photo on Google." in html
    assert "Media page" not in html
    assert "Gravity completeness" not in html


def test_matching_fingerprint_skips_generate(monkeypatch):
    optimize = _optimize(
        pdf_url="https://storage.googleapis.com/bucket/gbp/c1/optimize-loc.pdf",
        pdf_fingerprint=pdf_fingerprint(_optimize()),
    )
    monkeypatch.setattr(
        "backend.tg.services.gbp_optimize_pdf._download_cached",
        lambda url: b"%PDF-cached",
    )
    generated = []
    monkeypatch.setattr(
        "backend.tg.services.gbp_optimize_pdf.html_to_pdf_bytes",
        lambda html: generated.append(html) or b"%PDF-new",
    )
    data, name = build_or_fetch_proposal_pdf(
        {"name": "Clinic"},
        {"title": "Smile Dental"},
        optimize,
        client_id="c1",
        location_id="loc-1",
    )
    assert data == b"%PDF-cached"
    assert generated == []
    assert name.endswith("-gbp-recommendations.pdf")
    assert TEMPLATE_VERSION in pdf_fingerprint(optimize)


def test_new_gaps_checked_at_regenerates_and_replaces(monkeypatch):
    optimize = _optimize(
        gaps_checked_at="2026-11-27T00:00:00+00:00",
        pdf_url="https://storage.googleapis.com/bucket/gbp/c1/optimize-loc.pdf",
        pdf_fingerprint="2026-11-26T08:30:00+00:00|v1",  # old template; must regenerate
    )
    stored = {}
    monkeypatch.setattr("backend.tg.services.gbp_optimize_pdf._download_cached", lambda url: b"%PDF-stale")
    monkeypatch.setattr("backend.tg.services.gbp_optimize_pdf.html_to_pdf_bytes", lambda html: b"%PDF-fresh")
    monkeypatch.setattr("backend.tg.services.gbp_optimize_pdf._gcs_enabled", lambda: True)
    monkeypatch.setattr(
        "backend.tg.services.gbp_optimize_pdf._store_pdf",
        lambda client_id, location_id, pdf_bytes, fingerprint: stored.update(
            client_id=client_id,
            location_id=location_id,
            pdf_bytes=pdf_bytes,
            fingerprint=fingerprint,
        )
        or "https://storage.googleapis.com/bucket/gbp/c1/optimize-loc.pdf",
    )
    data, _name = build_or_fetch_proposal_pdf(
        {"name": "Clinic"},
        {"title": "Smile Dental"},
        optimize,
        client_id="c1",
        location_id="loc-1",
    )
    assert data == b"%PDF-fresh"
    assert stored["pdf_bytes"] == b"%PDF-fresh"
    assert stored["fingerprint"] == f"2026-11-27T00:00:00+00:00||{TEMPLATE_VERSION}"
    assert stored["location_id"] == "loc-1"


def _patch_pdf_route(monkeypatch, optimize=None, client=None, location=None, builder=None, sync=None):
    monkeypatch.setattr(
        "backend.tg.routes.gbp.fetch_client_doc",
        lambda client_id, username=None: client if client is not None else {"id": client_id, "name": "Clinic"},
    )
    location_row = location or {
        "location_id": "loc-1",
        "selected": True,
        "account_id": "9",
        "title": "Smile Dental",
        "address": "Jaipur",
    }
    monkeypatch.setattr(
        "backend.tg.services.gbp_api.get_gbp_location",
        lambda client_id, location_id: {**location_row, "location_id": location_id},
    )
    monkeypatch.setattr(
        "backend.tg.routes.gbp.get_gbp_location",
        lambda client_id, location_id: {**location_row, "location_id": location_id},
    )
    monkeypatch.setattr(
        "backend.tg.routes.gbp.get_gbp_optimize",
        lambda client_id, location_id: optimize if optimize is not None else _optimize(),
    )

    def default_sync(client_row, row, *, force, include_search_keywords):
        return optimize if optimize is not None else _optimize()

    monkeypatch.setattr("backend.tg.routes.gbp._sync_optimize_listing", sync or default_sync)
    if builder is not None:
        monkeypatch.setattr("backend.tg.services.gbp_optimize_pdf.build_or_fetch_proposal_pdf", builder)


def test_pdf_context_drops_add_already_listed():
    data = _optimize()
    data["listing"]["services"]["current"].append({"displayName": "Root canal"})
    context = proposal_context({"name": "Smile Group"}, {"title": "Smile Dental"}, data)
    assert [item["proposed_name"] for item in context["recommendations"]] == ["Teeth cleaning"]


def test_optimize_pdf_forces_live_listing(monkeypatch):
    seen = {}

    def sync(client_row, row, *, force, include_search_keywords):
        seen["force"] = force
        seen["keywords"] = include_search_keywords
        data = _optimize(listing_checked_at="2026-11-26T09:00:00+00:00")
        data["listing"] = {
            **data["listing"],
            "title": "Live Clinic",
            "services": {"current": [{"displayName": "Hip replacement"}]},
        }
        return data

    def fake_build(client, location_row, optimize, *, client_id, location_id):
        seen["services"] = [
            item["displayName"] for item in optimize["listing"]["services"]["current"]
        ]
        seen["fingerprint"] = pdf_fingerprint(optimize)
        return b"%PDF-live", "live.pdf"

    _patch_pdf_route(monkeypatch, sync=sync, builder=fake_build)
    response = _client().post("/gbp.optimize.pdf", json={"client_id": "c1", "location_id": "loc-1"})
    assert response.status_code == 200, response.text
    assert seen["force"] is True
    assert seen["keywords"] is False
    assert seen["services"] == ["Hip replacement"]
    assert "2026-11-26T09:00:00+00:00" in seen["fingerprint"]
    assert TEMPLATE_VERSION in seen["fingerprint"]


def test_optimize_pdf_route_returns_pdf(monkeypatch):
    def fake_build(client, location_row, optimize, *, client_id, location_id):
        assert client_id == "c1"
        assert location_id == "loc-1"
        assert optimize["suggested_title"]
        return b"%PDF-test", "smile-dental-gbp-recommendations.pdf"

    _patch_pdf_route(monkeypatch, builder=fake_build)
    response = _client().post("/gbp.optimize.pdf", json={"client_id": "c1", "location_id": "loc-1"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content == b"%PDF-test"
    assert "smile-dental-gbp-recommendations.pdf" in response.headers.get("content-disposition", "")


def test_optimize_pdf_route_400_before_optimize(monkeypatch):
    _patch_pdf_route(monkeypatch, optimize={})
    response = _client().post("/gbp.optimize.pdf", json={"client_id": "c1", "location_id": "loc-1"})
    assert response.status_code == 400
    assert "Optimize this listing first" in response.json()["detail"]


def test_optimize_pdf_route_404_unknown_client(monkeypatch):
    monkeypatch.setattr("backend.tg.routes.gbp.fetch_client_doc", lambda client_id, username=None: None)
    response = _client().post("/gbp.optimize.pdf", json={"client_id": "missing", "location_id": "loc-1"})
    assert response.status_code == 404
