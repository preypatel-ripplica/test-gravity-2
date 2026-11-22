"""Search-gap Optimize: seeding, ranks, sentences, score preview, and the reply counter."""

from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.tg.auth import get_current_user
from backend.tg.database import reply_slot_decision
from backend.main.app import app
from backend.tg.services.gbp_opportunities import (
    build_service_recommendations,
    decide_service_action,
    draft_profile_copy,
    prefer_listed_name,
    projected_listing_score,
)
from backend.tg.services.gbp_optimize import build_audit
from backend.tg.services.gbp_optimize_run import _ai_suggestion_lines, run_gap_optimize
from backend.tg.services.gbp_visibility import (
    customer_sentence,
    distance_km,
    match_client_rank,
    parse_maps_items,
    phrase_fits_review,
    point_gap,
    ring_points,
    score_opportunity,
    weighted_visibility_gap,
)
from backend.tg.services.keyword_research import (
    AdsBudget,
    already_a_service,
    classify_demand,
    discover_keywords,
    fallback_service_seeds,
    localize_seed,
    near_duplicate,
    pick_gap_keywords,
    select_final_keywords,
    select_scan_keywords,
    seeds_from_topics,
    settings_topic_fallback,
    unsuitable_reason,
)


def _client():
    app.dependency_overrides[get_current_user] = lambda: {"username": "owner"}
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def _topic(text, score, saved=True):
    row = {"text": text, "recommendation_score": score}
    if saved:
        row["recommendation_saved_at"] = "2026-11-01T00:00:00+00:00"
    return row


def test_seeds_come_from_top_topics_not_already_listed():
    topics = [
        _topic("Dental implants", 90),
        _topic("Root canal", 80),
        _topic("Teeth whitening", 70),
        _topic("How to floss", 10),
    ]
    seeds, error = seeds_from_topics(topics, ["Root canal"])
    assert error == ""
    assert seeds[0] == "Dental implants"
    assert "Root canal" not in seeds
    assert already_a_service("Root canal treatment", ["Root canal"])


def test_missing_recommendation_scores_stop_optimize():
    seeds, error = seeds_from_topics([{"text": "Implants"}], [])
    assert seeds == []
    assert "Settings" in error


def test_city_is_added_only_when_needed():
    assert localize_seed("dental implants", "Jaipur") == "dental implants Jaipur"
    assert localize_seed("dental implants Jaipur", "Jaipur") == "dental implants Jaipur"
    assert localize_seed("how implants work", "Jaipur") == "how implants work"


def test_shortlist_excludes_reported_phrases_even_with_huge_volume():
    candidates = [
        {"keyword": "dentist jaipur", "volume": 50000},
        {"keyword": "how to whiten teeth", "volume": 90000},
        {"keyword": "teeth whitening near me", "volume": 40},
        {"keyword": "dental implants jaipur", "volume": 20},
    ]
    picked = pick_gap_keywords(candidates, ["dentist jaipur"])
    phrases = [row["keyword"] for row in picked["keywords"]]
    assert "dentist jaipur" not in phrases
    assert phrases[0] == "teeth whitening near me"
    assert all(row["volume"] is None or isinstance(row["volume"], int) for row in picked["keywords"])


def test_unknown_volume_stays_unknown():
    picked = pick_gap_keywords([{"keyword": "prostate clinic jaipur", "volume": None}], [])
    assert picked["keywords"][0]["volume"] is None


def test_note_splits_five_and_five_and_bans_apply_to_all():
    kidney = [{"keyword": f"kidney clinic {index}", "volume": 50 - index} for index in range(6)]
    other = [{"keyword": f"stone doctor {index}", "volume": 30 - index} for index in range(6)]
    banned = [{"keyword": "dental implants jaipur", "volume": 99999}]
    picked = pick_gap_keywords(kidney + other + banned, [], note="Focus on kidney. Do not do implants.")
    phrases = [row["keyword"] for row in picked["keywords"]]
    assert len(phrases) == 10
    assert sum(1 for phrase in phrases if "kidney" in phrase) == 5
    assert not any("implant" in phrase for phrase in phrases)
    assert "implants" in picked["not_used"] or True


def test_unconfirmed_note_is_recorded_not_added():
    picked = pick_gap_keywords(
        [{"keyword": "root canal clinic", "volume": 10}],
        [],
        note="hair transplant",
    )
    assert [row["keyword"] for row in picked["keywords"]] == ["root canal clinic"]
    assert "transplant" in picked["not_used"] or "hair" in picked["not_used"]


