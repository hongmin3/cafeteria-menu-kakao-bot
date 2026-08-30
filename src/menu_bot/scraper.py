from __future__ import annotations

from datetime import datetime
from pathlib import Path
import platform
import re
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from .config import Settings


class ScrapeError(RuntimeError):
    """어느 단계에서 왜 막혔는지를 사람 말로 담은 크롤링 오류.

    Playwright 원문은 30초 타임아웃과 셀렉터 덤프만 남긴다. 그것이 그대로
    상태 파일과 알림 메일에 실리면, 받은 사람은 무엇이 잘못됐는지 읽어 낼 수
    없다(2026-08-29 공지 팝업 건이 그랬다). 단계 이름과 짐작되는 원인을 붙여
    메일만 보고도 다음 행동을 정할 수 있게 한다.
    """

    def __init__(self, step: str, reason: str, hint: str = ""):
        self.step = step
        self.reason = reason
        self.hint = hint
        super().__init__(f"[{step}] {reason}" + (f" — {hint}" if hint else ""))


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

# 실패한 순간의 화면·DOM을 남길 곳. data/는 저장소에 올라가지 않으므로 사내
# 게시판 내용이 밖으로 나가지 않는다.
SNAPSHOT_DIR = Path("data/diagnostics")
SNAPSHOT_KEEP = 12


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


def _describe_blockers(page) -> str:
    """지금 화면에서 진행을 막고 있을 만한 것을 한 줄로 적는다.

    실패 사유를 메일로 받았을 때 "무엇이 막았는가"가 바로 보이게 하는 것이
    목적이다. 화면을 읽다 실패하면 빈 문자열을 돌려준다 — 진단이 본 오류를
    가려서는 안 된다.
    """
    try:
        found = page.evaluate(
            """(selectors) => {
              const shown = el => getComputedStyle(el).display !== 'none'
                && el.getBoundingClientRect().width > 0;
              const layers = [...document.querySelectorAll(selectors)]
                .filter(shown)
                .map(el => (el.className || el.tagName).toString().split(' ').slice(-2).join('.'));
              return {
                layers: [...new Set(layers)].slice(0, 3),
                loginForm: !!document.querySelector('#auth_id, #auth_pw'),
                url: location.href,
              };
            }""",
            OVERLAY_SELECTORS,
        )
    except Exception:  # noqa: BLE001 - 진단 보조가 본 오류를 덮으면 안 된다
        return ""
    parts = []
    if found.get("loginForm"):
        parts.append("로그인 화면으로 돌아가 있습니다(세션 만료 또는 로그인 실패)")
    if found.get("layers"):
        parts.append(f"화면을 덮은 레이어: {', '.join(found['layers'])}")
    if found.get("url"):
        parts.append(f"현재 주소: {found['url']}")
    return " / ".join(parts)


