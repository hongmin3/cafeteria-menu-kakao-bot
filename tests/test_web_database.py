"""Validates: REQ-API-001."""

from contextlib import closing
from datetime import datetime, timedelta
import sqlite3
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from menu_bot import web
from menu_bot.config import Settings
from menu_bot.db import MenuDB
from menu_bot.models import MenuEntry


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "menu #1.db"
    settings = Settings(
        groupware_user="",
        groupware_password="",
        groupware_url="",
        post_prefixes=("뷰웍스", "안양"),
        default_location="",
        database_path=path,
        timezone="Asia/Seoul",
        webhook_token="test-token",
        ocr_provider="auto",
        next_week_state_path=tmp_path / "state.json",
    )
    monkeypatch.setattr(web, "get_settings", lambda: settings)
    return path


def ask(client, utterance="월요일 점심"):
    return client.post(
        "/kakao/skill/test-token", json={"userRequest": {"utterance": utterance}}
    )


def test_skill_and_health_leave_existing_database_mode_alone(db_path):
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    monday = today - timedelta(days=today.weekday())
    with closing(MenuDB(db_path)) as db:
        db.replace_entries(
            "post", [MenuEntry(monday, "뷰웍스", "중식", "일반식", "현미밥", source_post_id="post")]
        )
        assert db.conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"

    client = TestClient(web.app)
    status = client.get("/health").json()
    assert status["ok"] and status["entries"] == 1
    assert status["current_week"]["status"] == "partial"
    response = ask(client)
    assert response.status_code == 200
    assert "현미밥" in response.json()["template"]["outputs"][0]["simpleText"]["text"]
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_healthy_database_without_entries_returns_unpublished_notice(db_path):
    MenuDB(db_path).close()
    client = TestClient(web.app)
    status = client.get("/health").json()
    assert status["ok"] and status["entries"] == 0
    assert status["current_week"]["status"] == "empty"
    reply = ask(client).json()["template"]["outputs"][0]["simpleText"]["text"]
    assert "아직 확인하지 못했어요" in reply


@pytest.mark.parametrize("failure", ["missing", "corrupt", "io_error"])
def test_unavailable_database_returns_kakao_reply_and_unhealthy_status(db_path, monkeypatch, failure):
    if failure == "corrupt":
        db_path.write_bytes(b"invalid database")
    elif failure == "io_error":
        def fail_connect(*args, **kwargs):
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(sqlite3, "connect", fail_connect)

    client = TestClient(web.app, raise_server_exceptions=False)
    assert client.post("/kakao/skill/wrong-token", json={}).status_code == 404
    response = ask(client)
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "2.0"
    text = payload["template"]["outputs"][0]["simpleText"]["text"]
    assert "잠시 후 다시" in text
    assert "disk I/O error" not in text
    assert any(button["label"] == "사용방법" for button in payload["template"]["quickReplies"])
    assert client.get("/health").status_code == 503
    assert ask(client, "사용방법").status_code == 200
    if failure == "missing":
        assert not db_path.exists()


@pytest.mark.parametrize(
    "body",
    [b"{", b"[]", b'{"userRequest":null}', b'{"userRequest":{"utterance":5}}', b" " * 65537],
    ids=["syntax", "root-type", "request-type", "utterance-type", "length"],
)
def test_malformed_or_oversized_skill_body_returns_400(db_path, body):
    client = TestClient(web.app, raise_server_exceptions=False)
    assert client.post("/kakao/skill/test-token", content=body).status_code == 400


def test_previous_token_works_only_while_configured(db_path, monkeypatch):
    client = TestClient(web.app)
    monkeypatch.setenv("KAKAO_WEBHOOK_TOKEN_PREVIOUS", "old-token")
    body = {"userRequest": {"utterance": "사용방법"}}
    assert client.post("/kakao/skill/old-token", json=body).status_code == 200
    monkeypatch.delenv("KAKAO_WEBHOOK_TOKEN_PREVIOUS")
    assert client.post("/kakao/skill/old-token", json=body).status_code == 404


