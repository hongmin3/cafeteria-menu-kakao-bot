from __future__ import annotations

import platform
import re
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from .config import Settings


def _goto_settling(page, url: str, settle_ms: int = 1500) -> None:
    """SSO 로그인 화면은 홈 URL에서 login.vieworks.com으로 여러 번
    리다이렉트한 뒤에야 멈춘다. 그 경합 때문에 goto()가 "interrupted by
    another navigation"이나 net::ERR_ABORTED로 실패하는 일이 잦다. 둘 다
    최종적으로는 원하는 화면에 도달하므로 무시하고, 리다이렉트가 가라앉을
    시간을 좀 더 준다."""
    try:
        page.goto(url, wait_until="load")
    except PlaywrightError as exc:
        message = str(exc)
        if "ERR_ABORTED" not in message and "interrupted by another navigation" not in message:
            raise
    page.wait_for_timeout(settle_ms)


# 홈 화면을 덮는 레이어. jQuery UI 다이얼로그(공지 팝업), 그 뒤의 반투명
# 오버레이, 화면 전환 중 잠깐 뜨는 로딩 레이어가 모두 여기에 해당한다.
OVERLAY_SELECTORS = ".ui-dialog, .ui-widget-overlay, .loading_lyr"


def _dismiss_overlays(page) -> int:
    """홈 화면을 덮는 공지 팝업·로딩 레이어를 치우고 치운 개수를 돌려준다.

    그룹웨어 홈은 게시된 공지가 있으면 jQuery UI 다이얼로그(`.popnoti_lyr`)를
    띄우는데, 이 레이어가 좌상단 652×977 영역을 덮어 상단 메뉴 "게시판"의
    클릭 지점(537,55)을 가로챈다. 팝업은 스스로 닫히지 않으므로 Playwright의
    클릭은 30초를 기다린 끝에 `subtree intercepts pointer events`로 죽는다.
    2026-08-29 사내 공지가 올라온 뒤 주말 폴링과 시간별 재시도가 전부 이
    지점에서 실패해 2026-08-31 주차 식단표를 통째로 놓쳤다.

    닫기(X)만 누른다. "오늘 하루 보지 않기"류는 사내 계정 설정을 바꾸므로
    건드리지 않는다. 닫기 버튼이 없거나 눌러도 남는 레이어는 화면에서만
    숨긴다 — 서버 요청이 아니라 DOM 조작이라 그룹웨어 상태에 영향이 없다.
    """
    return page.evaluate(
        """(selectors) => {
          const shown = el => getComputedStyle(el).display !== 'none'
            && getComputedStyle(el).visibility !== 'hidden'
            && el.getBoundingClientRect().width > 0;
          let dismissed = 0;
          for (const layer of document.querySelectorAll(selectors)) {
            if (!shown(layer)) continue;
            const close = layer.querySelector('.ui-dialog-titlebar-close');
            if (close) close.click();
            if (shown(layer)) layer.style.display = 'none';
            dismissed += 1;
          }
          return dismissed;
        }""",
        OVERLAY_SELECTORS,
    )


def _click_past_overlays(page, target, timeout_ms: int = 15_000, attempts: int = 3) -> None:
    """덮개를 치우고 클릭한다. 그래도 가로채이면 다시 치우고 재시도한다.

    한 번 치우는 것으로 끝내지 않는 이유는, 화면 전환 중 로딩 레이어가 새로
    뜨거나 공지 팝업이 여러 개 쌓이는 경우가 있어서다. 마지막 시도까지
    가로채이면 요소에 click 이벤트를 직접 보낸다(메뉴 앵커의 onclick이 그대로
    실행된다). 덮개와 무관한 실패는 그대로 올려 보내 사유가 상태 파일과
    알림 메일에 남게 한다.
    """
    target.wait_for(timeout=timeout_ms)
    for attempt in range(attempts):
        _dismiss_overlays(page)
        try:
            target.click(timeout=timeout_ms)
            return
        except PlaywrightError as exc:
            if "intercepts pointer events" not in str(exc):
                raise
            if attempt == attempts - 1:
                target.dispatch_event("click")
                return


