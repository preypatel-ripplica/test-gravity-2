"""Offline transform checks (no Mongo required)."""

from __future__ import annotations

from . import transform as T


def test_core_mappings() -> None:
    client = {
        "id": "client-1",
        "name": "Dr Test",
        "website_url": "https://example.com",
        "specialty": "Ortho",
    }
    topics = [
        {
            "id": "topic-1",
            "client_id": "client-1",
            "text": "Knee pain",
            "weight": "high",
            "source": "auto",
            "recommendation_score": 80,
        }
    ]
    doctor = {
        "id": "client-1",
        "sections": [
            {
                "id": "sec-1",
                "title": "About",
                "fields": [{"id": "f1", "label": "Clinic", "value": "City"}],
            }
        ],
    }
    project = T.transform_project(client, topics, doctor)
    assert project["id"] == "client-1"
    assert project["name"] == "Dr Test"
    assert len(project["topics"]) == 1

    weekly = T.transform_weekly_tracker(
        {
            "id": "weekly:client-1:2025:6:1",
            "client_id": "client-1",
            "year": 2025,
            "month": 6,
            "week": 1,
            "cards": [{"id": "card-1", "type": "long_video", "title": "Week video"}],
        },
        project_id="client-1",
    )
    assert weekly["project_id"] == "client-1"
    assert len(weekly["cards"]) == 1
    assert "kind" not in weekly

    custom = T.transform_custom_tracker(
        {
            "id": "custom:client-1",
            "client_id": "client-1",
            "tasks": [{"id": "t1", "title": "Call", "done": True, "comment": "ok"}],
        },
        project_id="client-1",
    )
    assert custom["id"] == "custom:client-1"
    assert custom["tasks"][0]["done"] is True
    assert "cards" not in custom


if __name__ == "__main__":
    test_core_mappings()
    print("transform tests OK")
