from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Settings
from .db import MenuDB
from .parser import post_from_title
from .pipeline import process_manifest
from .scraper import GroupwareScraper


@dataclass(frozen=True)
class NextWeekWatchResult:
    target_week_start: date
    already_confirmed: bool
    found: bool
    message: str
    stats: dict | None = None


def next_monday(today: date) -> date:
    return today - timedelta(days=today.weekday()) + timedelta(days=7)


def _load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def check_next_week_posted(
    settings: Settings,
    now: datetime | None = None,
    scraper: GroupwareScraper | None = None,
    image_dir: Path = Path("data/images"),
    progress=print,
) -> NextWeekWatchResult:
    """다음 주 식단표 게시글을 확인하고, 발견되는 즉시 수집·OCR·저장까지 끝낸다.

    - 이번 주말(금 22시~일요일)에 이미 확인된 적이 있으면 그룹웨어에 접속하지
      않고 즉시 반환한다. 상태는 대상 주차(다음 주 월요일 날짜) 단위로
      저장되므로 매주 자동으로 새로 확인된다(수동 초기화 불필요).
    - 아직 확인되지 않았다면 게시글 목록을 읽어 대상 주차 게시글이 있는지
      본다. 없으면 다음 예정 시각에 다시 확인하도록 그대로 반환한다.
    - 있으면 그 자리에서 이미지 다운로드·OCR·파싱까지 수행해 다음 주
      week_start로 저장한다. 그 결과 월요일 00시가 되는 순간부터(달력이
      해당 주로 넘어가는 즉시) 카카오봇이 별도 배치 없이 바로 응답할 수
      있다. 월요일 08:00 운영 수집은 안전망으로 그대로 유지하며, 이미
      저장된 게시물을 다시 처리해도 같은 source_post_id로 덮어써 안전하다.
    """
    current = now or datetime.now(ZoneInfo(settings.timezone))
    target = next_monday(current.date())
    state = _load_state(settings.next_week_state_path)
    if state.get("confirmed_week_start") == target.isoformat():
        return NextWeekWatchResult(
            target_week_start=target,
            already_confirmed=True,
            found=True,
            message=f"{target.isoformat()} 주차 게시글은 이미 확인·저장되어 이번 주말 폴링을 건너뜁니다.",
        )

    scraper = scraper or GroupwareScraper(settings, headless=True)
    # 제목만 가볍게 먼저 확인한다(collect()는 본문 이미지를 실제로 렌더링해
    # 다운로드하므로, 아직 게시되지 않았을 때 매 2시간마다 큰 이미지를 헛되이
    # 내려받지 않기 위함).
    titles = scraper.list_recent_titles(max_pages=1)
    target_exists = False
    for post in titles:
        try:
            parsed = post_from_title(post["id"], post["title"], [])
        except ValueError:
            continue
        if parsed.start_date == target:
            target_exists = True
            break

    if not target_exists:
        return NextWeekWatchResult(
            target_week_start=target,
            already_confirmed=False,
            found=False,
            message=f"{target.isoformat()} 주차 게시글이 아직 없습니다. 다음 예정 시각에 다시 확인합니다.",
        )

    # 이제부터는 실제로 존재하므로 이미지 URL까지 수집해 바로 저장한다.
    posts = scraper.collect(max_pages=1)
    matched_rows = []
    for post in posts:
        try:
            parsed = post_from_title(post["id"], post["title"], [])
        except ValueError:
            continue
        if parsed.start_date == target:
            matched_rows.append(post)

    db = MenuDB(settings.database_path)
    try:
        stats = process_manifest(matched_rows, db, image_dir, progress=progress, week_start=target)
    finally:
        db.close()

    state["confirmed_week_start"] = target.isoformat()
    _save_state(settings.next_week_state_path, state)
    return NextWeekWatchResult(
        target_week_start=target,
        already_confirmed=False,
        found=True,
        message=(
            f"{target.isoformat()} 주차 게시글을 확인하고 미리 수집·저장했습니다. "
            "월요일 00시부터 바로 조회할 수 있고, 이번 주말 남은 폴링은 건너뜁니다."
        ),
        stats=stats,
    )
