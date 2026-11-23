"""GBP helpers and routes with Google HTTP mocked out."""

import base64
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.tg.auth import get_current_user
from backend.main.app import app
from backend.tg.services.gbp_api import (
    GbpApiError,
    _category_filter,
    build_location_patch,
    build_local_post_body,
    merge_metric_payloads,
    percent_change,
    search_categories,
    totals_between,
)
from backend.tg.services.gbp_optimize import (
    build_audit,
    checklist,
    classify_keyword,
    keyword_action,
    keyword_service_ideas,
    profile_update_from_approval,
    sanitize_service_suggestions,
)
from backend.tg.services.gbp_posts import (
    absolute_public_url,
    build_post_prompt,
    compose_drafts,
    enqueue_gbp_draft,
    normalize_schedule,
    posts_due_for_publish,
    run_scheduled_posts,
    schedule_runs_today,
)
from backend.tg.services.gbp_replies import (
    _gap_phrase_for_reply,
    build_review_insights,
    handle_one_review,
    suggested_service_names,
    named_group_limit,
    normalize_dynamic_themes,
    themes_from_assignments,
)


def _client():
    app.dependency_overrides[get_current_user] = lambda: {"username": "owner"}
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_profile_patch_mask_only_changed_fields(monkeypatch):
    captured = {}

    monkeypatch.setattr("backend.tg.routes.gbp.fetch_client_doc", lambda client_id, username=None: {"id": client_id})
    monkeypatch.setattr(
        "backend.tg.services.gbp_api.get_gbp_location",
        lambda client_id, location_id: {
            "location_id": location_id,
            "location_name": f"locations/{location_id}",
            "selected": True,
            "account_id": "9",
        },
    )
    monkeypatch.setattr("backend.tg.routes.gbp.ensure_gbp_credentials", lambda client_id: object())
    monkeypatch.setattr("backend.tg.routes.gbp.upsert_gbp_location", lambda *args, **kwargs: {})

    def fake_patch(creds, name, body, mask):
        captured["name"] = name
        captured["body"] = body
        captured["mask"] = mask
        return {"name": name, "title": body.get("title"), "metadata": {}}

    monkeypatch.setattr("backend.tg.routes.gbp.patch_location", fake_patch)

    response = _client().post(
        "/gbp.profile.patch",
        json={
            "client_id": "c1",
            "location_id": "loc-1",
            "update_mask": ["title", "phoneNumbers"],
            "location": {"title": "City Clinic", "phoneNumbers": {"primaryPhone": "+911234"}, "websiteUri": "https://nope.example"},
        },
    )
    assert response.status_code == 200, response.text
    assert captured["mask"] == "title,phoneNumbers"
    assert captured["body"] == {"title": "City Clinic", "phoneNumbers": {"primaryPhone": "+911234"}}
    assert "websiteUri" not in captured["body"]


def test_build_location_patch_rejects_address():
    try:
        build_location_patch(["storefrontAddress"], {"storefrontAddress": {}})
    except Exception as exc:  # noqa: BLE001
        assert "cannot be updated" in str(exc)
    else:
        raise AssertionError("address updates should be rejected")


def test_post_create_uses_public_image_url(monkeypatch):
    captured = {}
    monkeypatch.setattr("backend.tg.routes.gbp.fetch_client_doc", lambda client_id, username=None: {"id": client_id})
    monkeypatch.setattr(
        "backend.tg.services.gbp_api.get_gbp_location",
        lambda client_id, location_id: {
            "location_id": location_id,
            "selected": True,
            "account_id": "9",
        },
    )
    monkeypatch.setattr("backend.tg.routes.gbp.ensure_gbp_credentials", lambda client_id: object())

    def fake_create(creds, account_id, location_id, body):
        captured["body"] = body
        return {"name": "accounts/9/locations/loc-1/localPosts/1", **body}

    monkeypatch.setattr("backend.tg.routes.gbp.create_local_post", fake_create)
    image = "https://storage.googleapis.com/bucket/gbp/photo.jpg"
    response = _client().post(
        "/gbp.posts.create",
        json={
            "client_id": "c1",
            "location_id": "loc-1",
            "summary": "Clinic hours updated",
            "topic_type": "STANDARD",
            "source_url": image,
        },
    )
    assert response.status_code == 200, response.text
    assert captured["body"]["media"][0]["sourceUrl"] == image
    built = build_local_post_body(summary="Hi", source_url=image)
    assert built["media"][0]["sourceUrl"] == image


