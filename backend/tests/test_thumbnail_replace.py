"""Thumbnail replace, explicit-content flag, and local reference mixing."""

from backend.tg.database import _normalize_locale_payload
from backend.tg.openai_log import call_with_openai_retry, is_sexual_moderation_block
from backend.tg.services.youtube_metadata import (
    build_reference_edit_files,
    delete_replaced_thumbnail,
    thumbnail_aspect_ok,
    use_newest_youtube_refs,
)


def test_long_and_short_aspect_ratios():
    assert thumbnail_aspect_ok(1920, 1080, portrait=False)
    assert thumbnail_aspect_ok(1939, 1080, portrait=False)
    assert not thumbnail_aspect_ok(2020, 1080, portrait=False)
    assert thumbnail_aspect_ok(1080, 1920, portrait=True)
    assert not thumbnail_aspect_ok(1080, 1920, portrait=False)
    assert not thumbnail_aspect_ok(1000, 1000, portrait=False)
    assert not thumbnail_aspect_ok(1000, 1000, portrait=True)
    assert not thumbnail_aspect_ok(0, 1080, portrait=False)


def test_normalize_keeps_explicit_error_until_a_url_is_saved():
    blocked = _normalize_locale_payload({
        "yt_title": "Pain",
        "yt_thumbnail_error": "explicit",
    })
    assert blocked["yt_thumbnail_url"] == ""
    assert blocked["yt_thumbnail_error"] == "explicit"

    replaced = _normalize_locale_payload({
        "yt_title": "Pain",
        "yt_thumbnail_url": "https://storage.googleapis.com/bucket/thumbnails/new.png",
        "yt_thumbnail_error": "explicit",
    })
    assert replaced["yt_thumbnail_url"].endswith("new.png")
    assert replaced["yt_thumbnail_error"] == ""

    ignored = _normalize_locale_payload({"yt_thumbnail_error": "other"})
    assert ignored["yt_thumbnail_error"] == ""


class _Response:
    def __init__(self, text):
        self.text = text
        self.status_code = 400


def _sexual_error():
    exc = Exception("Client error '400 Bad Request'")
    exc.response = _Response(
        '{"error":{"code":"moderation_blocked","moderation_details":{"categories":["sexual"]}}}'
    )
    return exc


def test_sexual_moderation_block_is_not_retried(monkeypatch):
    monkeypatch.setattr("backend.tg.openai_log.time.sleep", lambda _wait: None)
    assert is_sexual_moderation_block(_sexual_error())
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise _sexual_error()

    try:
        call_with_openai_retry(fn, tag="yt-thumbnail", wait=0)
    except Exception as exc:
        assert is_sexual_moderation_block(exc)
    assert calls["n"] == 1


def test_other_thumbnail_errors_still_retry_once(monkeypatch):
    monkeypatch.setattr("backend.tg.openai_log.time.sleep", lambda _wait: None)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise TimeoutError("timed out")

    try:
        call_with_openai_retry(fn, tag="yt-thumbnail", wait=0)
    except TimeoutError:
        pass
    assert calls["n"] == 2


def test_local_only_does_not_download_youtube_refs(monkeypatch):
    calls = []

    def download(refs):
        calls.append(list(refs))
        return [("image[]", ("ref-0.jpg", b"yt", "image/jpeg"))]

    monkeypatch.setattr(
        "backend.tg.services.youtube_metadata._download_reference_files",
        download,
    )
    files = build_reference_edit_files([], [("local.png", b"abc", "image/png")])
    assert calls == []
    assert files == [("image[]", ("local.png", b"abc", "image/png"))]
    assert use_newest_youtube_refs(picked=False, has_local=True) is False


def test_picked_youtube_refs_are_mixed_with_local_files(monkeypatch):
    monkeypatch.setattr(
        "backend.tg.services.youtube_metadata._download_reference_files",
        lambda refs: [("image[]", ("ref-0.jpg", b"yt", "image/jpeg"))],
    )
    files = build_reference_edit_files(
        [{"id": "video-1"}],
        [("local.png", b"abc", "image/png")],
    )
    assert [item[1][0] for item in files] == ["ref-0.jpg", "local.png"]
    assert use_newest_youtube_refs(picked=True, has_local=True) is False
    assert use_newest_youtube_refs(picked=False, has_local=False) is True


def test_old_thumbnail_is_deleted_only_when_no_other_language_uses_it(monkeypatch):
    deleted = []
    monkeypatch.setattr(
        "backend.tg.services.youtube_metadata.delete_file",
        lambda path: deleted.append(path),
    )

    def path_for(url, folder):
        if "thumbnails/shared.png" in str(url):
            return "thumbnails/shared.png"
        if "thumbnails/old.png" in str(url):
            return "thumbnails/old.png"
        return None

    monkeypatch.setattr("backend.tg.services.youtube_metadata.bucket_object_path", path_for)
    shared = {
        "hinglish": {"yt_thumbnail_url": "https://storage.googleapis.com/b/thumbnails/shared.png"},
        "arabic": {"yt_thumbnail_url": "https://storage.googleapis.com/b/thumbnails/shared.png"},
    }
    delete_replaced_thumbnail(shared["hinglish"]["yt_thumbnail_url"], shared, "hinglish")
    assert deleted == []

    only = {
        "hinglish": {"yt_thumbnail_url": "https://storage.googleapis.com/b/thumbnails/old.png"},
        "arabic": {"yt_thumbnail_url": ""},
    }
    delete_replaced_thumbnail(only["hinglish"]["yt_thumbnail_url"], only, "hinglish")
    assert deleted == ["thumbnails/old.png"]

    delete_replaced_thumbnail("https://i.ytimg.com/vi/abc/hqdefault.jpg", only, "hinglish")
    assert deleted == ["thumbnails/old.png"]
