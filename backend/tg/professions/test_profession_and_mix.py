"""Profession registry and posting-mix rules. No database."""

from __future__ import annotations

import inspect

from backend.tg.posting_mix import (
    mix_platforms,
    normalize_posting_mix,
    seed_rows_for_mix,
    tracker_destination_context,
)
from backend.tg.professions import (
    DOCTOR_PROMPTS,
    PROFESSIONS,
    DoctorProfession,
    client_profession_fields,
    get_profession,
)
from backend.tg.professions.mock import MockProfession
from backend.tg.services.trends import analyze_topics_trends


def test_missing_and_unknown_profession_are_doctor():
    for client in ({}, {"profession": ""}, {"profession": "  "}, {"profession": "xyz"}, {"profession": "mock"}):
        profession = get_profession(client)
        assert isinstance(profession, DoctorProfession)
        assert profession.prompts_dir == DOCTOR_PROMPTS
        caps = profession.capabilities()
        assert caps["uses_google_trends"] is True
        assert caps["ui"]["keyword_layout"] == "priority_trends"
        assert caps["ui"]["title_pick"] == "weighted_mapped"
        assert caps["ui"]["profile_label"] == "Doctor profile"


def test_doctor_trend_step_is_dataforseo_function():
    source = inspect.getsource(DoctorProfession.analyze_trends)
    assert "analyze_topics_trends" in source
    assert analyze_topics_trends.__module__.endswith("trends")


def test_creator_is_selectable_and_skips_trends_and_mapping():
    from backend.tg.professions import SELECTABLE_PROFESSIONS
    from backend.tg.professions.creator import CREATOR_PROMPTS, CreatorProfession

    creator = get_profession({"profession": "creator"})
    assert isinstance(creator, CreatorProfession)
    assert creator.prompts_dir == CREATOR_PROMPTS
    assert "creator" in SELECTABLE_PROFESSIONS
    assert "mock" not in SELECTABLE_PROFESSIONS
    caps = creator.capabilities()
    assert caps["uses_google_trends"] is False
    assert caps["uses_video_mapping"] is False
    assert caps["uses_recommendations_tab"] is True
    assert caps["ui"]["keyword_layout"] == "ai_ranked"
    assert caps["ui"]["title_pick"] == "score_rank"
    assert caps["ui"]["profile_label"] == "Creator profile"
    video = [row["id"] for row in creator.stages("long_video")]
    assert video == [
        "planned",
        "script_generated",
        "video_edited",
        "yt_metadata_generated",
        "posted",
        "link_shared_with_client",
    ]
    assert [row["id"] for row in creator.stages("short")] == video
    assert video[-1] == "link_shared_with_client"
    assert creator.stages("long_video")[-1]["label"] == "Link shared with creator"
    assert creator.stages("static_post")[-1] == {
        "id": "link_shared_with_client",
        "label": "Link shared with creator",
    }
    assert creator.stages("blog")[-1]["label"] == "Link shared with creator"
    assert creator.capabilities()["ui"]["audience_noun"] == "creator"
    doctor = get_profession({"profession": "doctor"})
    assert [row["id"] for row in doctor.stages("long_video")][-1] == "link_shared_with_doctor"
    assert "audio_generated" in [row["id"] for row in doctor.stages("long_video")]
    blog_ids = [row["id"] for row in doctor.stages("blog")]
    assert blog_ids == ["planned", "published", "link_shared_with_doctor"]


def test_rank_pick_is_score_order_without_cutoff():
    from backend.tg.services.content_plan import pick_topics_by_rank

    picked = pick_topics_by_rank(
        [
            {"id": "low", "text": "Low", "recommendation_score": 12},
            {"id": "top", "text": "Top", "recommendation_score": 90},
            {"id": "mid", "text": "Mid", "recommendation_score": 40},
        ],
        2,
    )
    assert [row["id"] for row in picked] == ["top", "mid"]


