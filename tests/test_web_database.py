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
        post_prefixes=("뷰웍스",),
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
    assert client.get("/health").json() == {"ok": True, "entries": 1}
    response = ask(client)
    assert response.status_code == 200
    assert "현미밥" in response.json()["template"]["outputs"][0]["simpleText"]["text"]
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_healthy_database_without_entries_returns_unpublished_notice(db_path):
    MenuDB(db_path).close()
    client = TestClient(web.app)
    assert client.get("/health").json() == {"ok": True, "entries": 0}
    reply = ask(client).json()["template"]["outputs"][0]["simpleText"]["text"]
    assert "아직 그룹웨어에 올라오지 않았어요" in reply


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
