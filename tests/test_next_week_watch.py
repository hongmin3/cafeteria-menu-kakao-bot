from datetime import date, datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from menu_bot.config import Settings
from menu_bot.db import MenuDB
from menu_bot.models import MenuEntry
from menu_bot.next_week_watch import (
    check_next_week_deadline,
    check_next_week_posted,
    ensure_week_menu,
)


NOW = datetime(2026, 8, 21, 22, 0, tzinfo=ZoneInfo("Asia/Seoul"))  # 금요일 22시
SUNDAY_NIGHT = datetime(2026, 8, 23, 22, 0, tzinfo=ZoneInfo("Asia/Seoul"))  # 일요일 22시(마감)
TARGET = "2026-08-24"


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

    @staticmethod
    def _id(title: str) -> str:
        # 게시글마다 다른 id여야 한다. 같은 id면 "이미 처리한 게시글"로 걸러진다.
        return "post-" + str(abs(hash(title)) % 10**8)

    def list_recent_titles(self, max_pages: int = 1) -> list[dict]:
        self.list_calls += 1
        return [{"id": self._id(t), "title": t} for t in self.titles]

    def collect(self, max_pages: int = 1) -> list[dict]:
        self.collect_calls += 1
        return [{"id": self._id(t), "title": t, "images": []} for t in self.titles]


class ExplodingScraper:
    def list_recent_titles(self, max_pages: int = 1):
        raise AssertionError("이미 확인된 주차는 그룹웨어에 접속하면 안 된다")

    def collect(self, max_pages: int = 1):
        raise AssertionError("이미 확인된 주차는 그룹웨어에 접속하면 안 된다")


class FailingScraper:
    """그룹웨어 접속 자체가 실패하는 상황(사내망 장애, 로그인 화면 변경 등)."""

    def __init__(self, message: str = "net::ERR_CONNECTION_TIMED_OUT"):
        self.message = message

    def list_recent_titles(self, max_pages: int = 1):
        raise RuntimeError(self.message)

    def collect(self, max_pages: int = 1):
        raise RuntimeError(self.message)


class MailSpy:
    def __init__(self, ok: bool = True):
        self.ok = ok
        self.sent: list[tuple[str, str]] = []

    def __call__(self, subject: str, body: str, mail=None, progress=print) -> bool:
        self.sent.append((subject, body))
        return self.ok


def _ingesting_process(entries: int = 2):
    """게시글을 실제로 저장하는 process_manifest 대역.

    OCR·네트워크 없이 저장 경로만 재현해, 알림 본문에 들어가는 식단 구조가
    실제 DB에서 만들어지는지까지 검증한다.
    """

    def process(rows, db, image_dir, progress=print, week_start=None):
        from menu_bot.models import SourcePost

        for row in rows:
            post = SourcePost(
                post_id=row["id"], title=row["title"], location="뷰웍스",
                start_date=week_start or date(2026, 8, 24), image_urls=[],
            )
            db.save_post(post)
            db.replace_entries(post.post_id, [
                MenuEntry(
                    service_date=week_start, location="뷰웍스", meal_type="중식",
                    category="일반식", menu_text="제육볶음 · 콩나물국", status="normal",
                    source_post_id=post.post_id,
                ),
                MenuEntry(
                    service_date=week_start, location="뷰웍스", meal_type="중식",
                    category="PLUS 코너", menu_text="현미밥", status="normal",
                    source_post_id=post.post_id,
                ),
            ][:entries])
        return {"posts": len(rows), "images": 1, "entries": entries * len(rows),
                "filtered_entries": 0, "skipped_images": 0, "errors": []}

    return process


def _state(settings: Settings) -> dict:
    return json.loads(settings.next_week_state_path.read_text(encoding="utf-8"))


def _results(state: dict) -> list[str]:
    return [attempt["result"] for attempt in state.get("attempts", [])]


def test_next_week_post_found_and_confirmed_sends_success_mail(tmp_path: Path):
    settings = _settings(tmp_path)
    scraper = FakeScraper([f"[뷰웍스] {TARGET} ~ 08-28 식단표"])
    mail = MailSpy()
    result = check_next_week_posted(
        settings, now=NOW, scraper=scraper, process=_ingesting_process(), send=mail
    )
    assert result.found is True
    assert result.confirmed is True
    assert result.already_confirmed is False
    assert result.notified is True
    assert result.target_week_start.isoformat() == TARGET

    state = _state(settings)
    assert state["confirmed_week_start"] == TARGET
    assert state["success_notified_week"] == f"{TARGET}:primary"
    assert _results(state) == ["confirmed"]

    subject, body = mail.sent[0]
    assert "수집 완료" in subject
    # 알림에 실제 식단 구조가 들어가야 한다.
    assert "08월 24일(월)" in body
    assert "제육볶음" in body
    assert "공통 PLUS" in body