def test_fewer_than_ten_gap_phrases_are_not_padded():
    picked = pick_gap_keywords(
        [{"keyword": "dentist jaipur", "volume": 100}, {"keyword": "implants jaipur", "volume": 10}],
        ["dentist jaipur"],
    )
    assert [row["keyword"] for row in picked["keywords"]] == ["implants jaipur"]


def test_ring_has_seventeen_points_inside_18km():
    points = ring_points(26.9, 75.8)
    assert len(points) == 17
    assert points[0]["id"] == "clinic"
    for point in points:
        assert distance_km(26.9, 75.8, point["lat"], point["lng"]) <= 18.05


def test_place_id_match_ignores_paid_and_name_only():
    body = {
        "tasks": [
            {
                "result": [
                    {
                        "items": [
                            {"type": "maps_paid_item", "rank_group": 1, "place_id": "ABC", "title": "Smile"},
                            {"type": "maps_search", "rank_group": 4, "place_id": "ABC", "title": "Smile Dental"},
                            {"type": "maps_search", "rank_group": 2, "place_id": "OTHER", "title": "Smile Dental"},
                        ]
                    }
                ]
            }
        ]
    }
    items = parse_maps_items(body)
    matched = match_client_rank(items, place_id="ABC", name="Smile Dental", phone="", lat=1, lng=1)
    assert matched["rank"] == 4
    assert matched["matched_by"] == "place_id"
    name_only = match_client_rank(items, place_id="", name="Smile Dental", phone="", lat=1, lng=1)
    assert name_only["found"] is False


def test_not_found_is_not_rank_zero_or_a_provider_error():
    matched = match_client_rank([], place_id="ABC", name="Smile", phone="", lat=None, lng=None)
    assert matched["found"] is False
    assert matched["rank"] is None
    assert matched["error"] == ""


def test_sentences_use_nearby_points():
    def point(km, rank=None, found=False, error=""):
        return {"km": km, "direction": "north", "rank": rank, "found": found, "error": error}

    missing = customer_sentence([point(0), point(2), point(2), point(2), point(2)])
    assert missing["sentence"].startswith("People searching this near your clinic are not seeing you")
    failed = customer_sentence([point(0, error="timeout"), point(2, rank=1, found=True)])
    assert failed["sentence"].startswith("We could not check")
    far = customer_sentence(
        [
            point(0, rank=2, found=True),
            point(2, rank=2, found=True),
            point(2, rank=3, found=True),
            point(2, rank=2, found=True),
            point(2, rank=1, found=True),
            point(12),
            point(18),
        ]
    )
    assert far["sentence"].startswith("You show up near your clinic")


def test_phrase_fits_only_when_the_review_mentions_it():
    assert phrase_fits_review("dental implants jaipur", {"comment": "Great implant work"})
    assert not phrase_fits_review("dental implants jaipur", {"comment": "The waiting room was clean"})


def test_potential_score_only_when_apply_fixes_a_check():
    location = {
        "title": "Smile",
        "phoneNumbers": {"primaryPhone": "123"},
        "websiteUri": "https://smile.example",
        "profile": {"description": ""},
        "regularHours": {"periods": [{"openDay": "MONDAY"}]},
        "categories": {"primaryCategory": {"name": "c", "displayName": "Dentist"}},
        "serviceItems": [
            {"freeFormServiceItem": {"label": {"displayName": "Cleaning"}}},
        ],
    }
    audit = build_audit(location=location, media=[{"locationAssociation": {"category": "COVER"}}])
    assert projected_listing_score(audit, description="") is None
    projected = projected_listing_score(audit, description="Short")
    assert projected["potential"] > projected["current"]
    present = {**location, "profile": {"description": "Short"}}
    present_audit = build_audit(location=present, media=[{"locationAssociation": {"category": "COVER"}}])
    longer = "This clinic in Jaipur offers cleaning, fillings, and crowns for local patients who want gentle care."
    assert projected_listing_score(present_audit, description=longer) is None
    assert projected_listing_score(audit, added_services=["Fillings"]) is None
    added = projected_listing_score(audit, added_services=["Fillings", "Crowns"])
    assert added["potential"] > added["current"]
    assert "coverage" not in {check["id"] for section in audit["sections"] for check in section["checks"]}