def test_creator_scores_and_titles_do_not_use_trends_or_mapping():
    import inspect

    from backend.tg.services.content_plan import generate_content_plan, generate_titles_from_scores
    from backend.tg.services.topics import apply_stored_recommendation_scores

    stored = apply_stored_recommendation_scores([
        {"id": "a", "text": "Budget travel", "weight": "low", "source": "auto", "recommendation_score": 82, "trend_score": 90},
        {"id": "b", "text": "Street food", "weight": "high", "source": "auto", "recommendation_score": 40},
    ])
    by_text = {row["text"]: row for row in stored}
    assert by_text["Budget travel"]["recommendation_score"] == 82
    assert by_text["Budget travel"]["trend_points"] == 0
    assert by_text["Street food"]["recommendation_score"] == 40
    assert stored[0]["text"] == "Budget travel"

    title_source = inspect.getsource(generate_titles_from_scores)
    assert "ensure_video_topic_coverage" not in title_source
    assert "map_videos_batch" not in title_source
    doctor_source = inspect.getsource(generate_content_plan)
    assert "ensure_video_topic_coverage" in doctor_source

    creator_source = inspect.getsource(PROFESSIONS["creator"].generate_content_plan)
    assert "generate_titles_from_scores" in creator_source
    assert "ensure_video_topic_coverage" not in creator_source


def test_prompt_folder_defaults_to_doctor_and_creator_pack_exists():
    from backend.tg.professions.prompt_context import DOCTOR_PROMPTS_DIR, current_prompts_dir, use_prompts
    from backend.tg.services.openai_content_plan import _load_prompt

    assert current_prompts_dir() == DOCTOR_PROMPTS_DIR
    doctor_text = _load_prompt("content_plan_generate.txt")
    assert "CHIEF / CHAIRPERSON DOCTOR" in doctor_text
    creator_dir = DOCTOR_PROMPTS_DIR.parent / "creator"
    with use_prompts(creator_dir):
        assert current_prompts_dir() == creator_dir
        creator_text = _load_prompt("content_plan_generate.txt")
    assert current_prompts_dir() == DOCTOR_PROMPTS_DIR
    assert "CHIEF / CHAIRPERSON DOCTOR" not in creator_text
    assert "general creator" in creator_text.lower() or "general public" in creator_text.lower()
    doctor_names = {path.name for path in DOCTOR_PROMPTS_DIR.iterdir() if path.is_file()}
    creator_names = {path.name for path in creator_dir.iterdir() if path.is_file()}
    assert doctor_names <= creator_names
    assert "topic_search.txt" in creator_names
    assert (creator_dir / "languages" / "hinglish.txt").is_file()


def test_mock_hides_trends_and_is_not_production():
    mock = MockProfession()
    caps = mock.capabilities()
    assert caps["uses_google_trends"] is False
    assert caps["uses_video_mapping"] is False
    assert "mock" not in PROFESSIONS


def test_legacy_tracker_when_mix_not_saved():
    ctx = tracker_destination_context({"youtube_languages": [{"key": "tamil", "label": "Tamil"}]})
    assert ctx["destinations_mode"] == "legacy"
    assert ctx["posting_mix"] is None


def test_mix_columns_and_hide_does_not_describe_deletion():
    mix = normalize_posting_mix({
        "saved": True,
        "include": {"youtube": True, "instagram": False, "facebook": True},
        "extra_platforms": [{"key": "linkedin", "label": "LinkedIn"}],
    })
    assert mix_platforms(mix, "long_video") == ["youtube", "facebook", "linkedin"]
    rows = seed_rows_for_mix("long_video", ["hinglish", "tamil"], mix)
    assert [row.get("language") for row in rows if row["platform"] == "youtube"] == ["hinglish", "tamil"]
    assert sum(1 for row in rows if row["platform"] == "instagram") == 0
    assert sum(1 for row in rows if row["platform"] == "facebook") == 1
    hidden = normalize_posting_mix({
        **{"saved": True, "include": {"youtube": True, "instagram": True, "facebook": False}, "extra_platforms": []},
    })
    assert "instagram" in mix_platforms(hidden, "long_video")