def _save_failure_snapshot(page, label: str, directory: Path = SNAPSHOT_DIR) -> Path | None:
    """실패한 순간의 화면과 DOM을 남기고 스크린샷 경로를 돌려준다.

    2026-08-29 공지 팝업 건은 단서가 로그 한 줄(`intercepts pointer events`)뿐이라,
    무엇이 덮었는지 알아내려고 실제 그룹웨어에 다시 붙어 봐야 했다. 화면 한 장과
    HTML이 남아 있으면 그 왕복이 필요 없다.

    스냅샷을 남기다 실패해도 원래 오류를 가리지 않는다 — 이 함수는 예외를 삼킨다.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shot = directory / f"{stamp}-{label}.png"
        page.screenshot(path=str(shot), full_page=False)
        (directory / f"{stamp}-{label}.html").write_text(page.content(), encoding="utf-8")
        # 오래된 것부터 지운다. 매시 실패해도 디스크가 계속 불어나지 않게.
        for stale in sorted(directory.iterdir(), reverse=True)[SNAPSHOT_KEEP * 2:]:
            stale.unlink(missing_ok=True)
        return shot
    except Exception:  # noqa: BLE001 - 진단 보조가 본 오류를 덮으면 안 된다
        return None


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
        try:
            return pw.chromium.launch(**kwargs)
        except PlaywrightError as exc:
            raise ScrapeError(
                "브라우저 실행",
                f"Chromium을 띄우지 못했습니다: {exc}",
                "`playwright install chromium`이 필요하거나 서버 메모리가 부족할 수 있습니다.",
            ) from exc

    def _menu_link(self, page, label: str):
        """상단 메뉴 항목을 찾는다. 표시 문구가 바뀌면 title 속성으로 되짚는다.

        메뉴 이름은 그룹웨어 개편 때 바뀔 수 있는 값이라 텍스트 하나에만
        기대지 않는다. 둘 다 없으면 무엇을 못 찾았는지 분명히 말해 준다.
        """
        by_text = page.get_by_text(label, exact=True)
        if by_text.count():
            return by_text.first
        by_title = page.locator(f'[title="{label}"]')
        if by_title.count():
            return by_title.first
        raise ScrapeError(
            f"{label} 메뉴 찾기",
            f'상단 메뉴에서 "{label}"을 찾지 못했습니다.',
            f"메뉴 이름이 바뀌었을 수 있습니다. {_describe_blockers(page)}",
        )

    def _sign_in(self, page) -> None:
        """로그인 폼이 보이면 채워 넣고, 홈으로 넘어갔는지 확인한다.

        폼이 없으면 이미 로그인된 것으로 보고 넘어간다. 그 판단이 틀렸다면
        곧바로 다음 단계(게시판 열기)에서 드러난다.
        """
        if not (page.locator("#auth_id").count() and page.locator("#auth_pw").count()):
            return
        page.locator("#auth_id").fill(self.settings.groupware_user)
        page.locator("#auth_pw").fill(self.settings.groupware_password)
        submit = page.locator('input[type="submit"]')
        if submit.count():
            submit.first.click()
        else:
            # 제출 버튼 모양이 바뀌어도 로그인 자체는 되도록 엔터로 보낸다.
            page.locator("#auth_pw").press("Enter")
        host = re.escape(urlsplit(self.settings.groupware_url).netloc)
        try:
            page.wait_for_url(re.compile(rf"https?://{host}/"), timeout=30_000)
        except PlaywrightError as exc:
            still_login = bool(page.locator("#auth_id").count())
            raise ScrapeError(
                "로그인",
                "자격 증명을 넣었지만 그룹웨어 홈으로 넘어가지 않았습니다.",
                (
                    "로그인 화면에 그대로 머물러 있습니다 — 비밀번호 변경·계정 잠김·"
                    "추가 인증 화면일 수 있습니다."
                    if still_login
                    else f"{_describe_blockers(page)} / 원문: {exc}"
                ),
            ) from exc

    def _login_and_open_board(self, page) -> None:
        _goto_settling(page, self.settings.groupware_url)
        self._sign_in(page)
        _goto_settling(page, self.settings.groupware_url, settle_ms=1000)
        for label in ("게시판", "자유"):
            target = self._menu_link(page, label)
            try:
                _click_past_overlays(page, target)
            except PlaywrightError as exc:
                raise ScrapeError(
                    f"{label} 메뉴 열기",
                    f'"{label}"을 눌렀지만 화면이 넘어가지 않았습니다.',
                    _describe_blockers(page) or str(exc),
                ) from exc
        try:
            page.locator("a._atcl").first.wait_for(timeout=30_000)
        except PlaywrightError as exc:
            raise ScrapeError(
                "게시물 목록",
                "자유게시판에 들어갔지만 게시물 목록(a._atcl)이 나타나지 않았습니다.",
                _describe_blockers(page) or "게시판 화면 구조가 바뀌었을 수 있습니다.",
            ) from exc

    def _title_pattern(self) -> re.Pattern:
        return re.compile(r"^\[(?:" + "|".join(map(re.escape, self.settings.post_prefixes)) + r")]")

    def _require_credentials(self) -> None:
        if not self.settings.groupware_user or not self.settings.groupware_password:
            raise ScrapeError(
                "설정 확인",
                "GROUPWARE_USER와 GROUPWARE_PASSWORD가 필요합니다.",
                ".env에 값이 있는지 확인하세요.",
            )

    def _read_titles(self, page, page_no: int) -> list[dict]:
        """현재 목록 화면에서 제목과 게시물 번호를 읽는다."""
        return page.locator("a._atcl").evaluate_all(
            "els => els.map(e => ({title:(e.textContent||'').trim(), id:e.dataset.atclId}))"
        )

    def _go_to_page(self, page, page_no: int) -> bool:
        """목록 페이지를 넘긴다. 해당 번호가 없으면 False."""
        pager = page.locator("#atclList_pageList").get_by_role(
            "link", name=str(page_no), exact=True
        )
        if not pager.count():
            return False
        pager.click()
        page.wait_for_timeout(600)
        return True

    def collect(self, max_pages: int = 2) -> list[dict]:
        self._require_credentials()
        with sync_playwright() as pw:
            browser = self._launch(pw)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            try:
                self._login_and_open_board(page)

                title_re = self._title_pattern()
                collected: list[dict] = []
                for page_no in range(1, max_pages + 1):
                    if page_no > 1 and not self._go_to_page(page, page_no):
                        break
                    posts = [
                        post for post in self._read_titles(page, page_no)
                        if title_re.match(post["title"])
                    ]
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
                return collected
            except Exception:
                _save_failure_snapshot(page, "collect")
                raise
            finally:
                # 실패해도 반드시 닫는다. 매시 재시도가 실패할 때마다 브라우저를
                # 흘리면 서버 메모리를 갉아먹는다.
                browser.close()

    def list_recent_titles(self, max_pages: int = 1) -> list[dict]:
        """게시물 본문에 들어가지 않고 제목·번호만 가볍게 읽는다.

        다음 주 식단표가 게시됐는지만 확인하면 되는 주말 폴링용으로, 이미지
        다운로드와 게시물 클릭이 없어 collect()보다 그룹웨어 부담이 적다.
        """
        self._require_credentials()
        with sync_playwright() as pw:
            browser = self._launch(pw)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            try:
                self._login_and_open_board(page)

                title_re = self._title_pattern()
                collected: list[dict] = []
                for page_no in range(1, max_pages + 1):
                    if page_no > 1 and not self._go_to_page(page, page_no):
                        break
                    collected.extend(
                        post for post in self._read_titles(page, page_no)
                        if title_re.match(post["title"])
                    )
                return collected
            except Exception:
                _save_failure_snapshot(page, "titles")
                raise
            finally:
                browser.close()