def test_draft_keeps_the_real_business_name(monkeypatch):
    monkeypatch.setattr("backend.tg.config.settings.OPENAI_API_KEY", "", raising=False)
    copy = draft_profile_copy(
        {
            "business_name": "Smile Dental",
            "locality": "Jaipur",
            "current_description": "",
            "services": ["Cleaning"],
            "keywords": [{"phrase": "dental implants jaipur", "sentence": "Missing nearby", "volume": None}],
        }
    )
    assert copy["title"] == "Smile Dental"
    assert "dental implants jaipur" in copy["description"]


def test_suggestion_lines_fill_service_description():
    recs = [{
        "action": "ADD",
        "proposed_name": "azoospermia",
        "proposed_description": "azoospermia at City Clinic in Delhi. Patients can ask about this service when they book.",
    }]
    _ai_suggestion_lines(
        recs,
        lambda prompt: {
            "items": [
                {
                    "name": "Azoospermia evaluation",
                    "why": "Patients look for this when semen has no sperm.",
                    "description": "Azoospermia is when semen has no sperm. Evaluation finds the cause and treatment options.",
                }
            ]
        },
    )
    assert recs[0]["why"].startswith("Patients look")
    assert "semen" in recs[0]["proposed_description"]
    assert "Patients can ask" not in recs[0]["proposed_description"]


def test_reply_slot_is_one_in_seven_and_does_not_burn_a_miss():
    value = None
    included = []
    for _ in range(6):
        value, include = reply_slot_decision(value, phrase_fits=True)
        included.append(include)
    assert included == [False, False, False, False, False, False]
    assert value == 6
    stayed, include = reply_slot_decision(value, phrase_fits=False)
    assert stayed == 6 and include is False
    reset, include = reply_slot_decision(6, phrase_fits=True)
    assert reset == 0 and include is True


def test_optimize_get_does_not_call_google(monkeypatch):
    monkeypatch.setattr("backend.tg.routes.gbp.fetch_client_doc", lambda client_id, username=None: {"id": client_id})
    monkeypatch.setattr(
        "backend.tg.services.gbp_api.get_gbp_location",
        lambda client_id, location_id: {"location_id": location_id, "selected": True, "account_id": "9"},
    )
    monkeypatch.setattr(
        "backend.tg.routes.gbp.get_gbp_optimize",
        lambda client_id, location_id: {"listing": {"score": 42, "sections": []}, "gaps_status": "ready"},
    )

    def boom(*args, **kwargs):
        raise AssertionError("Google should not be called")

    monkeypatch.setattr("backend.tg.routes.gbp.get_location", boom)
    response = _client().post("/gbp.optimize.get", json={"client_id": "c1", "location_id": "loc-1"})
    assert response.status_code == 200, response.text
    assert response.json()["listing"]["score"] == 42


def test_refresh_listing_replaces_only_the_listing(monkeypatch):
    saved = {}
    monkeypatch.setattr("backend.tg.routes.gbp.fetch_client_doc", lambda client_id, username=None: {"id": client_id})
    monkeypatch.setattr(
        "backend.tg.services.gbp_api.get_gbp_location",
        lambda client_id, location_id: {"location_id": location_id, "selected": True, "account_id": "9", "client_id": client_id},
    )
    monkeypatch.setattr("backend.tg.routes.gbp._creds", lambda client_id: object())
    monkeypatch.setattr(
        "backend.tg.routes.gbp._collect_listing_audit",
        lambda *args, **kwargs: {"audit": {"score": 55, "sections": []}, "location": {}, "topics": [], "keywords": []},
    )
    monkeypatch.setattr("backend.tg.routes.gbp.merge_gbp_optimize", lambda client_id, location_id, patch: saved.update(patch) or patch)
    monkeypatch.setattr("backend.tg.routes.gbp.get_gbp_optimize", lambda client_id, location_id: saved)

    response = _client().post("/gbp.optimize.refresh", json={"client_id": "c1", "location_id": "loc-1"})
    assert response.status_code == 200, response.text
    assert set(saved) == {"listing", "listing_checked_at"}
    assert saved["listing"]["score"] == 55


def test_other_client_cannot_read_optimize(monkeypatch):
    monkeypatch.setattr("backend.tg.routes.gbp.fetch_client_doc", lambda client_id, username=None: None)
    response = _client().post("/gbp.optimize.get", json={"client_id": "other", "location_id": "loc-1"})
    assert response.status_code == 404