def test_success_mail_not_resent_for_same_week(tmp_path: Path):
    settings = _settings(tmp_path)
    mail = MailSpy()
    for _ in range(2):
        check_next_week_posted(
            settings, now=NOW, scraper=FakeScraper([f"[뷰웍스] {TARGET} ~ 08-28 식단표"]),
            process=_ingesting_process(), send=mail,
        )
    assert len(mail.sent) == 1


def test_post_found_but_zero_entries_is_not_confirmed(tmp_path: Path):
    """제목만 올라오고 이미지가 없거나 OCR이 아무것도 못 읽은 경우.

    이걸 성공으로 처리하면 폴링이 멈춰 그 주 식단을 통째로 놓친다.
    """
    settings = _settings(tmp_path)
    mail = MailSpy()
    result = check_next_week_posted(
        settings, now=NOW, scraper=FakeScraper([f"[뷰웍스] {TARGET} ~ 08-28 식단표"]), send=mail
    )
    assert result.found is True
    assert result.confirmed is False
    assert result.error is not None
    assert mail.sent == []
    state = _state(settings)
    assert "confirmed_week_start" not in state
    assert _results(state) == ["ingest_failed"]


def test_next_week_post_not_found_records_attempt(tmp_path: Path):
    settings = _settings(tmp_path)
    scraper = FakeScraper(["[뷰웍스] 2026-08-17 ~ 08-21 식단표"])  # 이번 주 게시글만 있음
    mail = MailSpy()
    result = check_next_week_posted(settings, now=NOW, scraper=scraper, send=mail)
    assert result.found is False
    assert result.confirmed is False
    assert mail.sent == []
    state = _state(settings)
    assert "confirmed_week_start" not in state
    assert _results(state) == ["not_posted"]


def test_scraper_failure_is_recorded_with_reason(tmp_path: Path):
    settings = _settings(tmp_path)
    mail = MailSpy()
    result = check_next_week_posted(
        settings, now=NOW, scraper=FailingScraper(), send=mail, progress=lambda *_: None
    )
    assert result.found is False
    assert result.confirmed is False
    assert "ERR_CONNECTION_TIMED_OUT" in (result.error or "")
    assert mail.sent == []
    state = _state(settings)
    assert _results(state) == ["error"]
    assert "ERR_CONNECTION_TIMED_OUT" in state["attempts"][0]["error"]


