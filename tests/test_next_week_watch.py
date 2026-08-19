from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from menu_bot.config import Settings
from menu_bot.next_week_watch import check_next_week_posted


NOW = datetime(2026, 8, 21, 22, 0, tzinfo=ZoneInfo("Asia/Seoul"))  # 금요일 22시


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        groupware_user="user",
        groupware_password="pass",
        groupware_url="https://groupware.example.com/board",
        post_prefixes=("뷰웍스",),
        default_location="",
        database_path=tmp_path / "menus.db",
        timezone="Asia/Seoul",
        webhook_token="",
        ocr_provider="auto",
        next_week_state_path=tmp_path / "next_week_watch_state.json",
    )


class FakeScraper:
    def __init__(self, titles: list[str]):
        self.titles = titles
        self.list_calls = 0
        self.collect_calls = 0

    def list_recent_titles(self, max_pages: int = 1) -> list[dict]:
        self.list_calls += 1
        return [{"id": f"post-{i}", "title": title} for i, title in enumerate(self.titles)]

    def collect(self, max_pages: int = 1) -> list[dict]:
        self.collect_calls += 1
        return [{"id": f"post-{i}", "title": title, "images": []} for i, title in enumerate(self.titles)]


class ExplodingScraper:
    def list_recent_titles(self, max_pages: int = 1):
        raise AssertionError("이미 확인된 주차는 그룹웨어에 접속하면 안 된다")

    def collect(self, max_pages: int = 1):
        raise AssertionError("이미 확인된 주차는 그룹웨어에 접속하면 안 된다")


def test_next_week_post_found_and_state_saved(tmp_path: Path):
    settings = _settings(tmp_path)
    scraper = FakeScraper(["[뷰웍스] 2026-08-24 ~ 08-28 식단표"])
    result = check_next_week_posted(settings, now=NOW, scraper=scraper)
    assert result.found is True
    assert result.already_confirmed is False
    assert result.target_week_start.isoformat() == "2026-08-24"
    assert settings.next_week_state_path.exists()


def test_next_week_post_not_found_yet(tmp_path: Path):
    settings = _settings(tmp_path)
    scraper = FakeScraper(["[뷰웍스] 2026-08-17 ~ 08-21 식단표"])  # 이번 주 게시글만 있음
    result = check_next_week_posted(settings, now=NOW, scraper=scraper)
    assert result.found is False
    assert not settings.next_week_state_path.exists()


def test_already_confirmed_week_skips_groupware_access(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.next_week_state_path.write_text('{"confirmed_week_start": "2026-08-24"}', encoding="utf-8")
    result = check_next_week_posted(settings, now=NOW, scraper=ExplodingScraper())
    assert result.already_confirmed is True
    assert result.found is True


def test_different_weekend_recheck_after_previous_confirmation(tmp_path: Path):
    settings = _settings(tmp_path)
    # 지난주에 확인된 상태가 남아있어도 이번 주 대상(다음주 월요일)이 다르면 다시 확인한다.
    settings.next_week_state_path.write_text('{"confirmed_week_start": "2026-08-17"}', encoding="utf-8")
    scraper = FakeScraper(["[뷰웍스] 2026-08-24 ~ 08-28 식단표"])
    result = check_next_week_posted(settings, now=NOW, scraper=scraper)
    assert result.already_confirmed is False
    assert result.found is True
    assert scraper.list_calls == 1
    assert scraper.collect_calls == 1