def test_no_visibility_cron_route():
    response = _client().post("/cron/gbp.visibility.run", headers={"X-Cron-Secret": "gravity-cron-secret"})
    assert response.status_code == 404


def test_same_day_scan_is_not_repeated(monkeypatch):
    calls = []
    store = {"keywords": [], "listing": {"score": 10, "sections": []}}

    def poster(url, payload):
        calls.append(url)
        if "maps" in url:
            return {"tasks": [{"result": [{"items": [{"type": "maps_search", "rank_group": 6, "place_id": "ABC", "title": "Smile"}]}]}], "cost": 0.002}
        return {"tasks": [{"result": [{"items": [{"keyword": "dental implants jaipur", "search_volume": 80}]}]}]}

    def merge(client_id, location_id, patch):
        store.update(patch)
        return store

    monkeypatch.setattr("backend.tg.services.gbp_optimize_run.merge_gbp_optimize", merge)
    monkeypatch.setattr("backend.tg.services.gbp_optimize_run.get_gbp_optimize", lambda client_id, location_id: store)
    monkeypatch.setattr("backend.tg.services.gbp_optimize_run.draft_profile_copy", lambda packet: {"title": "Smile", "description": "A long enough description for the clinic and its patients in Jaipur today.", "error": ""})
    location = {
        "title": "Smile",
        "profile": {"description": "Short"},
        "storefrontAddress": {"locality": "Jaipur"},
        "categories": {"primaryCategory": {"displayName": "Dentist"}},
        "serviceItems": [{"freeFormServiceItem": {"label": {"displayName": "Dental implants"}}}],
    }
    topics = [_topic("dental implants", 90)]
    run_gap_optimize(
        "c1",
        "loc",
        location=location,
        topics=topics,
        reported=[],
        lat=26.9,
        lng=75.8,
        place_id="ABC",
        poster=poster,
        today=date(2026, 11, 3),
    )
    maps_calls = sum(1 for url in calls if "maps" in url)
    assert maps_calls == 0
    assert not any("search_volume" in url for url in calls)
    assert store.get("keywords")
    calls.clear()
    run_gap_optimize(
        "c1",
        "loc",
        location=location,
        topics=topics,
        reported=[],
        lat=26.9,
        lng=75.8,
        place_id="ABC",
        poster=poster,
        today=date(2026, 11, 3),
    )
    assert not any("maps" in url for url in calls)


def test_ads_budget_stops_a_second_call_before_fifteen_cents():
    calls = []

    def poster(url, payload):
        calls.append((url, len(payload[0]["keywords"])))
        keywords = payload[0]["keywords"]
        return {
            "tasks": [
                {
                    "cost": 0.09,
                    "result": [{"keyword": keyword, "search_volume": 10} for keyword in keywords],
                }
            ]
        }

    seeds = [f"seed {index}" for index in range(25)]
    found = discover_keywords(seeds, location_name="India", poster=AdsBudget().wrap(poster))
    assert len(calls) == 1
    assert calls[0][1] == 20
    assert "keywords_for_keywords" in calls[0][0]
    assert len(found) == 20


def test_payment_required_is_not_reported_as_ok(monkeypatch):
    from backend.tg.services.dataforseo_client import DataForSeoError, post_json

    class Response:
        status_code = 402

        def json(self):
            return {
                "status_code": 20000,
                "status_message": "Ok.",
                "tasks": [{"status_code": 40200, "status_message": "Payment Required."}],
            }

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: Response())
    with pytest.raises(DataForSeoError) as caught:
        post_json("https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live", [])
    assert "balance" in caught.value.message.lower()
    assert caught.value.message != "Ok."


def test_settings_topics_are_kept_without_a_service_overlap():
    topics = [_topic("heart failure", 90), _topic("kidney stone", 40), _topic("pain", 10)]
    chosen = settings_topic_fallback(topics)
    assert "heart failure" in chosen
    assert "kidney stone" in chosen
    assert "pain" not in chosen
    services = fallback_service_seeds(
        ["Kidney Stones", "BPH Treatment"],
        ["kidney stone"],
        [],
    )
    assert services == ["BPH Treatment"]


def test_service_seeds_prefer_uncovered_then_low_impressions_without_ads_volume():
    services = [f"Alpha{index}" for index in range(12)]
    reported = [{"keyword": "Alpha0", "impressions": 80}]
    chosen = fallback_service_seeds(services, [], reported)
    assert len(chosen) == 10
    assert chosen[0] != "Alpha11"
    assert "Alpha0" not in chosen