def test_collapse_mix_destinations_drops_legacy_language_instagram_rows():
    from backend.tg.posting_mix import collapse_mix_destinations

    mix = {
        "saved": True,
        "include": {"youtube": False, "instagram": True, "facebook": False},
        "extra_platforms": [],
    }
    dests = [
        {"id": "a", "language": "hinglish", "platform": "instagram", "url": ""},
        {"id": "b", "language": "arabic", "platform": "instagram", "url": ""},
        {"id": "c", "language": "russian", "platform": "instagram", "url": ""},
    ]
    out = collapse_mix_destinations(dests, "long_video", [], mix)
    assert [row["platform"] for row in out] == ["instagram"]
    assert "language" not in out[0]
    yt_mix = {
        "saved": True,
        "include": {"youtube": True, "instagram": True, "facebook": False},
        "extra_platforms": [],
    }
    with_yt = collapse_mix_destinations(
        dests + [{"id": "yt", "language": "hinglish", "platform": "youtube", "url": "https://youtu.be/x"}],
        "long_video",
        ["hinglish"],
        yt_mix,
    )
    assert [row["platform"] for row in with_yt] == ["youtube", "instagram"]
    assert with_yt[0]["language"] == "hinglish"


def test_hindi_key_stays_hinglish():
    ctx = tracker_destination_context({
        "youtube_languages": [{"key": "hindi", "label": "Hindi"}],
        "posting_mix": {"saved": True, "include": {"youtube": True, "instagram": False, "facebook": False}, "extra_platforms": []},
    })
    assert ctx["languages"] == ["hinglish"]
    assert ctx["language_labels"]["hinglish"] == "Hindi"


def test_creator_static_pick_uses_all_topics_ranked():
    from backend.tg.professions.creator import CreatorProfession

    creator = CreatorProfession()
    picked = creator.pick_static_keywords({
        "topics": [
            {"id": "low", "text": "Low", "recommendation_score": 12, "weight": "high"},
            {"id": "top", "text": "Top", "recommendation_score": 90, "weight": "low"},
            {"id": "mid", "text": "Mid", "recommendation_score": 40},
            {"id": "", "text": "Skip"},
            {"id": "blank", "text": "  "},
        ],
    })
    assert [row["topic_id"] for row in picked] == ["top", "mid", "low"]
    assert picked[0]["topic_text"] == "Top"
    assert picked[-1]["recommendation_score"] == 12
    assert [row["topic_id"] for row in creator.sample_static_keywords(picked, 2)] == ["top", "mid"]


def test_creator_static_brief_uses_niche():
    from backend.tg.routes.social import _client_brief_profile

    name, specialty, creator = _client_brief_profile(
        {"profession": "creator", "name": "Ada", "niche": "personal finance", "specialty": ""}
    )
    assert creator is True
    assert name == "Ada"
    assert specialty == "personal finance"
    name, specialty, creator = _client_brief_profile(
        {"profession": "doctor", "name": "Dr X", "specialty": "cardiology", "niche": "ignored"}
    )
    assert creator is False
    assert specialty == "cardiology"


def test_plug_migrated_flag_is_on_profession_fields():
    from backend.tg.database import is_plug_migrated

    assert is_plug_migrated({"migrated_from_plug": "sachin"})
    assert not is_plug_migrated({"migrated_from_plug": ""})
    assert not is_plug_migrated({})
    fields = client_profession_fields({"profession": "doctor", "migrated_from_plug": "jigar"})
    assert fields["migrated_from_plug"] == "jigar"
    assert fields["profession"] == "doctor"


def test_doctor_static_pick_still_uses_recommended_keywords():
    source = inspect.getsource(DoctorProfession.pick_static_keywords)
    assert "_recommended_keywords" in source
    assert "score < 50" not in source