class GroupwareScraper:
    """로그인 후 자유게시판에서 식단 게시물과 본문 이미지 URL을 읽는다."""

    def __init__(self, settings: Settings, headless: bool = True):
        self.settings = settings
        self.headless = headless

    def _launch(self, pw):
        """플랫폼에 맞는 Chromium을 띄운다.

        macOS/Windows 데스크톱에는 Google Chrome이 설치돼 있어 그대로 chrome
        채널을 쓰지만, 사내 Linux 서버에는 Chrome이 없어 Playwright가
        내려받은 번들 Chromium을 써야 한다. Ubuntu 24.04는 AppArmor가 비특권
        user namespace를 막아 번들 Chromium의 샌드박스가 뜨지 않으므로,
        Linux에서는 --no-sandbox를 붙인다(그룹웨어 페이지만 여는 headless
        전용 프로세스이고, 서버에서 일반 웹서핑을 하지 않는다).
        """
        channel = self.settings.browser_channel
        args: list[str] = []
        if channel == "auto":
            if platform.system() == "Linux":
                channel = ""
                args = ["--no-sandbox", "--disable-dev-shm-usage"]
            else:
                channel = "chrome"
        elif platform.system() == "Linux":
            args = ["--no-sandbox", "--disable-dev-shm-usage"]
        kwargs: dict = {"headless": self.headless}
        if channel:
            kwargs["channel"] = channel
        if args:
            kwargs["args"] = args
        return pw.chromium.launch(**kwargs)

    def _login_and_open_board(self, page) -> None:
        _goto_settling(page, self.settings.groupware_url)
        if page.locator("#auth_id").count() and page.locator("#auth_pw").count():
            page.locator("#auth_id").fill(self.settings.groupware_user)
            page.locator("#auth_pw").fill(self.settings.groupware_password)
            page.locator('input[type="submit"]').click()
            host = re.escape(urlsplit(self.settings.groupware_url).netloc)
            page.wait_for_url(re.compile(rf"https?://{host}/"), timeout=30_000)
        _goto_settling(page, self.settings.groupware_url, settle_ms=1000)
        _click_past_overlays(page, page.get_by_text("게시판", exact=True).first)
        _click_past_overlays(page, page.get_by_text("자유", exact=True).first)
        page.locator("a._atcl").first.wait_for(timeout=30_000)

    def _title_pattern(self) -> re.Pattern:
        return re.compile(r"^\[(?:" + "|".join(map(re.escape, self.settings.post_prefixes)) + r")]")

    def collect(self, max_pages: int = 2) -> list[dict]:
        if not self.settings.groupware_user or not self.settings.groupware_password:
            raise RuntimeError("GROUPWARE_USER와 GROUPWARE_PASSWORD가 필요합니다.")
        with sync_playwright() as pw:
            browser = self._launch(pw)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            self._login_and_open_board(page)

            title_re = self._title_pattern()
            collected: list[dict] = []
            for page_no in range(1, max_pages + 1):
                if page_no > 1:
                    pager = page.locator("#atclList_pageList").get_by_role("link", name=str(page_no), exact=True)
                    if not pager.count():
                        break
                    pager.click()
                    page.wait_for_timeout(600)
                posts = page.locator("a._atcl").evaluate_all(
                    "els => els.map(e => ({title:(e.textContent||'').trim(), id:e.dataset.atclId}))"
                )
                posts = [post for post in posts if title_re.match(post["title"])]
                for post in posts:
                    _click_past_overlays(
                        page, page.locator(f'a._atcl[data-atcl-id="{post["id"]}"]')
                    )
                    page.wait_for_timeout(650)
                    # 본문 이미지는 <article> 안이 아니라 <p> 아래에 바로
                    # 들어 있어 태그 위치 대신 첨부파일 URL 패턴으로 찾는다.
                    images = page.locator("img").evaluate_all(
                        "els => els.map(e => ({src:e.src,w:e.naturalWidth,h:e.naturalHeight}))"
                        ".filter(x => x.w > 500 && x.h > 500 && x.src.includes('/board/image/'))"
                    )
                    collected.append({
                        "id": post["id"], "title": post["title"],
                        "images": images, "page": page_no,
                    })
            browser.close()
            return collected

    def list_recent_titles(self, max_pages: int = 1) -> list[dict]:
        """게시물 본문에 들어가지 않고 제목·번호만 가볍게 읽는다.

        다음 주 식단표가 게시됐는지만 확인하면 되는 주말 폴링용으로, 이미지
        다운로드와 게시물 클릭이 없어 collect()보다 그룹웨어 부담이 적다.
        """
        if not self.settings.groupware_user or not self.settings.groupware_password:
            raise RuntimeError("GROUPWARE_USER와 GROUPWARE_PASSWORD가 필요합니다.")
        with sync_playwright() as pw:
            browser = self._launch(pw)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            self._login_and_open_board(page)

            title_re = self._title_pattern()
            collected: list[dict] = []
            for page_no in range(1, max_pages + 1):
                if page_no > 1:
                    pager = page.locator("#atclList_pageList").get_by_role("link", name=str(page_no), exact=True)
                    if not pager.count():
                        break
                    pager.click()
                    page.wait_for_timeout(600)
                posts = page.locator("a._atcl").evaluate_all(
                    "els => els.map(e => ({title:(e.textContent||'').trim(), id:e.dataset.atclId}))"
                )
                collected.extend(post for post in posts if title_re.match(post["title"]))
            browser.close()
            return collected