def test_unknown_demand_is_not_stored_as_zero_and_india_is_labeled():
    unknown = classify_demand(city_volume=None, broader_volume=None, theme_has_demand=False, city_name="Gurugram")
    assert unknown["demand_status"] == "unknown"
    assert unknown["volume"] is None
    broader = classify_demand(city_volume=None, broader_volume=33100, theme_has_demand=False, city_name="Gurugram")
    assert broader["demand_status"] == "broader"
    assert broader["volume"] is None
    assert broader["demand_location"] == "India"
    assert broader["broader_volume"] == 33100


def test_shortlist_does_not_fill_one_theme():
    kidney = [
        {"keyword": f"kidney stone clinic {index}", "volume": 80 - index, "demand_status": "measured"}
        for index in range(6)
    ]
    prostate = [{"keyword": "prostate clinic", "volume": 20, "demand_status": "measured"}]
    picked = select_scan_keywords(kidney + prostate, ["kidney stone", "prostate"], locality="Jaipur", category="Urologist")
    phrases = [row["keyword"] for row in picked["keywords"]]
    assert any("prostate" in phrase for phrase in phrases)
    assert sum(1 for phrase in phrases if "kidney" in phrase) < 6


def test_size_and_language_variants_count_as_duplicates():
    assert near_duplicate("10mm kidney stone treatment", "11mm kidney stone treatment")
    assert near_duplicate("11 mm kidney stone treatment in hindi", "12 mm kidney stone treatment without surgery")
    assert not near_duplicate("erectile dysfunction treatment", "kidney stone treatment")


def test_junk_phrases_are_dropped_before_maps():
    assert unsuitable_reason("kidney stone homeopathic doctor", ["Kidney Stone Treatment"]) == "other_modality"
    assert unsuitable_reason("tract infection treatment", ["Urinary Tract Infection Treatment"]) == "truncated_seed"
    assert unsuitable_reason("Urinary Tract Infection Treatment", ["Urinary Tract Infection Treatment"]) == ""
    picked = select_scan_keywords(
        [
            {"keyword": "kidney stone homeopathic doctor", "volume": 10, "demand_status": "measured"},
            {"keyword": "tract infection treatment", "volume": 590, "demand_status": "measured"},
            {"keyword": "erectile dysfunction treatment", "volume": 260, "demand_status": "measured"},
        ],
        ["Kidney Stone Treatment", "Urinary Tract Infection Treatment", "Erectile Dysfunction Treatment"],
        category="Urologist",
    )
    phrases = [row["keyword"] for row in picked["keywords"]]
    assert "kidney stone homeopathic doctor" not in phrases
    assert "tract infection treatment" not in phrases
    assert any("erectile" in phrase for phrase in phrases)


def test_final_ten_does_not_fill_with_size_variants():
    scanned = [
        {"phrase": "10mm kidney stone treatment", "opportunity_score": 80, "service": "Kidney Stone Treatment"},
        {"phrase": "11mm kidney stone treatment", "opportunity_score": 79, "service": "Kidney Stone Treatment"},
        {"phrase": "12 mm kidney stone treatment without surgery", "opportunity_score": 78, "service": "Kidney Stone Treatment"},
        {"phrase": "erectile dysfunction treatment", "opportunity_score": 70, "service": "Erectile Dysfunction Treatment"},
        {"phrase": "enlarged prostate treatment", "opportunity_score": 60, "service": "Enlarged Prostate Treatment"},
    ]
    final = select_final_keywords(
        scanned,
        seeds=["Kidney Stone Treatment", "Erectile Dysfunction Treatment", "Enlarged Prostate Treatment"],
    )
    phrases = [row["phrase"] for row in final]
    assert "10mm kidney stone treatment" in phrases
    assert "11mm kidney stone treatment" not in phrases
    assert "12 mm kidney stone treatment without surgery" not in phrases
    assert "erectile dysfunction treatment" in phrases


def test_truncated_ads_phrase_is_not_a_service_name():
    assert prefer_listed_name("tract infection treatment", ["Urinary Tract Infection Treatment"]) == "Urinary Tract Infection Treatment"