def test_creator_seed_keywords_uses_web_search_not_sitemap():
    source = inspect.getsource(PROFESSIONS["creator"].seed_keywords)
    assert "generate_creator_keywords" in source
    assert "refresh_creator_keywords" in source
    assert "refresh_client_topics" not in source
    assert "generate_auto_topics" not in source
    doctor_source = inspect.getsource(DoctorProfession.seed_keywords)
    assert "refresh_client_topics" in doctor_source
    assert "generate_auto_topics" in doctor_source


def test_creator_search_payload_and_keyword_mapping():
    from backend.tg.services.creator_topics import (
        build_search_payload,
        keywords_from_search,
        search_profile_error,
        weight_for_score,
    )

    assert search_profile_error({"niche": "food"}) == (
        "Add details about niche in Keywords before searching."
    )
    assert search_profile_error({"niche_details": "late night eats"}) == (
        "Add niche in Keywords before searching."
    )
    assert search_profile_error({"niche": "food", "niche_details": "late night eats"}) is None

    payload = build_search_payload(
        {
            "name": "Jigar",
            "website_url": "https://streetromeo.com",
            "instagram": "streetromeo",
            "niche": "street food",
            "niche_details": "Mumbai night eats",
            "example_topics": ["pav bhaji"],
            "example_scripts": ["Wait. Fridge empty?"],
        },
        language="english",
        prompt="more beginner-friendly",
    )
    assert payload["name"] == "Jigar"
    assert payload["website"] == "https://streetromeo.com"
    assert payload["instagram"] == "streetromeo"
    assert payload["niche"] == "street food"
    assert payload["niche_details"] == "Mumbai night eats"
    assert payload["example_topics"] == ["pav bhaji"]
    assert payload["example_scripts"] == ["Wait. Fridge empty?"]
    assert payload["language"] == "english"
    assert payload["prompt"] == "more beginner-friendly"
    assert "web search" in payload["scoring"]

    rows = keywords_from_search(
        [
            {"id": "a", "title": "Hot pav bhaji", "score": 88},
            {"id": "b", "title": "Monsoon snacks", "score": 61},
            {"id": "c", "title": "Old recipe", "score": 22},
            {"id": "d", "title": "Late night vada", "score": 70},
        ]
    )
    assert [row["text"] for row in rows] == [
        "Hot pav bhaji",
        "Late night vada",
        "Monsoon snacks",
        "Old recipe",
    ]
    assert rows[0]["recommendation_score"] == 88
    assert rows[0]["source"] == "auto"
    assert weight_for_score(88) == "high"
    assert weight_for_score(61) == "medium"
    assert weight_for_score(22) == "low"
    assert rows[0]["weight"] == "high"
    assert rows[2]["weight"] == "medium"


def test_coerce_content_suggestion_row_fills_plug_import_gaps():
    from backend.tg.database import coerce_content_suggestion_row
    from backend.tg.schemas import ContentSuggestionItem

    raw = {
        "id": "plug-0d56b3c7-2dc",
        "title_en": "Street food myths",
        "topic_text": "Street food myths",
        "format": "short",
        "script": "Hello",
        "origin": "generated",
    }
    row = coerce_content_suggestion_row(raw)
    assert row is not None
    item = ContentSuggestionItem(**row)
    assert item.topic_id == ""
    assert item.video_type == "short"
    assert item.reasoning == ""
    assert item.format == "Short"


def test_creator_search_copies_plug_openai_web_search():
    import inspect

    from backend.tg.services import creator_topics

    source = inspect.getsource(creator_topics._responses_create)
    assert '"type": "web_search"' in source or "'type': 'web_search'" in source
    assert "tool_choice" in source
    assert creator_topics.TOPIC_SCHEMA["properties"]["topics"]["minItems"] == 4
    assert creator_topics.TOPIC_SCHEMA["properties"]["topics"]["maxItems"] == 4
    prompt = (creator_topics.PROMPTS_DIR / "topic_search.txt").read_text(encoding="utf-8")
    assert "You MUST use the web search tool" in prompt
    assert "Return EXACTLY 4 topics" in prompt
