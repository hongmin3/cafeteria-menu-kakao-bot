from contextlib import closing
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from menu_bot import advisor, ocr, pipeline
from menu_bot.db import MenuDB
from menu_bot.models import MenuEntry
from menu_bot.scraper import GroupwareScraper, ScrapeError


MONDAY = date(2026, 11, 23)
NEXT_MONDAY = MONDAY + timedelta(days=7)
TITLE = "[뷰웍스] 2026-11-23 식단표"


def entry(day, text, post_id="10"):
    return MenuEntry(day, "뷰웍스", "중식", "일반식", text, source_post_id=post_id)


def run_pipeline(db, tmp_path, monkeypatch, entries, week=MONDAY, post_id="10"):
    monkeypatch.setattr(pipeline, "_download", lambda url, folder: folder / "menu.png")
    monkeypatch.setattr(pipeline, "recognize", lambda _: [])
    monkeypatch.setattr(pipeline, "parse_ocr_lines", lambda *_: entries)
    return pipeline.process_manifest(
        [{"id": post_id, "title": TITLE, "images": ["https://example.invalid/menu.png"]}],
        db, tmp_path, progress=lambda _: None, week_start=week, use_advisor=False,
    )


def test_ingest_replaces_only_the_selected_week_and_keeps_previous_on_empty(tmp_path, monkeypatch):
    with closing(MenuDB(tmp_path / "menu.db")) as db:
        run_pipeline(db, tmp_path, monkeypatch, [entry(MONDAY, "콩나물국")])
        run_pipeline(db, tmp_path, monkeypatch, [entry(NEXT_MONDAY, "미역국")], NEXT_MONDAY)
        assert [row["menu_text"] for row in db.query(MONDAY)] == ["콩나물국"]
        result = run_pipeline(db, tmp_path, monkeypatch, [])
        assert result["entries"] == 0
        assert [row["menu_text"] for row in db.query(MONDAY)] == ["콩나물국"]
        assert [row["menu_text"] for row in db.query(NEXT_MONDAY)] == ["미역국"]


def test_failed_insert_rolls_back_before_another_post_commits(tmp_path, monkeypatch):
    with closing(MenuDB(tmp_path / "menu.db")) as db:
        run_pipeline(db, tmp_path, monkeypatch, [entry(MONDAY, "기존 식단")])
        db.conn.execute(
            """CREATE TRIGGER simulated_write_failure BEFORE INSERT ON menu_entries
               WHEN NEW.menu_text = '중단'
               BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END"""
        )
        stats = run_pipeline(db, tmp_path, monkeypatch, [entry(MONDAY, "중단")])
        assert len(stats["errors"]) == 1
        run_pipeline(db, tmp_path, monkeypatch, [entry(MONDAY, "다른 게시물", "11")], post_id="11")
        with closing(MenuDB(tmp_path / "menu.db", read_only=True)) as reader:
            rows = {row["source_post_id"]: row for row in reader.query(MONDAY)}
            assert rows["10"]["menu_text"] == "기존 식단"
            assert rows["10"]["source_start_date"] == MONDAY.isoformat()
            assert rows["11"]["source_post_sequence"] > rows["10"]["source_post_sequence"]


def test_partial_conversion_preserves_an_existing_meal(tmp_path, monkeypatch):
    tuesday = MONDAY + timedelta(days=1)
    with closing(MenuDB(tmp_path / "menu.db")) as db:
        run_pipeline(db, tmp_path, monkeypatch, [entry(MONDAY, "월요일"), entry(tuesday, "화요일")])
        stats = run_pipeline(db, tmp_path, monkeypatch, [entry(MONDAY, "부분 결과")])
        assert len(stats["errors"]) == 1
        assert [row["menu_text"] for row in db.query(MONDAY)] == ["월요일"]
        assert [row["menu_text"] for row in db.query(tuesday)] == ["화요일"]


def test_download_rechecks_existing_url_and_preserves_it_on_login_html(tmp_path, monkeypatch):
    url = "https://example.invalid/test.png?version=1"
    target = pipeline.image_path(url, tmp_path)
    target.write_bytes(b"old")
    response = SimpleNamespace(
        headers={"Content-Type": "image/png"}, content=b"new", raise_for_status=lambda: None,
    )
    monkeypatch.setattr(pipeline.requests, "get", lambda *a, **k: response)
    assert pipeline._download(url, tmp_path).read_bytes() == b"new"
    response.headers["Content-Type"] = "text/html"
    with pytest.raises(ValueError, match="이미지"):
        pipeline._download(url, tmp_path)
    assert target.read_bytes() == b"new"


def test_broken_ocr_cache_recovers_then_new_image_invalidates_it(tmp_path, monkeypatch):
    image = tmp_path / "menu.png"
    image.write_bytes(b"original")
    cache = image.with_suffix(".png.ocr.json")
    cache.write_text("{", encoding="utf-8")
    invocations = []

    def recognize(path):
        invocations.append(path.read_bytes())
        return [{"text": "식단", "x": .1, "y": .2, "width": .2, "height": .1}]

    monkeypatch.setattr(ocr, "_active_provider", lambda: SimpleNamespace(recognize=recognize))
    assert ocr.recognize(image) == ocr.recognize(image)
    assert len(invocations) == 1
    image.write_bytes(b"new")
    ocr.recognize(image)
    assert invocations == [b"original", b"new"]


def test_advisor_retry_state_failure_keeps_ocr_result(tmp_path, monkeypatch):
    image = tmp_path / "sample.png"
    image.write_bytes(b"test")
    entries = [entry(MONDAY, "식단")]
    post = pipeline.post_from_title("10", TITLE, [])
    monkeypatch.setattr(advisor, "find_signals", lambda *_: [{"kind": "example"}])
    monkeypatch.setattr(advisor, "build_prompt", lambda *_: "")
    monkeypatch.setattr(advisor, "failure_mail", lambda *_: ("테스트", "테스트"))

    def fail_to_write(*_):
        raise OSError("simulated full storage")

    def fail_advisor(*_):
        raise advisor.AdvisorError("auth", "simulated")

    monkeypatch.setattr(advisor, "_mark_alerted", fail_to_write)
    result = advisor.advise(
        post, image, [], entries, runner=fail_advisor, enabled=True,
        progress=lambda _: None, send=lambda *a, **k: True,
        alert_state_path=tmp_path / "alert.json",
    )
    assert result == entries


def test_post_metadata_tracks_page_and_reports_missing_identifiers():
    scraper = GroupwareScraper(SimpleNamespace())
    locator = SimpleNamespace(evaluate_all=lambda _: [{"id": "7", "title": "title"}])
    page = SimpleNamespace(locator=lambda _: locator)

    assert scraper._read_titles(page, 3) == [{"id": "7", "title": "title", "page": 3}]
    locator.evaluate_all = lambda _: [{"title": "no identifier"}]
    with pytest.raises(ScrapeError, match="게시물 목록"):
        scraper._read_titles(page, 3)
