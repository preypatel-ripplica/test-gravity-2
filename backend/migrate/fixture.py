"""Synthetic TG-shaped docs to exercise the migrator when source DB is empty."""

from __future__ import annotations

from typing import Any

from . import transform as T


def build_fixture_bundle() -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    client_id = "fixture-client-1"
    client = {
        "id": client_id,
        "name": "Fixture Clinic",
        "website_url": "https://fixture.example.com",
        "specialty": "Physiotherapy",
        "designation": "PT",
        "description": "Migrator fixture project",
        "reference_youtube_channel": "https://youtube.com/@fixture",
        "ai_videos_started_from": "2025-01",
    }
    topics = [
        {
            "id": "fixture-topic-1",
            "client_id": client_id,
            "text": "Lower back pain",
            "weight": "high",
            "source": "manual",
            "recommendation_score": 75,
        },
        {
            "id": "fixture-topic-2",
            "client_id": client_id,
            "text": "Knee rehab",
            "weight": "medium",
            "source": "auto",
            "recommendation_score": 60,
        },
    ]
    doctor = {
        "id": client_id,
        "sections": [
            {
                "id": "sec-about",
                "title": "About",
                "fields": [
                    {"id": "f1", "label": "City", "value": "Mumbai"},
                ],
            }
        ],
    }
    channel = {
        "id": "UCfixture0001",
        "client_id": client_id,
        "title": "Fixture Channel",
        "subscriber_count": 100,
        "video_count": 2,
        "language": "hinglish",
        "google_credentials": {
            "token": "fixture-access",
            "refresh_token": "fixture-refresh",
            "scopes": ["https://www.googleapis.com/auth/youtube"],
        },
    }
    videos = [
        {
            "id": "vidfixture01",
            "client_id": client_id,
            "channel_id": "UCfixture0001",
            "title": "Back pain basics",
            "published_at": "2025-06-01T00:00:00Z",
            "view_count": 50,
            "topic_id": "fixture-topic-1",
        }
    ]
    plan = {
        "id": client_id,
        "content_suggestions": {
            "items": [
                {
                    "id": "fixture-plan-1",
                    "topic_id": "fixture-topic-1",
                    "title_en": "Back pain tips",
                    "script": "Welcome to the clinic...",
                    "format": "long",
                }
            ]
        },
    }
    content_video = {
        "id": f"cv:{client_id}:fixture-topic-1",
        "client_id": client_id,
        "topic_id": "fixture-topic-1",
        "topic_text": "Lower back pain",
        "content_plan_item_id": "fixture-plan-1",
        "yt_locales": {"hinglish": {"yt_title": "Back pain", "yt_description": "d"}},
        "youtube_urls": [],
    }
    report = {
        "id": "fixture-report-1",
        "client_id": client_id,
        "report_month": "2025-06",
        "status": "ready",
        "narrative": {"summary": "Good month"},
        "html_url": "<html>ok</html>",
    }
    social_post = {
        "id": "fixture-spost-1",
        "client_id": client_id,
        "source_type": "keyword",
        "topic_id": "fixture-topic-1",
        "brief": {"caption": "Stretch daily"},
        "publish_status": "draft",
        "publish_targets": ["instagram"],
    }
    schedule = {
        "id": client_id,
        "client_id": client_id,
        "frequency": "weekly",
        "selected_days": ["mon", "wed"],
        "posts_per_day": 1,
    }
    weekly = {
        "id": f"weekly:{client_id}:2025:6:1",
        "client_id": client_id,
        "year": 2025,
        "month": 6,
        "week": 1,
        "cards": [
            {
                "id": "fixture-card-1",
                "type": "long",
                "title": "Week 1 long",
                "stage": "planned",
                "sort_order": 0,
                "topic_id": "fixture-topic-1",
                "content_plan_item_id": "fixture-plan-1",
                "assets": {"script_text": "Welcome to the clinic..."},
            }
        ],
    }
    custom = {
        "id": f"custom:{client_id}",
        "client_id": client_id,
        "tasks": [
            {"id": "fixture-custom-1", "title": "Send report", "done": False}
        ],
    }
    creds = {
        "id": client_id,
        "credentials": [
            {
                "id": "cred-1",
                "service": "portal",
                "username": "doc",
                "password": "secret",
                "notes": "fixture",
            }
        ],
    }

    yt_secret = T.transform_youtube_secret(channel, project_id=client_id)
    assert yt_secret
    bundle = {
        "projects": [T.transform_project(client, topics, doctor)],
        "project_secrets": [
            yt_secret,
            *T.transform_manual_credentials(creds, project_id=client_id),
        ],
        "plan_items": T.transform_plan_items(plan, project_id=client_id),
        "weekly_trackers": [T.transform_weekly_tracker(weekly, project_id=client_id)],
        "custom_trackers": [T.transform_custom_tracker(custom, project_id=client_id)],
        "channels": [
            T.transform_channel(
                channel, project_id=client_id, secret_id=yt_secret["id"]
            )
        ],
        "videos": [T.transform_video(v, project_id=client_id) for v in videos],
        "productions": [T.transform_production(content_video, project_id=client_id)],
        "monthly_reports": [T.transform_report(report, project_id=client_id)],
        "social_posts": [T.transform_social_post(social_post, project_id=client_id)],
        "social_schedules": [
            T.transform_social_schedule(schedule, project_id=client_id)
        ],
    }
    stats = {
        "source_clients": 1,
        "source_counts": {},  # fixture — skip source-unchanged check
        "bundle_counts": {k: len(v) for k, v in bundle.items()},
        "errors": [],
        "topic_embedded": sum(len(p.get("topics") or []) for p in bundle["projects"]),
        "fixture": True,
    }
    return bundle, stats