def test_already_confirmed_week_skips_groupware_access(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.next_week_state_path.write_text(
        json.dumps({"target_week_start": TARGET, "confirmed_week_start": TARGET}), encoding="utf-8"
    )
    result = check_next_week_posted(settings, now=NOW, scraper=ExplodingScraper())
    assert result.already_confirmed is True
    assert result.found is True
    assert result.confirmed is True


def test_different_weekend_recheck_after_previous_confirmation(tmp_path: Path):
    settings = _settings(tmp_path)
    # 지난주에 확인된 상태가 남아 있어도 이번 대상 주차가 다르면 다시 확인한다.
    settings.next_week_state_path.write_text(
        json.dumps({"target_week_start": "2026-08-17", "confirmed_week_start": "2026-08-17"}),
        encoding="utf-8",
    )
    scraper = FakeScraper([f"[뷰웍스] {TARGET} ~ 08-28 식단표"])
    result = check_next_week_posted(
        settings, now=NOW, scraper=scraper, process=_ingesting_process(), send=MailSpy()
    )
    assert result.already_confirmed is False
    assert result.confirmed is True
    assert scraper.list_calls == 1
    assert scraper.collect_calls == 1
    # 주차가 바뀌면 지난 주 시도 기록은 버리고 새로 센다.
    assert _results(_state(settings)) == ["confirmed"]


def test_corrupt_state_file_does_not_block_collection(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.next_week_state_path.write_text("{ 깨진 json", encoding="utf-8")
    result = check_next_week_posted(
        settings, now=NOW, scraper=FakeScraper([f"[뷰웍스] {TARGET} ~ 08-28 식단표"]),
        process=_ingesting_process(), send=MailSpy(),
    )
    assert result.confirmed is True


def test_deadline_alerts_when_next_week_still_missing(tmp_path: Path):
    settings = _settings(tmp_path)
    # 주말 내내 게시글이 없었던 상황을 만든다.
    for _ in range(3):
        check_next_week_posted(
            settings, now=NOW, scraper=FakeScraper(["[뷰웍스] 2026-08-17 ~ 08-21 식단표"]),
            send=MailSpy(),
        )
    mail = MailSpy()
    result = check_next_week_deadline(settings, now=SUNDAY_NIGHT, send=mail)
    assert result.confirmed is False
    assert result.alerted is True
    subject, body = mail.sent[0]
    assert "아직 못 받았습니다" in subject
    assert "게시글이 아직 없음: 3회" in body
    assert _state(settings)["deadline_alert_sent_week"] == TARGET


def test_deadline_reports_crawl_failures(tmp_path: Path):
    settings = _settings(tmp_path)
    check_next_week_posted(
        settings, now=NOW, scraper=FailingScraper("로그인 화면을 찾지 못했습니다"),
        send=MailSpy(), progress=lambda *_: None,
    )
    mail = MailSpy()
    check_next_week_deadline(settings, now=SUNDAY_NIGHT, send=mail)
    _, body = mail.sent[0]
    assert "그룹웨어 접속/스크래핑 실패: 1회" in body
    assert "로그인 화면을 찾지 못했습니다" in body


def test_deadline_is_quiet_when_week_already_confirmed(tmp_path: Path):
    settings = _settings(tmp_path)
    check_next_week_posted(
        settings, now=NOW, scraper=FakeScraper([f"[뷰웍스] {TARGET} ~ 08-28 식단표"]),
        process=_ingesting_process(), send=MailSpy(),
    )
    mail = MailSpy()
    result = check_next_week_deadline(settings, now=SUNDAY_NIGHT, send=mail)
    assert result.confirmed is True
    assert result.alerted is False
    assert mail.sent == []


def test_deadline_alert_sent_only_once(tmp_path: Path):
    settings = _settings(tmp_path)
    mail = MailSpy()
    first = check_next_week_deadline(settings, now=SUNDAY_NIGHT, send=mail)
    second = check_next_week_deadline(settings, now=SUNDAY_NIGHT, send=mail)
    assert first.alerted is True
    assert second.alerted is False
    assert second.already_alerted is True
    assert len(mail.sent) == 1


def test_deadline_retries_when_mail_send_failed(tmp_path: Path):
    settings = _settings(tmp_path)
    failing = MailSpy(ok=False)
    result = check_next_week_deadline(settings, now=SUNDAY_NIGHT, send=failing)
    assert result.alerted is False
    assert result.already_alerted is False
    assert "deadline_alert_sent_week" not in _state(settings)
    # 발송이 실패했으니 다음 실행에서 다시 시도해야 한다.
    working = MailSpy()
    assert check_next_week_deadline(settings, now=SUNDAY_NIGHT, send=working).alerted is True


# ── 1시간 간격 재시도 (일요일 22시 마감 이후) ──────────────
SUNDAY_LATE = datetime(2026, 8, 23, 23, 0, tzinfo=ZoneInfo("Asia/Seoul"))
MONDAY_EARLY = datetime(2026, 8, 24, 1, 0, tzinfo=ZoneInfo("Asia/Seoul"))
TUESDAY = datetime(2026, 8, 25, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 8, 21), "2026-08-17"),  # 금 → 이번 주
        (date(2026, 8, 22), "2026-08-24"),  # 토 → 다가오는 주
        (date(2026, 8, 23), "2026-08-24"),  # 일 → 다가오는 주
        (date(2026, 8, 24), "2026-08-24"),  # 월 → 이번 주
        (date(2026, 8, 28), "2026-08-24"),  # 금 → 이번 주
    ],
)
def test_week_for_does_not_shift_across_midnight(today: date, expected: str):
    """일요일 밤과 월요일 새벽이 같은 주차를 가리켜야 재시도가 엉뚱한 주로 넘어가지 않는다."""
    from menu_bot.next_week_watch import _week_for

    assert _week_for(today).isoformat() == expected


def test_ensure_menu_collects_when_week_is_missing(tmp_path: Path):
    settings = _settings(tmp_path)
    scraper = FakeScraper([f"[뷰웍스] {TARGET} ~ 08-28 식단표"])
    mail = MailSpy()
    result = ensure_week_menu(
        settings, now=SUNDAY_LATE, scraper=scraper, process=_ingesting_process(), send=mail
    )
    assert result.confirmed is True
    assert result.target_week_start.isoformat() == TARGET
    assert scraper.collect_calls == 1
    assert len(mail.sent) == 1


