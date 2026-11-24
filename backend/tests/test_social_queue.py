"""Queued static posts are stored as Mongo status=queued."""


def test_fetch_scheduled_posts_queries_status_queued(monkeypatch):
    captured = {}

    class Col:
        def find(self, query):
            captured["query"] = query
            return [
                {"id": "later", "project_id": "c1", "status": "queued", "queue_order": 2},
                {"id": "first", "project_id": "c1", "status": "queued", "queue_order": 1},
                {"id": "unnumbered", "project_id": "c1", "status": "queued"},
            ]

    monkeypatch.setattr("backend.tg.database.social_posts_col", lambda: Col())
    from backend.tg.database import fetch_scheduled_posts

    rows = fetch_scheduled_posts("c1")
    assert captured["query"] == {"project_id": "c1", "status": "queued"}
    assert [row["id"] for row in rows] == ["unnumbered", "first", "later"]
    assert all(row["publish_status"] == "scheduled" for row in rows)
    assert all(row["client_id"] == "c1" for row in rows)
