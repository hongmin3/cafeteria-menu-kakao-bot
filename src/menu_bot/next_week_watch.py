from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Settings
from .db import MenuDB
from .notify import (
    deadline_alert_mail,
    format_week_structure,
    send_mail,
    success_mail,
)
from .parser import post_from_title
from .pipeline import process_manifest
from .scraper import GroupwareScraper


# 상태 파일에 남길 시도 기록 개수 상한. 주말 폴링은 2시간 간격이라 한 주에
# 20회 남짓이지만, 실패가 이어질 때 파일이 무한히 커지지 않게 잘라 둔다.
MAX_ATTEMPTS = 40


@dataclass(frozen=True)
class NextWeekWatchResult:
    target_week_start: date
    already_confirmed: bool
    found: bool
    message: str
    stats: dict | None = None
    # 게시글 존재(found)와 실제 확보(confirmed)를 분리한다. 게시글만 올라오고
    # 이미지가 없거나 OCR 결과가 0건이면 확보한 것이 아니므로 폴링을 계속해야 한다.
    confirmed: bool = False
    error: str | None = None
    notified: bool = False


@dataclass(frozen=True)
class DeadlineCheckResult:
    target_week_start: date
    confirmed: bool
    alerted: bool
    already_alerted: bool
    message: str


def next_monday(today: date) -> date:
    return today - timedelta(days=today.weekday()) + timedelta(days=7)


def _load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # 상태 파일이 깨졌다고 수집을 못 하게 만들 이유는 없다. 새로 시작한다.
            return {}
    return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def _state_for_target(path: Path, target: date) -> dict:
    """대상 주차가 바뀌면 지난 주 시도 기록을 버리고 새로 시작한다."""
    state = _load_state(path)
    if state.get("target_week_start") != target.isoformat():
        previous = state.get("confirmed_week_start")
        state = {"target_week_start": target.isoformat(), "attempts": []}
        if previous:
            # 지난 주차 확인 이력은 남겨 둔다(주차가 다르면 어차피 재확인한다).
            state["previous_confirmed_week_start"] = previous
    state.setdefault("attempts", [])
    return state


def _record_attempt(state: dict, when: datetime, result: str, error: str | None = None) -> None:
    attempts = state.setdefault("attempts", [])
    entry: dict = {"at": when.isoformat(timespec="seconds"), "result": result}
    if error:
        entry["error"] = error[:500]
    attempts.append(entry)
    del attempts[:-MAX_ATTEMPTS]


def check_next_week_posted(
    settings: Settings,
    now: datetime | None = None,
    scraper: GroupwareScraper | None = None,
    image_dir: Path = Path("data/images"),
    progress=print,
    process=process_manifest,
    send=send_mail,
) -> NextWeekWatchResult:
    """다음 주 식단표 게시글을 확인하고, 발견되는 즉시 수집·OCR·저장까지 끝낸다.

    - 이번 주말에 이미 확보된 주차면 그룹웨어에 접속하지 않고 즉시 반환한다.
      상태는 대상 주차(다음 주 월요일) 단위로 저장되므로 매주 자동으로 다시
      확인한다(수동 초기화 불필요).
    - 아직 확보되지 않았다면 게시글 목록의 제목만 읽어 대상 주차 게시글이
      있는지 본다. 없으면 시도 기록만 남기고 다음 예정 시각을 기다린다.
    - 있으면 그 자리에서 이미지 다운로드·OCR·파싱까지 수행해 다음 주
      week_start로 저장한다. 그 결과 월요일 00시가 되는 순간부터 카카오봇이
      별도 배치 없이 바로 응답할 수 있다. 월요일 08:00 정기 수집은 안전망으로
      유지하며, 이미 저장된 게시물을 다시 처리해도 같은 source_post_id로
      덮어써 안전하다.
    - **저장된 메뉴 항목이 1개 이상일 때만 확보(confirmed)로 본다.** 게시글
      제목만 올라오고 이미지가 아직 없거나 OCR이 아무것도 못 읽은 경우를
      성공으로 처리하면 폴링이 멈춰 버려 그 주 식단을 통째로 놓친다.
    - 확보되면 알림 메일을 한 번 보낸다(같은 주차에 중복 발송하지 않는다).
      그룹웨어 접속 자체가 실패한 경우도 사유를 상태 파일에 남겨, 일요일
      22시 마감 점검이 "무엇이 몇 번 실패했는지"를 메일로 알릴 수 있게 한다.
    """
    current = now or datetime.now(ZoneInfo(settings.timezone))
    target = next_monday(current.date())
    state = _state_for_target(settings.next_week_state_path, target)
    checked_at = f"{current:%Y-%m-%d %H:%M} ({settings.timezone})"

    if state.get("confirmed_week_start") == target.isoformat():
        return NextWeekWatchResult(
            target_week_start=target,
            already_confirmed=True,
            found=True,
            confirmed=True,
            message=f"{target.isoformat()} 주차 게시글은 이미 확인·저장되어 이번 주말 폴링을 건너뜁니다.",
        )

    scraper = scraper or GroupwareScraper(settings, headless=True)
    try:
        # 제목만 가볍게 먼저 확인한다. collect()는 본문 이미지를 실제로 렌더링해
        # 다운로드하므로, 아직 게시되지 않았을 때 2시간마다 큰 이미지를 헛되이
        # 내려받지 않기 위함이다.
        titles = scraper.list_recent_titles(max_pages=1)
        target_exists = any(_matches_target(post, target) for post in titles)

        if not target_exists:
            _record_attempt(state, current, "not_posted")
            _save_state(settings.next_week_state_path, state)
            return NextWeekWatchResult(
                target_week_start=target,
                already_confirmed=False,
                found=False,
                message=f"{target.isoformat()} 주차 게시글이 아직 없습니다. 다음 예정 시각에 다시 확인합니다.",
            )

        # 실제로 존재하므로 이미지 URL까지 수집해 바로 저장한다.
        matched_rows = [post for post in scraper.collect(max_pages=1) if _matches_target(post, target)]
        db = MenuDB(settings.database_path)
        try:
            stats = process(matched_rows, db, image_dir, progress=progress, week_start=target)
            structure = format_week_structure(db, target) if stats.get("entries") else ""
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - 실패 사유를 남기는 것이 이 함수의 목적 중 하나
        _record_attempt(state, current, "error", f"{type(exc).__name__}: {exc}")
        _save_state(settings.next_week_state_path, state)
        message = f"{target.isoformat()} 주차 확인 중 오류가 났습니다: {type(exc).__name__}: {exc}"
        progress(message)
        return NextWeekWatchResult(
            target_week_start=target,
            already_confirmed=False,
            found=False,
            message=message,
            error=f"{type(exc).__name__}: {exc}",
        )

    if not stats.get("entries"):
        _record_attempt(state, current, "ingest_failed", _ingest_error(stats))
        _save_state(settings.next_week_state_path, state)
        message = (
            f"{target.isoformat()} 주차 게시글은 있지만 저장된 메뉴가 0건입니다. "
            "확보로 처리하지 않고 다음 예정 시각에 다시 시도합니다."
        )
        progress(message)
        return NextWeekWatchResult(
            target_week_start=target,
            already_confirmed=False,
            found=True,
            message=message,
            stats=stats,
            error=_ingest_error(stats),
        )

    state["confirmed_week_start"] = target.isoformat()
    state["confirmed_at"] = current.isoformat(timespec="seconds")
    _record_attempt(state, current, "confirmed")
    _save_state(settings.next_week_state_path, state)

    notified = False
    if state.get("success_notified_week") != target.isoformat():
        subject, body = success_mail(target, checked_at, stats, structure)
        notified = send(subject, body, progress=progress)
        if notified:
            state["success_notified_week"] = target.isoformat()
            _save_state(settings.next_week_state_path, state)

    return NextWeekWatchResult(
        target_week_start=target,
        already_confirmed=False,
        found=True,
        confirmed=True,
        message=(
            f"{target.isoformat()} 주차 게시글을 확인하고 미리 수집·저장했습니다. "
            "월요일 00시부터 바로 조회할 수 있고, 이번 주말 남은 폴링은 건너뜁니다."
        ),
        stats=stats,
        notified=notified,
    )