def test_ensure_menu_stops_once_the_menu_is_in(tmp_path: Path):
    """확보되면 그룹웨어에 접속하지 않고 즉시 끝난다 — 이게 '루프가 멈춘다'의 실제 동작."""
    settings = _settings(tmp_path)
    ensure_week_menu(
        settings, now=SUNDAY_LATE, scraper=FakeScraper([f"[뷰웍스] {TARGET} ~ 08-28 식단표"]),
        process=_ingesting_process(), send=MailSpy(),
    )
    mail = MailSpy()
    for moment in (MONDAY_EARLY, TUESDAY):
        result = ensure_week_menu(settings, now=moment, scraper=ExplodingScraper(), send=mail)
        assert result.already_confirmed is True
        assert result.confirmed is True
    assert mail.sent == []


def test_ensure_menu_uses_the_db_not_just_the_state_file(tmp_path: Path):
    """월요일 정기 수집이 상태 파일을 건드리지 않고 DB만 채운 경우.

    상태 파일만 보면 이미 들어온 주차를 계속 다시 긁는다.
    """
    settings = _settings(tmp_path)
    db = MenuDB(settings.database_path)
    try:
        db.replace_entries("p", [
            MenuEntry(service_date=date(2026, 8, 24), location="뷰웍스", meal_type="중식",
                      category="일반식", menu_text="제육볶음", source_post_id="p"),
        ])
    finally:
        db.close()
    result = ensure_week_menu(settings, now=MONDAY_EARLY, scraper=ExplodingScraper())
    assert result.already_confirmed is True
    # 주말 폴링·마감 점검이 헛돌지 않도록 상태 파일에도 확보 사실을 남긴다.
    assert _state(settings)["confirmed_week_start"] == TARGET


def test_ensure_menu_keeps_retrying_while_post_is_absent(tmp_path: Path):
    settings = _settings(tmp_path)
    mail = MailSpy()
    for moment in (SUNDAY_LATE, MONDAY_EARLY, TUESDAY):
        result = ensure_week_menu(
            settings, now=moment, scraper=FakeScraper(["[뷰웍스] 2026-08-17 ~ 08-21 식단표"]),
            send=mail,
        )
        assert result.confirmed is False
        # 게시글이 없는 것은 이상 상황이 아니므로 오류로 표시하지 않는다(종료 코드 0).
        assert result.error is None
    assert _results(_state(settings)) == ["not_posted"] * 3
    # 일요일 밤에는 조용하지만, 그 주가 시작된 뒤(월요일)에도 답할 수 없으면
    # 한 번은 알려야 한다. 화요일에 또 보내지는 않는다.
    assert len(mail.sent) == 1
    assert "아직 못 받았습니다" in mail.sent[0][0]


def _other_sites_process(week_start_default=date(2026, 8, 24)):
    """뷰웍스 게시글 없이 다른 사업장 게시글만 올라온 상황을 재현한다."""

    def process(rows, db, image_dir, progress=print, week_start=None):
        from menu_bot.models import SourcePost

        week = week_start or week_start_default
        for index, location in enumerate(("화성", "안양")):
            post = SourcePost(post_id=f"other-{index}", title=f"[{location}] {week}",
                              location=location, start_date=week, image_urls=[])
            db.save_post(post)
            db.replace_entries(post.post_id, [
                MenuEntry(service_date=week, location=location, meal_type="중식",
                          category="일반식", menu_text="지점메뉴", source_post_id=post.post_id),
            ])
        return {"posts": 2, "images": 2, "entries": 2,
                "filtered_entries": 0, "skipped_images": 0, "errors": []}

    return process


def test_other_sites_only_answers_but_keeps_waiting_for_primary(tmp_path: Path):
    """2026-08-24 주차에 실제로 났던 사고.

    [화성]·[안양] 게시글만 올라와 113건이 저장됐는데 "수집 완료" 메일이 나갔고,
    챗봇은 공통 식단을 고르지 못해 "확인할 수 없어요"로 답했다. 지금은 두
    사업장 식단을 합쳐 답하되, 뷰웍스 게시글은 계속 기다린다.
    """
    settings = _settings(tmp_path)
    mail = MailSpy()
    result = check_next_week_posted(
        settings, now=NOW, scraper=FakeScraper([f"[화성] {TARGET} ~ 08-28"]),
        process=_other_sites_process(), send=mail, progress=lambda *_: None,
    )
    assert result.found is True
    assert result.servable is True, "다른 사업장 식단으로라도 답할 수 있어야 한다"
    assert result.confirmed is False, "뷰웍스 게시글을 받을 때까지 확보가 아니다"
    state = _state(settings)
    assert "confirmed_week_start" not in state, "폴링이 멈추면 안 된다"
    assert _results(state) == ["fallback_only"]
    subject, body = mail.sent[0]
    assert "다른 사업장 기준" in subject
    assert "뷰웍스 게시글이 아직 없어" in body


