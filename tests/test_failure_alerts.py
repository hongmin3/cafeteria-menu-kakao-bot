"""수집이 막혔을 때 사람이 제때 알게 되는지 확인한다.

2026-08-29 사내 공지 팝업이 게시판 진입을 막았을 때, 첫 실패부터 마감 알림까지
44시간 동안 34번을 헛돌면서도 아무 알림이 없었다. 그 사이 금요일 정기 수집도
같은 이유로 죽어 있었다. 여기서 검증하는 것은 두 가지다 — 연속 실패가 쌓이면
마감을 기다리지 않고 알리는가, 그리고 조용히 넘어가기 쉬운 실패(제목 형식
변경)를 실패로 잡아내는가.
"""

from datetime import date, datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from menu_bot.config import Settings
from menu_bot.next_week_watch import STUCK_ALERT_AFTER, ensure_week_menu
from menu_bot.notify import FAILURE_RESULTS


MONDAY = datetime(2026, 8, 31, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
TARGET = "2026-08-31"


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


class MailSpy:
    def __init__(self, ok: bool = True):
        self.ok = ok
        self.sent: list[tuple[str, str]] = []

    def __call__(self, subject: str, body: str, mail=None, progress=print) -> bool:
        self.sent.append((subject, body))
        return self.ok

    @property
    def stuck_alerts(self) -> list[tuple[str, str]]:
        return [item for item in self.sent if "연속 실패" in item[0]]


class BlockedScraper:
    """게시판 진입이 막힌 상황(공지 팝업, 로그인 화면 변경, 사내망 장애)."""

    def __init__(self, message: str = "[게시판 메뉴 열기] 화면이 넘어가지 않았습니다."):
        self.message = message

    def list_recent_titles(self, max_pages: int = 1):
        raise RuntimeError(self.message)

    def collect(self, max_pages: int = 1):
        raise RuntimeError(self.message)


class TitleScraper:
    """게시글은 있지만 제목 형식이 우리가 아는 것과 다른 상황."""

    def __init__(self, titles: list[str]):
        self.titles = titles

    def list_recent_titles(self, max_pages: int = 1) -> list[dict]:
        return [{"id": f"post-{i}", "title": t} for i, t in enumerate(self.titles)]

    def collect(self, max_pages: int = 1) -> list[dict]:
        return [
            {"id": f"post-{i}", "title": t, "images": []}
            for i, t in enumerate(self.titles)
        ]


def _state(settings: Settings) -> dict:
    return json.loads(settings.next_week_state_path.read_text(encoding="utf-8"))


def _run(settings, scraper, mail, times: int) -> None:
    for hour in range(times):
        ensure_week_menu(
            settings,
            now=MONDAY.replace(hour=9 + hour),
            scraper=scraper,
            send=mail,
            progress=lambda *_: None,
        )


def test_alerts_after_consecutive_failures_without_waiting_for_deadline(tmp_path: Path):
    """연속 실패가 임계치에 닿으면 마감(일요일 22시) 전에 곧바로 알린다."""
    settings, mail = _settings(tmp_path), MailSpy()

    _run(settings, BlockedScraper(), mail, times=STUCK_ALERT_AFTER)

    assert len(mail.stuck_alerts) == 1
    subject, body = mail.stuck_alerts[0]
    assert f"{STUCK_ALERT_AFTER}회 연속 실패" in subject
    # 무엇이 막았는지가 본문에 실려야 메일만 보고 다음 행동을 정할 수 있다.
    assert "게시판 메뉴 열기" in body
    assert _state(settings)["stuck_alert_sent_week"] == TARGET


def test_stays_quiet_until_the_threshold(tmp_path: Path):
    """한두 번의 일시적 실패로 사람을 깨우지 않는다."""
    settings, mail = _settings(tmp_path), MailSpy()

    _run(settings, BlockedScraper(), mail, times=STUCK_ALERT_AFTER - 1)

    assert mail.stuck_alerts == []


def test_alerts_only_once_per_week(tmp_path: Path):
    """실패가 계속돼도 경보는 주차당 한 번이다(재시도는 계속된다)."""
    settings, mail = _settings(tmp_path), MailSpy()

    _run(settings, BlockedScraper(), mail, times=STUCK_ALERT_AFTER + 5)

    assert len(mail.stuck_alerts) == 1


def test_alert_is_retried_when_the_mail_fails(tmp_path: Path):
    """메일 발송이 실패하면 보냈다고 기록하지 않아 다음 시도에서 다시 보낸다."""
    settings = _settings(tmp_path)
    failing, working = MailSpy(ok=False), MailSpy()

    _run(settings, BlockedScraper(), failing, times=STUCK_ALERT_AFTER)
    assert "stuck_alert_sent_week" not in _state(settings)

    _run(settings, BlockedScraper(), working, times=1)
    assert len(working.stuck_alerts) == 1


def test_unreadable_titles_count_as_failure_not_as_absence(tmp_path: Path):
    """제목 형식이 바뀌면 '게시글 없음'이 아니라 실패로 잡아 알린다.

    이것이 가장 조용한 실패다. 식단표가 눈앞에 올라와 있는데도 아무 일도
    일어나지 않은 채 그 주를 통째로 놓친다.
    """
    settings, mail = _settings(tmp_path), MailSpy()
    # 접두어는 맞지만 연도가 없어 주차를 읽어 낼 수 없는 제목.
    scraper = TitleScraper(["[뷰웍스] 8/31 ~ 9/4 주간 식단표"])

    _run(settings, scraper, mail, times=STUCK_ALERT_AFTER)

    results = [attempt["result"] for attempt in _state(settings)["attempts"]]
    assert results == ["title_unreadable"] * STUCK_ALERT_AFTER
    assert "title_unreadable" in FAILURE_RESULTS
    assert len(mail.stuck_alerts) == 1
    assert "8/31 ~ 9/4" in mail.stuck_alerts[0][1]


def test_absent_post_is_not_a_failure(tmp_path: Path):
    """아직 게시되지 않은 것은 정상이다 — 경보를 보내지 않는다.

    금요일 저녁부터 매시 확인하므로, 게시 전 몇 번은 반드시 이렇게 나온다.
    """
    settings, mail = _settings(tmp_path), MailSpy()
    scraper = TitleScraper(["[뷰웍스] 2026-08-24 ~ 2026-08-28 주간식단표"])  # 지난 주차

    _run(settings, scraper, mail, times=STUCK_ALERT_AFTER + 2)

    results = [attempt["result"] for attempt in _state(settings)["attempts"]]
    assert set(results) == {"not_posted"}
    assert mail.stuck_alerts == []


def test_streak_resets_once_the_menu_arrives(tmp_path: Path):
    """중간에 성공하면 연속 실패는 0부터 다시 센다."""
    settings, mail = _settings(tmp_path), MailSpy()

    _run(settings, BlockedScraper(), mail, times=STUCK_ALERT_AFTER - 1)
    # 게시글이 아직 없는 정상 상태가 한 번 끼어들면 연속이 끊긴다.
    _run(settings, TitleScraper(["[뷰웍스] 2026-08-24 ~ 2026-08-28"]), mail, times=1)
    _run(settings, BlockedScraper(), mail, times=STUCK_ALERT_AFTER - 1)

    assert mail.stuck_alerts == []


# ── 테스트가 진짜 메일을 보내지 않는다는 보장 ────────────────────────────


def test_real_mail_sending_is_blocked_during_tests():
    """`send=` 주입을 빠뜨려도 실제 메일은 나가지 않는다.

    2026-08-31에 주입을 빠뜨린 테스트 하나가 서버에서 pytest를 돌릴 때마다
    운영 담당자에게 미확보 알림을 보냈다. conftest의 두 겹(설정 비우기 +
    SMTP 차단)이 살아 있는지 여기서 확인한다.
    """
    from menu_bot.notify import MailSettings, send_mail

    # 1겹: 설정이 비어 있어 발송 전에 물러난다.
    assert send_mail("제목", "본문", progress=lambda *_: None) is False

    # 2겹: 설정이 채워져 있어도 소켓을 열지 못한다.
    configured = MailSettings(
        host="smtp.example.com", port=587, user="u", password="p",
        security="starttls", sender="u@example.com",
        recipients=("someone@example.com",), timeout=5,
    )
    assert configured.configured is True
    assert send_mail("제목", "본문", mail=configured, progress=lambda *_: None) is False
