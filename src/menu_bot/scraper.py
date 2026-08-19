from __future__ import annotations

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


class GroupwareScraper:
    """로그인 후 자유게시판에서 식단 게시물과 본문 이미지 URL을 읽는다."""

    def __init__(self, settings: Settings, headless: bool = True):
        self.settings = settings
        self.headless = headless

    def _login_and_open_board(self, page) -> None:
        _goto_settling(page, self.settings.groupware_url)
        if page.locator("#auth_id").count() and page.locator("#auth_pw").count():
            page.locator("#auth_id").fill(self.settings.groupware_user)
            page.locator("#auth_pw").fill(self.settings.groupware_password)
            page.locator('input[type="submit"]').click()
            host = re.escape(urlsplit(self.settings.groupware_url).netloc)
            page.wait_for_url(re.compile(rf"https?://{host}/"), timeout=30_000)
        _goto_settling(page, self.settings.groupware_url, settle_ms=1000)
        page.get_by_text("게시판", exact=True).first.click()
        page.get_by_text("자유", exact=True).first.click()
        page.locator("a._atcl").first.wait_for(timeout=30_000)

    def _title_pattern(self) -> re.Pattern:
        return re.compile(r"^\[(?:" + "|".join(map(re.escape, self.settings.post_prefixes)) + r")]")

    def collect(self, max_pages: int = 2) -> list[dict]:
        if not self.settings.groupware_user or not self.settings.groupware_password:
            raise RuntimeError("GROUPWARE_USER와 GROUPWARE_PASSWORD가 필요합니다.")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=self.headless)
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
                    page.locator(f'a._atcl[data-atcl-id="{post["id"]}"]').click()
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
            browser = pw.chromium.launch(channel="chrome", headless=self.headless)
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