def test_range_offers_day_buttons_without_using_db(db_path):
    client = TestClient(web.app)
    result = ask(client, "월~금 점심").json()["template"]
    assert "요일" in result["outputs"][0]["simpleText"]["text"]
    assert [entry["messageText"] for entry in result["quickReplies"][:5]] == [
        f"{day}요일 중식" for day in "월화수목금"
    ]
    assert not db_path.exists()


def test_week_choices_preserve_site_meal_and_corner(db_path):
    client = TestClient(web.app)
    result = ask(client, "이번 주 안양 점심 건강식만").json()["template"]
    assert result["quickReplies"][0]["messageText"] == "월요일 안양 중식 건강식"
    assert not db_path.exists()


def test_source_button_only_uses_approved_https_config(db_path, monkeypatch):
    client = TestClient(web.app)
    monkeypatch.setenv("KAKAO_MENU_SOURCE_URL", "https://example.test/cafeteria")
    labels = [button["label"] for button in ask(client, "사용방법").json()["template"]["quickReplies"]]
    assert "원본 식단표 확인" in labels
    source = ask(client, "원본 식단표 확인")
    assert "https://example.test/cafeteria" in source.text
    monkeypatch.setenv("KAKAO_MENU_SOURCE_URL", "https://user:password@example.test/cafeteria")
    assert "example.test" not in ask(client, "원본 식단표 확인").text
    assert "식당 담당자" in ask(client, "알레르기").text
    assert not db_path.exists()


def test_long_meal_pages_preserve_items_and_original_date(db_path):
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    monday = today - timedelta(days=today.weekday())
    items = [f"메뉴{number:03d} 이름이 긴 식단 항목" for number in range(150)]
    with closing(MenuDB(db_path)) as db:
        db.replace_entries("post", [
            MenuEntry(monday, "뷰웍스", "중식", "일반식", " · ".join(items), source_post_id="post"),
        ])
    client = TestClient(web.app)
    utterance = "월요일 점심"
    seen = []
    for _ in range(20):
        reply = ask(client, utterance).json()["template"]
        assert 1 <= len(reply["outputs"]) <= 3
        for result in reply["outputs"]:
            text = result["simpleText"]["text"]
            assert len(text) <= 500
            assert f"{monday:%m월 %d일}" in text
            seen.extend(line[2:] for line in text.splitlines() if line.startswith("- "))
        followups = [entry for entry in reply["quickReplies"] if entry["label"] == "다음 항목"]
        if not followups:
            break
        utterance = followups[0]["messageText"]
        assert f"{monday:%m/%d}" in utterance
    assert seen == items


def test_probe_checks_real_current_day_answer_and_requires_auth(db_path, monkeypatch):
    monday = datetime(2026, 11, 30, 12, tzinfo=ZoneInfo("Asia/Seoul"))
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return monday.astimezone(tz)

    monkeypatch.setattr(web, "datetime", FixedDateTime)
    monkeypatch.setenv("MENUBOT_PROBE_TOKEN", "probe-only")
    with closing(MenuDB(db_path)) as db:
        db.replace_entries("post", [
            MenuEntry(monday.date(), "뷰웍스", "중식", "안내", "휴무",
                      status="no_service", source_post_id="post"),
        ])
    client = TestClient(web.app)
    assert client.get("/kakao/probe", headers={"Authorization": "Bearer test-token"}).status_code == 404
    response = client.get("/kakao/probe", headers={"Authorization": "Bearer probe-only"})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["status"] == "partial"
    assert "휴무" not in response.text


def test_probe_reports_db_unavailable_without_exposing_details(db_path, monkeypatch):
    monkeypatch.setenv("MENUBOT_PROBE_TOKEN", "probe-only")
    client = TestClient(web.app)
    response = client.get("/kakao/probe", headers={"Authorization": "Bearer probe-only"})
    assert response.status_code == 503
    assert response.json()["ok"] is False
    assert response.json()["status"] == "db_unavailable"
    assert str(db_path) not in response.text