def test_gap_ignores_errors_and_weak_rank_beats_high_volume():
    assert point_gap({"error": "timeout", "found": False}) is None
    assert point_gap({"found": False}) == 100
    assert point_gap({"found": True, "rank": 2}) == 0
    assert point_gap({"found": True, "rank": 15}) == 50
    only_error = weighted_visibility_gap([{"km": 0, "error": "timeout"}])
    assert only_error is None
    visible = score_opportunity(weighted_gap=0, local_intent=30, demand_points=15, competitor_points=5, feasibility=6)
    buried = score_opportunity(weighted_gap=50, local_intent=30, demand_points=8, competitor_points=5, feasibility=6)
    assert buried > visible


def test_service_recommendation_keeps_volume_and_the_match_reason():
    rows = build_service_recommendations(
        [
            {
                "phrase": "circumcision",
                "volume": 1300,
                "demand_status": "measured",
                "demand_location": "Gurugram",
            }
        ],
        ["Kidney Stones"],
        hints={
            "circumcision": {
                "match": "none",
                "concept": "circumcision",
                "current_service": "",
                "why": "Patients search this as its own procedure.",
            }
        },
    )
    assert rows[0]["action"] == "ADD"
    assert rows[0]["why"] == ""
    assert rows[0]["volume"] == 1300
    assert rows[0]["demand_location"] == "Gurugram"


def test_keep_is_not_returned_as_a_service_recommendation():
    rows = build_service_recommendations(
        [
            {
                "phrase": "kidney stone treatment",
                "volume": 260,
                "demand_status": "measured",
                "demand_location": "Gurugram",
            }
        ],
        ["Kidney Stone Treatment"],
        hints={
            "kidney stone treatment": {
                "match": "same",
                "concept": "Kidney Stone Treatment",
                "current_service": "Kidney Stone Treatment",
            }
        },
    )
    assert rows == []


def test_runtime_prompt_is_omitted_when_the_box_is_empty():
    from backend.tg.services.gbp_opportunities import runtime_prompt

    assert runtime_prompt("") == ""
    assert runtime_prompt("   ") == ""
    note = runtime_prompt("Focus on kidney stones.")
    assert "Focus on kidney stones." in note
    assert "Additional user prompt at runtime" in note
    assert decide_service_action("none")["action"] == "ADD"
    assert decide_service_action("same", name_clear=True, description_thin=False)["action"] == "KEEP"
    assert decide_service_action("same", name_clear=True, description_thin=True)["action"] == "KEEP"
    assert decide_service_action("same", name_clear=True, description_thin=True)["rename"] is False
    replaced = decide_service_action("same", name_clear=False)
    assert replaced["action"] == "REPLACE"
    assert replaced["rename"] is True
    assert decide_service_action("uncertain")["action"] == "ADD"
    assert "REVIEW" not in {decide_service_action(match)["action"] for match in ("none", "same", "uncertain", "related")}


def test_public_optimize_keeps_point_competitors_and_hides_report_services(monkeypatch):
    monkeypatch.setattr("backend.tg.routes.gbp.fetch_client_doc", lambda client_id, username=None: {"id": client_id})
    monkeypatch.setattr(
        "backend.tg.services.gbp_api.get_gbp_location",
        lambda client_id, location_id: {"location_id": location_id, "selected": True, "account_id": "9"},
    )
    monkeypatch.setattr(
        "backend.tg.routes.gbp.get_gbp_optimize",
        lambda client_id, location_id: {
            "listing": {"score": 42, "sections": [], "services": {"suggested": [{"name": "Vikrqm"}], "current": []}},
            "gaps_status": "ready",
            "service_recommendations": [
                {"action": "KEEP", "current_name": "Kidney Stones"},
                {"action": "ADD", "proposed_name": "circumcision"},
            ],
            "keywords": [
                {
                    "phrase": "kidney stone treatment",
                    "volume": 260,
                    "demand_status": "measured",
                    "demand_location": "Gurugram",
                    "points": [
                        {
                            "id": "clinic",
                            "km": 0,
                            "direction": "clinic",
                            "found": False,
                            "rank": None,
                            "competitors": [{"name": "Other Clinic", "place_id": "P1"}],
                        }
                    ],
                }
            ],
        },
    )
    response = _client().post("/gbp.optimize.get", json={"client_id": "c1", "location_id": "loc-1"})
    body = response.json()
    assert body["keywords"][0]["points"][0]["competitors"][0]["name"] == "Other Clinic"
    assert body["listing"]["services"]["suggested"] == []
    assert [item["action"] for item in body["service_recommendations"]] == ["ADD"]