def check_next_week_deadline(
    settings: Settings,
    now: datetime | None = None,
    progress=print,
    send=send_mail,
) -> DeadlineCheckResult:
    """주말 폴링 마감 시점(일요일 22시)에 다음 주 식단 확보 여부를 판정한다.

    확보돼 있으면 아무것도 하지 않는다. 확보되지 않았으면 그동안 무엇이 몇 번
    실패했는지를 정리해 알림 메일을 보낸다. 같은 주차에 두 번 보내지 않도록
    상태 파일에 발송 여부를 남긴다(메일 발송이 실패하면 기록하지 않으므로
    다음 실행에서 다시 시도한다).

    이 함수는 시간을 직접 판단하지 않는다. "언제가 마감인지"는 systemd
    타이머(menubot-nextweek-deadline.timer)가 정하고, 여기서는 호출된 시점에
    확보됐는지만 본다. 그래야 마감 시각을 바꿀 때 코드를 건드리지 않는다.
    """
    current = now or datetime.now(ZoneInfo(settings.timezone))
    target = next_monday(current.date())
    state = _state_for_target(settings.next_week_state_path, target)
    checked_at = f"{current:%Y-%m-%d %H:%M} ({settings.timezone})"

    if state.get("confirmed_week_start") == target.isoformat():
        return DeadlineCheckResult(
            target_week_start=target,
            confirmed=True,
            alerted=False,
            already_alerted=False,
            message=f"{target.isoformat()} 주차 식단은 확보돼 있습니다. 마감 알림을 보내지 않습니다.",
        )

    if state.get("deadline_alert_sent_week") == target.isoformat():
        return DeadlineCheckResult(
            target_week_start=target,
            confirmed=False,
            alerted=False,
            already_alerted=True,
            message=f"{target.isoformat()} 주차 미확보 알림은 이미 보냈습니다.",
        )

    subject, body = deadline_alert_mail(target, checked_at, state)
    alerted = send(subject, body, progress=progress)
    if alerted:
        state["deadline_alert_sent_week"] = target.isoformat()
    _save_state(settings.next_week_state_path, state)
    return DeadlineCheckResult(
        target_week_start=target,
        confirmed=False,
        alerted=alerted,
        already_alerted=False,
        message=(
            f"{target.isoformat()} 주차 식단 미확보 — 알림 메일을 보냈습니다."
            if alerted
            else f"{target.isoformat()} 주차 식단 미확보 — 알림 메일 발송에 실패했습니다."
        ),
    )


def _matches_target(post: dict, target: date) -> bool:
    try:
        parsed = post_from_title(post["id"], post["title"], [])
    except ValueError:
        return False
    return parsed.start_date == target


def _ingest_error(stats: dict) -> str:
    if stats.get("errors"):
        return f"process_manifest 오류: {stats['errors']}"
    return (
        f"이미지 {stats.get('images', 0)}장 중 식단표로 인식된 것이 없어 "
        f"메뉴 항목 0건(제외 {stats.get('skipped_images', 0)}장)"
    )
