"""그룹웨어 화면이 예상과 다를 때 크롤러가 어떻게 버티는지 확인한다.

2026-08-29 사내 공지가 게시되자 그룹웨어 홈에 jQuery UI 다이얼로그
(`.popnoti_lyr`)가 뜨면서 상단 "게시판" 메뉴의 클릭 지점을 덮었다. 팝업이
스스로 닫히지 않아 Playwright 클릭이 30초마다 `subtree intercepts pointer
events`로 죽었고, 주말 폴링·시간별 재시도가 전부 실패해 2026-08-31 주차
식단표를 놓쳤다. 실제 브라우저 없이 그 상황과, 같은 식으로 깨질 수 있는
다른 경우들(메뉴 이름 변경, 로그인 실패, 목록 구조 변경)을 재현한다.
"""

import pytest
from playwright.sync_api import Error as PlaywrightError

from menu_bot.scraper import (
    ScrapeError,
    _click_past_overlays,
    _describe_blockers,
    _save_failure_snapshot,
)


INTERCEPT = (
    "Locator.click: Timeout 30000ms exceeded.\n"
    '  - <div class="box_top">…</div> from <div class="ui-dialog popnoti_lyr">…</div>'
    " subtree intercepts pointer events"
)


class FakePage:
    """`_dismiss_overlays`가 부르는 evaluate만 흉내 낸다."""

    def __init__(self, overlays: int = 1):
        self.overlays = overlays
        self.dismiss_calls = 0

    def evaluate(self, script, arg=None):
        self.dismiss_calls += 1
        dismissed, self.overlays = self.overlays, 0
        return dismissed


class FakeLocator:
    """앞선 `intercept_times`번의 클릭만 덮개에 가로채이는 요소."""

    def __init__(self, intercept_times: int, other_error: str | None = None):
        self.intercept_times = intercept_times
        self.other_error = other_error
        self.clicks = 0
        self.dispatched = 0
        self.waited = False

    def wait_for(self, timeout=None):
        self.waited = True

    def click(self, timeout=None):
        self.clicks += 1
        if self.other_error:
            raise PlaywrightError(self.other_error)
        if self.clicks <= self.intercept_times:
            raise PlaywrightError(INTERCEPT)

    def dispatch_event(self, name):
        assert name == "click"
        self.dispatched += 1


def test_dismisses_notice_popup_before_clicking():
    """덮개를 먼저 치우므로 첫 클릭부터 통과한다."""
    page, target = FakePage(overlays=1), FakeLocator(intercept_times=0)

    _click_past_overlays(page, target)

    assert target.waited and target.clicks == 1
    assert page.dismiss_calls == 1
    assert target.dispatched == 0


def test_retries_when_a_new_overlay_appears_mid_click():
    """화면 전환 중 새 레이어가 떠도 다시 치우고 눌러 성공한다."""
    page, target = FakePage(), FakeLocator(intercept_times=1)

    _click_past_overlays(page, target)

    assert target.clicks == 2
    assert page.dismiss_calls == 2
    assert target.dispatched == 0


def test_falls_back_to_dispatching_click_when_overlay_persists():
    """끝까지 가로채이면 요소에 click 이벤트를 직접 보내 앞으로 나아간다."""
    page, target = FakePage(), FakeLocator(intercept_times=99)

    _click_past_overlays(page, target)

    assert target.clicks == 3  # attempts 기본값만큼만 시도한다
    assert target.dispatched == 1


def test_unrelated_failures_still_surface():
    """덮개와 무관한 실패는 삼키지 않는다 — 알림에 사유가 남아야 한다."""
    page = FakePage()
    target = FakeLocator(intercept_times=0, other_error="net::ERR_CONNECTION_REFUSED")

    with pytest.raises(PlaywrightError, match="ERR_CONNECTION_REFUSED"):
        _click_past_overlays(page, target)

    assert target.dispatched == 0


# ── 화면이 예상과 다를 때 남기는 사유 ────────────────────────────────────


def test_scrape_error_names_the_step_and_the_reason():
    """메일만 보고 다음 행동을 정할 수 있도록 단계와 사유를 함께 싣는다."""
    error = ScrapeError("게시판 메뉴 열기", "화면이 넘어가지 않았습니다.", "덮개: ui-dialog")

    assert error.step == "게시판 메뉴 열기"
    assert "게시판 메뉴 열기" in str(error)
    assert "화면이 넘어가지 않았습니다." in str(error)
    assert "덮개: ui-dialog" in str(error)
    # 기존 호출부가 RuntimeError로 잡고 있으므로 그 계약을 깨지 않아야 한다.
    assert isinstance(error, RuntimeError)


class BlockedPage:
    """로그인 화면으로 튕겼고 레이어까지 떠 있는 상태."""

    def evaluate(self, script, arg=None):
        return {
            "layers": ["ui-front.popnoti_lyr"],
            "loginForm": True,
            "url": "https://groupware.example.com/login",
        }


class BrokenPage:
    """화면을 읽는 것 자체가 실패하는 상태(페이지가 이미 닫힘 등)."""

    def evaluate(self, script, arg=None):
        raise PlaywrightError("Target page, context or browser has been closed")

    def screenshot(self, path=None, full_page=False):
        raise PlaywrightError("closed")

    def content(self):
        raise PlaywrightError("closed")


def test_blockers_are_described_in_plain_words():
    """무엇이 막았는지가 한 줄로 정리돼야 로그를 뒤지지 않는다."""
    described = _describe_blockers(BlockedPage())

    assert "로그인 화면" in described
    assert "popnoti_lyr" in described
    assert "https://groupware.example.com/login" in described


def test_diagnostics_never_mask_the_original_failure():
    """진단이 실패해도 예외를 내지 않는다 — 본 오류를 가리면 안 된다."""
    assert _describe_blockers(BrokenPage()) == ""
    assert _save_failure_snapshot(BrokenPage(), "titles") is None