def test_location_select_persists_multiple_and_active(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.tg.database._use_mongo", lambda: False)
    monkeypatch.setattr("backend.tg.database.DB_FILE", tmp_path / "db.json")
    monkeypatch.setattr("backend.tg.routes.gbp.fetch_client_doc", lambda client_id, username=None: {"id": client_id})

    from backend.tg.database import get_gbp_connection, list_gbp_locations, save_gbp_connection, upsert_gbp_location

    save_gbp_connection("c1", {"status": "connected", "google_credentials": {"token": "t"}, "auto_reply_mode": "off"})
    upsert_gbp_location("c1", "loc-a", {"title": "Branch A", "selected": False, "account_id": "1", "account_name": "accounts/1"})
    upsert_gbp_location("c1", "loc-b", {"title": "Branch B", "selected": False, "account_id": "1", "account_name": "accounts/1"})

    response = _client().post(
        "/gbp.locations.select",
        json={"client_id": "c1", "location_ids": ["loc-a", "loc-b"]},
    )
    assert response.status_code == 200, response.text
    selected = {row["location_id"]: row["selected"] for row in list_gbp_locations("c1")}
    assert selected == {"loc-a": True, "loc-b": True}
    assert get_gbp_connection("c1")["active_location_id"] == "loc-a"


def test_other_users_client_is_not_found(monkeypatch):
    monkeypatch.setattr("backend.tg.routes.gbp.fetch_client_doc", lambda client_id, username=None: None)
    response = _client().post("/gbp.connection.get", json={"client_id": "someone-elses-client"})
    assert response.status_code == 404


def _review(star="FIVE", comment="Great visit"):
    return {
        "name": "accounts/1/locations/2/reviews/9",
        "starRating": star,
        "comment": comment,
    }


def _location():
    return {"location_id": "2", "title": "City Clinic", "account_id": "1"}


def test_auto_reply_skips_one_star(monkeypatch):
    saved = {}
    monkeypatch.setattr("backend.tg.database.get_gbp_review_draft", lambda draft_id: None)
    monkeypatch.setattr("backend.tg.database.save_gbp_review_draft", lambda draft_id, payload: saved.update(payload) or payload)
    called = []
    monkeypatch.setattr("backend.tg.services.gbp_api.update_review_reply", lambda *args, **kwargs: called.append(args))

    result = handle_one_review(
        "c1",
        _location(),
        {"auto_reply_mode": "fully_automatic", "skip_one_star": True, "skip_angry": True},
        _review("ONE", "Bad"),
        object(),
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "skip_one_star"
    assert called == []
    assert saved["status"] == "skipped"


def test_human_review_does_not_publish(monkeypatch):
    monkeypatch.setattr("backend.tg.database.get_gbp_review_draft", lambda draft_id: None)
    monkeypatch.setattr("backend.tg.database.save_gbp_review_draft", lambda draft_id, payload: payload)
    monkeypatch.setattr("backend.tg.services.gbp_replies.draft_review_reply", lambda review, name, instructions="", keyword="": "Thanks for visiting.")
    monkeypatch.setattr("backend.tg.services.gbp_replies._gap_phrase_for_reply", lambda *args, **kwargs: "")
    called = []
    monkeypatch.setattr("backend.tg.services.gbp_api.update_review_reply", lambda *args, **kwargs: called.append(args))

    result = handle_one_review(
        "c1",
        _location(),
        {"auto_reply_mode": "human_review", "skip_one_star": True, "skip_angry": True},
        _review(),
        object(),
    )
    assert result["status"] == "pending_approval"
    assert called == []


def test_seventh_reply_gets_suggested_services_and_an_empty_list_does_not(monkeypatch):
    names = suggested_service_names({
        "service_recommendations": [
            {"action": "ADD", "proposed_name": "Circumcision"},
            {"action": "REPLACE", "proposed_name": "Cystoscopy"},
            {"action": "KEEP", "proposed_name": "Ignored"},
        ]
    })
    assert names == ["Circumcision", "Cystoscopy"]
    assert suggested_service_names({}) == []
    monkeypatch.setattr(
        "backend.tg.database.get_gbp_optimize",
        lambda client_id, location_id: {"service_recommendations": [{"action": "ADD", "proposed_name": "Circumcision"}]},
    )
    seen = {}
    monkeypatch.setattr("backend.tg.database.remember_reply_keyword", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "backend.tg.database.advance_review_counter",
        lambda *args, **kwargs: seen.update(fits=kwargs.get("phrase_fits")) or True,
    )
    phrase = _gap_phrase_for_reply("c1", "loc", {"starRating": "FIVE", "comment": "The doctor was kind"})
    assert phrase == "Circumcision"
    assert seen["fits"] is True
    monkeypatch.setattr("backend.tg.database.get_gbp_optimize", lambda client_id, location_id: {"service_recommendations": []})
    monkeypatch.setattr(
        "backend.tg.database.advance_review_counter",
        lambda *args, **kwargs: seen.update(fits=kwargs.get("phrase_fits")) or False,
    )
    assert _gap_phrase_for_reply("c1", "loc", {"starRating": "FIVE", "comment": "Kind staff"}) == ""
    assert seen["fits"] is False


def test_fully_automatic_publishes(monkeypatch):
    monkeypatch.setattr("backend.tg.database.get_gbp_review_draft", lambda draft_id: None)
    monkeypatch.setattr("backend.tg.database.save_gbp_review_draft", lambda draft_id, payload: payload)
    monkeypatch.setattr("backend.tg.services.gbp_replies.draft_review_reply", lambda review, name, instructions="", keyword="": "Thanks for visiting.")
    monkeypatch.setattr("backend.tg.services.gbp_replies._gap_phrase_for_reply", lambda *args, **kwargs: "")
    called = []
    monkeypatch.setattr(
        "backend.tg.services.gbp_api.update_review_reply",
        lambda creds, review_name, comment: called.append((review_name, comment)) or {"comment": comment},
    )

    result = handle_one_review(
        "c1",
        _location(),
        {"auto_reply_mode": "fully_automatic", "skip_one_star": True, "skip_angry": True},
        _review(),
        object(),
    )
    assert result["status"] == "published"
    assert called == [("accounts/1/locations/2/reviews/9", "Thanks for visiting.")]


def test_google_errors_keep_403(monkeypatch):
    monkeypatch.setattr("backend.tg.routes.gbp.fetch_client_doc", lambda client_id, username=None: {"id": client_id})
    monkeypatch.setattr(
        "backend.tg.services.gbp_api.get_gbp_location",
        lambda client_id, location_id: {
            "location_id": location_id,
            "selected": True,
            "account_id": "9",
            "location_name": f"locations/{location_id}",
        },
    )
    monkeypatch.setattr("backend.tg.routes.gbp.ensure_gbp_credentials", lambda client_id: object())

    def boom(*args, **kwargs):
        from backend.tg.services.gbp_api import GbpApiError

        raise GbpApiError(403, "The caller does not have permission")

    monkeypatch.setattr("backend.tg.routes.gbp.get_location", boom)
    response = _client().post("/gbp.profile.get", json={"client_id": "c1", "location_id": "loc-1"})
    assert response.status_code == 403
    assert "permission" in response.json()["detail"].lower()


def test_category_search_quotes_spaces_and_retries_the_first_word(monkeypatch):
    assert _category_filter("Urologist Consultation") == 'displayName="Urologist Consultation"'
    seen = []

    def fake_request(creds, method, url, params=None, **kwargs):
        seen.append(params.get("filter"))
        if 'displayName="Urologist Consultation"' in (params.get("filter") or ""):
            raise GbpApiError(400, "Invalid filter")
        return {"categories": [{"name": "categories/gcid:urologist", "displayName": "Urologist"}]}

    monkeypatch.setattr("backend.tg.services.gbp_api._request", fake_request)
    hits = search_categories(object(), "Urologist Consultation")
    assert hits[0]["displayName"] == "Urologist"
    assert seen[0] == 'displayName="Urologist Consultation"'
    assert seen[1] == 'displayName="Urologist"'


def _thin_location():
    return {
        "title": "City Clinic",
        "storefrontAddress": {"locality": "Delhi"},
        "phoneNumbers": {},
        "websiteUri": "",
        "profile": {"description": "Pain care."},
        "regularHours": {},
        "categories": {},
        "serviceItems": [
            {"freeFormServiceItem": {"label": {"displayName": "Back pain consult", "description": ""}}}
        ],
        "metadata": {},
    }


def test_checklist_score_and_photo_gaps():
    sections = checklist(_thin_location(), appointment_uri="", appointment_error="", media=[{"locationAssociation": {"category": "ADDITIONAL"}}])
    by_id = {section["id"]: section for section in sections}
    assert by_id["business"]["score"] < 100
    assert by_id["categories"]["score"] == 0
    assert by_id["photos"]["score"] == 0
    assert {item["title"] for item in by_id["photos"]["checks"]} == {"Cover", "Interior", "Team", "At work"}
    audit = build_audit(location=_thin_location(), media=[], specialty="Pain management", client_description="Back pain and sciatica consults.")
    assert audit["score_label"] == "Gravity completeness"
    assert audit["score"] < 100


def test_approval_patch_cannot_rename_or_move_the_clinic():
    mask, body = profile_update_from_approval(
        description="Our Delhi clinic sees back pain and sciatica.",
        services=[{"displayName": "Sciatica consult", "description": ""}],
        service_category="categories/gcid:pain",
    )
    assert mask == ["profile", "serviceItems"]
    assert "title" not in body
    assert "storefrontAddress" not in body
    applied_mask, applied = build_location_patch(mask, body)
    assert applied_mask == "profile,serviceItems"
    assert "title" not in applied
    kept = sanitize_service_suggestions(
        [{"name": "Laser therapy", "reason": "popular", "evidence": "made up"}],
        evidence=["Back pain and sciatica consults"],
        existing=["Back pain consult"],
    )
    assert kept == []


def test_keyword_groups_and_actions():
    assert classify_keyword("City Clinic delhi", "City Clinic", "Delhi") == "brand"
    assert classify_keyword("pain clinic near me", "City Clinic", "Delhi") == "area"
    assert classify_keyword("how to treat sciatica", "City Clinic", "Delhi") == "question"
    assert classify_keyword("sciatica specialist", "City Clinic", "Delhi") == "service"
    services = ["Back pain consult"]
    description = "We see patients for back pain."
    assert keyword_action("sciatica specialist", "service", description, services) == "suggest_service"
    assert keyword_action("back pain consult", "service", description, services) == "already_covered"
    assert keyword_action("how to treat sciatica", "question", description, services) == "post_idea"
    assert keyword_action("urologist gurgaon", "service", "", ["Urologist Consultation"]) == "already_covered"
    assert keyword_action("urologist near me", "area", "", ["Urologist Consultation"]) == "already_covered"
    invented = sanitize_service_suggestions(
        [{
            "name": "Prostate Care Consultation",
            "reason": "Seen in searches",
            "evidence": 'search_keywords: "best prostate care doctor near me"',
        }],
        evidence=["urologist near me", "bladder doctor"],
        existing=["Enlarged Prostate Treatment"],
    )
    assert invented == []
    kept = sanitize_service_suggestions(
        [{"name": "Andrologist consultation", "reason": "People search for this", "evidence": "andrologist gurgaon"}],
        evidence=["andrologist gurgaon"],
        existing=["Urologist Consultation"],
    )
    assert kept[0]["evidence"] == "andrologist gurgaon"


def test_review_insights_fallback_queue_and_age():
    reviews = [
        {"name": "reviews/1", "starRating": "FIVE", "comment": "The doctor explained everything clearly.", "createTime": "2026-10-01T00:00:00Z"},
        {"name": "reviews/2", "starRating": "TWO", "comment": "The waiting time was two hours.", "createTime": "2026-09-01T00:00:00Z", "reviewReply": {"comment": "Sorry"}},
        {"name": "reviews/3", "starRating": "ONE", "comment": "Worst visit.", "createTime": "2026-08-01T00:00:00Z"},
        {"name": "reviews/4", "starRating": "THREE", "comment": "The injection was painful.", "createTime": "2026-10-20T00:00:00Z"},
    ]
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    insights = build_review_insights(reviews, [{"status": "skipped", "reason": "skip_angry", "review_name": "reviews/9", "comment": "This is a scam"}], now=now)
    themes = {item["id"]: item for item in insights["themes"]}
    assert themes["doctor_communication"]["lean"] == "positive"
    assert themes["waiting_time"]["count"] == 1
    reasons = {item["review_name"]: item["reason"] for item in insights["sensitive"]}
    assert reasons["reviews/3"] == "skip_one_star"
    assert reasons["reviews/4"] == "mentions_treatment"
    assert reasons["reviews/9"] == "skip_angry"
    assert "patient" not in insights["sensitive"][0]["suggested_reply"].lower()
    assert insights["waiting"]["count"] == 3
    assert insights["waiting"]["oldest_days"] >= 80
    named = normalize_dynamic_themes(
        [
            {"label": "Doctor was thorough", "count": 12, "lean": "positive"},
            {"label": "Long wait before the consult", "count": 4, "lean": "needs_attention"},
            {"label": "Doctor was thorough", "count": 2, "lean": "positive"},
            {"label": "", "count": 3, "lean": "mixed"},
        ]
    )
    assert [item["label"] for item in named] == ["Doctor was thorough", "Long wait before the consult"]
    assigned = themes_from_assignments(
        [
            {"starRating": "FIVE", "comment": "Great"},
            {"starRating": "FIVE", "comment": "Kind"},
            {"starRating": "ONE", "comment": "Late"},
            {"starRating": "THREE", "comment": ""},
        ],
        {
            "summary": "Patients like the manner. Fix lateness.",
            "categories": [
                {"label": "Kind manner", "advice": "Keep explaining clearly.", "reviews": [1, 2]},
                {"label": "Running late", "advice": "Tell patients when the doctor is delayed.", "reviews": [3]},
            ],
        },
    )
    assert [item["count"] for item in assigned["themes"]] == [2, 1, 1]
    assert assigned["themes"][-1]["label"] == "Others"
    assert sum(item["count"] for item in assigned["themes"]) == 4
    assert named_group_limit(65) == 5
    assert named_group_limit(151) == 11


def test_post_prompt_includes_clinic_context_and_image_model(monkeypatch):
    prompt = build_post_prompt(
        services=["Sciatica consult"],
        description="Delhi pain clinic",
        keyword_themes=[{"keyword": "sciatica specialist", "theme": "service"}],
        recent_texts=["We are open on Saturday"],
        count=1,
    )
    assert "Sciatica consult" in prompt
    assert "Delhi pain clinic" in prompt
    assert "sciatica specialist" in prompt
    assert "We are open on Saturday" in prompt
    assert "Do not invent" in prompt

    captured = {}

    class FakeData:
        b64_json = base64.b64encode(b"png").decode()
        url = None

    class FakeImages:
        def generate(self, **kwargs):
            captured.update(kwargs)
            return type("Resp", (), {"data": [FakeData()]})()

    class FakeClient:
        images = FakeImages()

    monkeypatch.setattr("backend.tg.services.gbp_posts.settings.OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("backend.tg.services.gbp_posts.settings.OPENAI_IMAGE_MODEL", "gpt-image-2")
    monkeypatch.setattr("openai.OpenAI", lambda api_key=None: FakeClient())
    monkeypatch.setattr(
        "backend.tg.services.gcs_storage.upload_bytes",
        lambda folder, filename, data, content_type="image/png": f"https://storage.googleapis.com/bucket/{folder}/{filename}",
    )
    from backend.tg.services.gbp_posts import generate_post_image

    url, error = generate_post_image("Sciatica consults are available", "c1")
    assert error == ""
    assert url.startswith("https://storage.googleapis.com/bucket/gbp/c1/")
    assert captured["model"] == "gpt-image-2"
    assert "Sciatica consults are available" in captured["prompt"]


def test_failed_image_still_saves_the_text_draft(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.tg.database._use_mongo", lambda: False)
    monkeypatch.setattr("backend.tg.database.DB_FILE", tmp_path / "db.json")
    monkeypatch.setattr(
        "backend.tg.services.gbp_posts.generate_post_image",
        lambda summary, client_id="shared", references=None: (None, "The post photo could not be created."),
    )
    drafts = compose_drafts("c1", "loc-1", ["Sciatica consults are available"])
    assert drafts[0]["summary"] == "Sciatica consults are available"
    assert drafts[0]["source_url"] is None
    assert drafts[0]["image_error"]
    assert drafts[0]["status"] == "pending"


def test_schedule_day_match_and_limits():
    ist = timezone(timedelta(hours=5, minutes=30))
    wednesday = datetime(2026, 10, 28, 9, 0, tzinfo=ist)
    assert schedule_runs_today({"frequency": "daily"}, wednesday)
    assert schedule_runs_today({"frequency": "weekdays"}, wednesday)
    assert not schedule_runs_today({"frequency": "once_a_week", "selected_days": ["Monday"]}, wednesday)
    assert schedule_runs_today({"frequency": "once_a_week", "selected_days": ["Wednesday"]}, wednesday)
    try:
        normalize_schedule({"frequency": "once_a_week", "selected_days": []})
    except ValueError as exc:
        assert "one day" in str(exc)
    else:
        raise AssertionError("once a week needs a day")
    saved = normalize_schedule({"frequency": "daily", "posts_per_day": 9, "autopublish": True})
    assert saved["posts_per_day"] == 9
    assert normalize_schedule({"frequency": "daily", "posts_per_day": 40})["posts_per_day"] == 10
    assert classify_keyword("dr vikram", "Dr Vikram Barua Kaushik", "Gurugram") == "brand"
    assert keyword_action("urologist gurgaon", "service", "Urologist", []) == "already_covered"
    ideas = keyword_service_ideas(
        [{"keyword": "andrologist gurgaon", "action": "suggest_service"}, {"keyword": "urologist near me", "action": "already_covered"}],
        ["Urologist Consultation"],
    )
    assert ideas[0]["name"] == "Andrologist"
    assert ideas[0]["evidence"] == "andrologist gurgaon"
    full = "https://storage.googleapis.com/bucket/gbp/c1/a.png"
    assert absolute_public_url(full) == full
    assert absolute_public_url("gbp/c1/photo.png").startswith("https://storage.googleapis.com/")
    assert absolute_public_url("gbp/c1/photo.png").endswith("/gbp/c1/photo.png")
    assert saved["autopublish"] is True


def _schedule_db(tmp_path, monkeypatch, autopublish):
    monkeypatch.setattr("backend.tg.database._use_mongo", lambda: False)
    monkeypatch.setattr("backend.tg.database.DB_FILE", tmp_path / "db.json")
    from backend.tg.database import save_gbp_connection, upsert_gbp_location

    save_gbp_connection("c1", {"status": "connected", "google_credentials": {"token": "t"}})
    upsert_gbp_location(
        "c1",
        "loc-1",
        {
            "selected": True,
            "account_id": "9",
            "title": "City Clinic",
            "post_schedule": {
                "frequency": "daily",
                "selected_days": [],
                "posts_per_day": 1,
                "autopublish": autopublish,
            },
        },
    )


def _seed_draft(draft_id, status, summary, created_at, queue_order=None):
    from backend.tg.database import save_gbp_post_draft

    save_gbp_post_draft(draft_id, {
        "client_id": "c1",
        "location_id": "loc-1",
        "status": status,
        "queue_order": queue_order,
        "summary": summary,
        "source_url": "https://example.com/a.png",
        "topic_type": "STANDARD",
        "created_at": created_at,
    })


def test_queue_publishes_before_the_newest_draft(tmp_path, monkeypatch):
    _schedule_db(tmp_path, monkeypatch, autopublish=True)
    _seed_draft("queued", "queued", "Queued post", "2026-10-01T00:00:00+00:00", queue_order=1)
    _seed_draft("pending", "pending", "Newest draft", "2026-10-02T00:00:00+00:00")
    calls = {"publish": []}
    monkeypatch.setattr("backend.tg.gbp_oauth.ensure_gbp_credentials", lambda client_id: object())
    monkeypatch.setattr(
        "backend.tg.services.gbp_posts.create_local_post",
        lambda creds, account_id, location_id, body: calls["publish"].append(body) or {"name": "posts/1"},
    )
    today = datetime(2026, 10, 28, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    first = run_scheduled_posts(today)
    assert first["processed"][0]["drafts"] == 1
    assert first["processed"][0]["queued"] == 1
    assert calls["publish"][0]["summary"] == "Queued post"
    assert calls["publish"][0]["media"][0]["sourceUrl"] == "https://example.com/a.png"
    run_scheduled_posts(today)
    assert len(calls["publish"]) == 1

    tomorrow = datetime(2026, 10, 29, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    second = run_scheduled_posts(tomorrow)
    assert second["processed"][0]["drafts"] == 1
    assert calls["publish"][1]["summary"] == "Newest draft"


def test_autopublish_off_leaves_generated_drafts_alone(tmp_path, monkeypatch):
    _schedule_db(tmp_path, monkeypatch, autopublish=False)
    _seed_draft("pending", "pending", "Newest draft", "2026-10-02T00:00:00+00:00")
    calls = {"publish": []}
    monkeypatch.setattr("backend.tg.gbp_oauth.ensure_gbp_credentials", lambda client_id: object())
    monkeypatch.setattr(
        "backend.tg.services.gbp_posts.create_local_post",
        lambda creds, account_id, location_id, body: calls["publish"].append(body) or {"name": "posts/1"},
    )
    today = datetime(2026, 10, 28, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    run_scheduled_posts(today)
    assert calls["publish"] == []
    due = posts_due_for_publish("c1", "loc-1", {"posts_per_day": 1, "autopublish": False})
    assert due == []


def test_enqueue_appends_and_keeps_edited_text(tmp_path, monkeypatch):
    _schedule_db(tmp_path, monkeypatch, autopublish=False)
    _seed_draft("a", "pending", "First", "2026-10-01T00:00:00+00:00")
    _seed_draft("b", "pending", "Second", "2026-10-02T00:00:00+00:00")
    from backend.tg.database import get_gbp_post_draft

    first = enqueue_gbp_draft("c1", get_gbp_post_draft("a"), "Edited first")
    second = enqueue_gbp_draft("c1", get_gbp_post_draft("b"))
    assert first["status"] == "queued"
    assert first["summary"] == "Edited first"
    assert first["queue_order"] == 1
    assert second["queue_order"] == 2
    due = posts_due_for_publish("c1", "loc-1", {"posts_per_day": 1, "autopublish": True})
    assert [item["id"] for item in due] == ["a"]


def test_apply_history_stays_when_optimize_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.tg.database._use_mongo", lambda: False)
    monkeypatch.setattr("backend.tg.database.DB_FILE", tmp_path / "db.json")
    from backend.tg.database import append_gbp_apply_history, get_gbp_location, merge_gbp_optimize, upsert_gbp_location

    upsert_gbp_location("c1", "loc-1", {"selected": True, "title": "Clinic"})
    append_gbp_apply_history("c1", "loc-1", {"applied_on": "2026-11-23", "kind": "description", "before": "Old", "after": "New"})
    merge_gbp_optimize("c1", "loc-1", {"keywords": [{"keyword": "stone"}], "gaps_status": "ready"})
    row = get_gbp_location("c1", "loc-1")
    assert row["optimize"]["gaps_status"] == "ready"
    assert row["apply_history"][0]["after"] == "New"
    assert "apply_history" not in row["optimize"]


def test_result_windows_use_per_day_when_lengths_differ():
    series = {
        "CALL_CLICKS": [
            {"date": "2026-11-01", "value": 10},
            {"date": "2026-11-02", "value": 10},
            {"date": "2026-11-03", "value": 30},
        ]
    }
    short = totals_between(series, date(2026, 11, 1), date(2026, 11, 2))
    long = totals_between(series, date(2026, 11, 1), date(2026, 11, 3))
    assert short["CALL_CLICKS"] == 20
    assert long["CALL_CLICKS"] == 50
    same = percent_change(20, 40, 2, 2)
    assert same["percent"] == 100
    assert same["basis"] == "total"
    uneven = percent_change(20, 50, 2, 3)
    assert uneven["basis"] == "per_day"
    assert uneven["percent"] == round(((50 / 3) - 10) / 10 * 100)


def test_post_cron_rejects_a_bad_secret():
    response = _client().post("/cron/gbp.posts.run", headers={"X-Cron-Secret": "nope"})
    assert response.status_code == 401


def test_optimize_audit_route_returns_score(monkeypatch):
    monkeypatch.setattr("backend.tg.routes.gbp.fetch_client_doc", lambda client_id, username=None: {"id": client_id, "specialty": "Pain management", "description": "Back pain and sciatica consults."})
    monkeypatch.setattr("backend.tg.routes.gbp.fetch_topics", lambda client_id: [{"text": "sciatica"}])
    monkeypatch.setattr(
        "backend.tg.services.gbp_api.get_gbp_location",
        lambda client_id, location_id: {
            "location_id": location_id,
            "location_name": f"locations/{location_id}",
            "selected": True,
            "account_id": "9",
        },
    )
    monkeypatch.setattr("backend.tg.routes.gbp.ensure_gbp_credentials", lambda client_id: object())
    monkeypatch.setattr("backend.tg.routes.gbp.upsert_gbp_location", lambda *args, **kwargs: {})
    monkeypatch.setattr("backend.tg.routes.gbp.get_location", lambda creds, name: _thin_location())
    monkeypatch.setattr("backend.tg.routes.gbp.list_media", lambda creds, account_id, location_id: [])
    monkeypatch.setattr("backend.tg.routes.gbp.list_place_action_links", lambda creds, location_id: [])
    monkeypatch.setattr("backend.tg.routes.gbp.fetch_search_keywords", lambda creds, location_id, start, end: [{"keyword": "sciatica specialist", "impressions": 12}])
    monkeypatch.setattr("backend.tg.routes.gbp.search_categories", lambda creds, query, region_code="IN": [{"name": "categories/gcid:pain", "displayName": "Pain management physician"}])
    monkeypatch.setattr(
        "backend.tg.routes.gbp.request_profile_draft",
        lambda **kwargs: ({
            "description": "Our clinic provides back pain and sciatica consults.",
            "services": [{"name": "Sciatica consult", "reason": "Listed on the site", "evidence": "sciatica"}],
            "primary_name": "categories/gcid:pain",
            "reason": "Matches the specialty",
        }, ""),
    )
    response = _client().post("/gbp.optimize.audit", json={"client_id": "c1", "location_id": "loc-1"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["score_label"] == "Gravity completeness"
    assert body["description"]["suggestion"].startswith("Our clinic")
    assert any(item["name"] == "Sciatica consult" for item in body["services"]["suggested"])
    assert body["categories"]["suggestion"]["displayName"] == "Pain management physician"
    assert any(item["keyword"] == "sciatica specialist" and item["action"] == "suggest_service" for item in body["keywords"])


def test_all_locations_metric_rollup():
    merged = merge_metric_payloads(
        [
            {"series": {"CALL_CLICKS": [{"date": "2026-01-01", "value": 2}]}},
            {"series": {"CALL_CLICKS": [{"date": "2026-01-01", "value": 3}, {"date": "2026-01-02", "value": 1}]}},
        ]
    )
    assert merged["totals"]["CALL_CLICKS"] == 6
