"""공지 팝업이 메뉴 클릭을 가로채도 게시판에 들어가는지 확인한다.

2026-08-29 사내 공지가 게시되자 그룹웨어 홈에 jQuery UI 다이얼로그
(`.popnoti_lyr`)가 뜨면서 상단 "게시판" 메뉴의 클릭 지점을 덮었다. 팝업이
스스로 닫히지 않아 Playwright 클릭이 30초마다 `subtree intercepts pointer
events`로 죽었고, 주말 폴링·시간별 재시도가 전부 실패해 2026-08-31 주차
식단표를 놓쳤다. 실제 브라우저 없이 그 상황을 재현한다.
"""

import pytest
from playwright.sync_api import Error as PlaywrightError

from menu_bot.scraper import _click_past_overlays


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