def test_other_sites_only_keeps_hourly_retry_alive(tmp_path: Path):
    settings = _settings(tmp_path)
    ensure_week_menu(
        settings, now=SUNDAY_LATE, scraper=FakeScraper([f"[화성] {TARGET} ~ 08-28"]),
        process=_other_sites_process(), send=MailSpy(), progress=lambda *_: None,
    )
    # 다음 시각에도 그룹웨어를 다시 확인해야 한다(즉시 종료하면 안 된다).
    scraper = FakeScraper([f"[뷰웍스] {TARGET} ~ 08-28 식단표"])
    result = ensure_week_menu(
        settings, now=MONDAY_EARLY, scraper=scraper, process=_ingesting_process(),
        send=MailSpy(), progress=lambda *_: None,
    )
    assert scraper.collect_calls == 1
    assert result.confirmed is True


def test_deadline_reports_the_other_sites_reason(tmp_path: Path):
    settings = _settings(tmp_path)
    check_next_week_posted(
        settings, now=NOW, scraper=FakeScraper([f"[화성] {TARGET} ~ 08-28"]),
        process=_other_sites_process(), send=MailSpy(), progress=lambda *_: None,
    )
    mail = MailSpy()
    check_next_week_deadline(settings, now=SUNDAY_NIGHT, send=mail)
    _, body = mail.sent[0]
    assert "다른 사업장 식단만 확보" in body


def test_ensure_menu_records_connection_failures(tmp_path: Path):
    settings = _settings(tmp_path)
    result = ensure_week_menu(
        settings, now=MONDAY_EARLY, scraper=FailingScraper(), progress=lambda *_: None
    )
    assert result.error is not None
    assert _results(_state(settings)) == ["error"]


def test_ensure_menu_does_not_confirm_on_zero_entries(tmp_path: Path):
    settings = _settings(tmp_path)
    result = ensure_week_menu(
        settings, now=MONDAY_EARLY, scraper=FakeScraper([f"[뷰웍스] {TARGET} ~ 08-28 식단표"]),
        send=MailSpy(), progress=lambda *_: None,
    )
    assert result.found is True
    assert result.confirmed is False
    assert _results(_state(settings)) == ["ingest_failed"]


def test_ensure_menu_success_mail_is_sent_once(tmp_path: Path):
    settings = _settings(tmp_path)
    mail = MailSpy()
    ensure_week_menu(
        settings, now=SUNDAY_LATE, scraper=FakeScraper([f"[뷰웍스] {TARGET} ~ 08-28 식단표"]),
        process=_ingesting_process(), send=mail,
    )
    ensure_week_menu(
        settings, now=MONDAY_EARLY, scraper=FakeScraper([f"[뷰웍스] {TARGET} ~ 08-28 식단표"]),
        process=_ingesting_process(), send=mail,
    )
    assert len(mail.sent) == 1


def test_week_structure_marks_special_and_no_service(tmp_path: Path):
    from menu_bot.notify import format_week_structure

    db = MenuDB(tmp_path / "menus.db")
    try:
        db.replace_entries("p1", [
            MenuEntry(service_date=date(2026, 8, 24), location="뷰웍스", meal_type="중식",
                      category="일반식", menu_text="말복 특식 · 갈비낙지탕", status="special",
                      source_post_id="p1"),
            MenuEntry(service_date=date(2026, 8, 25), location="뷰웍스", meal_type="조식",
                      category="안내", menu_text="전사 휴무", status="no_service",
                      source_post_id="p1"),
        ])
        text = format_week_structure(db, date(2026, 8, 24))
    finally:
        db.close()
    assert "저장된 항목 2개" in text
    assert "✨특식" in text
    assert "⛔미운영" in text
    assert "08월 26일(수)" in text and "(저장된 항목 없음)" in text


def test_send_mail_without_config_returns_false(tmp_path: Path, monkeypatch):
    from menu_bot.notify import MailSettings, send_mail

    unconfigured = MailSettings(
        host="", port=587, user="", password="", security="starttls",
        sender="", recipients=(), timeout=5,
    )
    logs: list[str] = []
    assert send_mail("제목", "본문", mail=unconfigured, progress=logs.append) is False
    assert any("설정" in line for line in logs)
