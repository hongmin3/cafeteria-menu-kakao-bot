from __future__ import annotations

import re
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from .config import Settings


class GroupwareScraper:
    """로그인 후 자유게시판에서 식단 게시물과 본문 이미지 URL을 읽는다."""

    def __init__(self, settings: Settings, headless: bool = True):
        self.settings = settings
        self.headless = headless

    def collect(self, max_pages: int = 2) -> list[dict]:
        if not self.settings.groupware_user or not self.settings.groupware_password:
            raise RuntimeError("GROUPWARE_USER와 GROUPWARE_PASSWORD가 필요합니다.")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=self.headless)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.goto(self.settings.groupware_url, wait_until="domcontentloaded")
            if page.locator("#auth_id").count() and page.locator("#auth_pw").count():
                page.locator("#auth_id").fill(self.settings.groupware_user)
                page.locator("#auth_pw").fill(self.settings.groupware_password)
                page.locator('input[type="submit"]').click()
                host = re.escape(urlsplit(self.settings.groupware_url).netloc)
                page.wait_for_url(re.compile(rf"https?://{host}/"), timeout=30_000)
            page.goto(self.settings.groupware_url, wait_until="domcontentloaded")
            page.get_by_text("게시판", exact=True).first.click()
            page.get_by_text("자유", exact=True).first.click()
            page.locator("a._atcl").first.wait_for(timeout=30_000)

            title_re = re.compile(r"^\[(?:" + "|".join(map(re.escape, self.settings.post_prefixes)) + r")]" )
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
                    images = page.locator("article img").evaluate_all(
                        "els => els.map(e => ({src:e.src,w:e.naturalWidth,h:e.naturalHeight}))"
                        ".filter(x => x.w > 500 && x.h > 500)"
                    )
                    collected.append({
                        "id": post["id"], "title": post["title"],
                        "images": images, "page": page_no,
                    })
            browser.close()
            return collected
