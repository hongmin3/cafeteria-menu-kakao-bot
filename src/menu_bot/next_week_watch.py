from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Settings
from .db import MenuDB
from .notify import (
    FAILURE_RESULTS,
    deadline_alert_mail,
    format_week_structure,
    send_mail,
    stuck_alert_mail,
    success_mail,
)
from .parser import post_from_title
from .pipeline import process_manifest
from .query import PRIMARY_LOCATION, _choose_common_menu
from .scraper import GroupwareScraper


# 상태 파일에 남길 시도 기록 개수 상한. 주말 폴링은 2시간 간격이라 한 주에
# 20회 남짓이지만, 실패가 이어질 때 파일이 무한히 커지지 않게 잘라 둔다.
MAX_ATTEMPTS = 40

# 몇 번 연속으로 실패하면 마감(일요일 22시)을 기다리지 않고 알릴지. 폴링이
# 매시로 바뀌었으니 3회면 세 시간이다 — 일시적인 접속 실패로 사람을 깨우지는
# 않으면서, 화면 구조가 바뀌어 계속 막히는 상황은 그날 안에 드러난다.
# 2026-08-29 공지 팝업 건은 첫 실패에서 마감 알림까지 44시간이 걸렸다.
STUCK_ALERT_AFTER = 3


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
    # 챗봇이 그 주차에 답할 수 있는가. 확보 판정(confirmed)은 이 값과 같은
    # 기준으로 한다 — 저장된 행이 있는지가 아니라 응답을 만들 수 있는지로
    # 봐야 알림과 실제 답이 어긋나지 않는다.
    servable: bool = False
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


def _failure_streak(state: dict) -> int:
    """마지막 성공(또는 '아직 게시 안 됨') 이후 연속 실패 횟수."""
    streak = 0
    for attempt in reversed(state.get("attempts") or []):
        if attempt.get("result") in FAILURE_RESULTS:
            streak += 1
        else:
            break
    return streak


def _alert_if_stuck(
    settings: Settings, target: date, state: dict, checked_at: str, send, progress
) -> bool:
    """연속 실패가 임계치에 닿으면 그 자리에서 경보를 보낸다(주차당 한 번).

    게시글이 아직 안 올라온 것(not_posted)은 실패로 세지 않는다. 그건 정상이고,
    금요일 저녁에 매시 확인하면 대부분 몇 번은 그렇게 나온다.
    """
    streak = _failure_streak(state)
    if streak < STUCK_ALERT_AFTER or state.get("stuck_alert_sent_week") == target.isoformat():
        return False
    subject, body = stuck_alert_mail(target, checked_at, state, streak)
    if not send(subject, body, progress=progress):
        return False
    state["stuck_alert_sent_week"] = target.isoformat()
    _save_state(settings.next_week_state_path, state)
    return True


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

    return _collect_week(
        settings, target, current, state, checked_at,
        scraper=scraper, image_dir=image_dir, progress=progress, process=process, send=send,
    )


def _collect_week(
    settings: Settings,
    target: date,
    current: datetime,
    state: dict,
    checked_at: str,
    scraper=None,
    image_dir: Path = Path("data/images"),
    progress=print,
    process=process_manifest,
    send=send_mail,
) -> NextWeekWatchResult:
    """대상 주차 게시글을 찾아 수집·OCR·저장하고, 확보되면 알림을 보낸다.

    주말 폴링(check_next_week_posted)과 시간별 재시도(ensure_week_menu)가
    같은 본문을 쓴다. 둘의 차이는 "어느 주차를 노리는가"와 "이미 확보됐는지
    어떻게 판단하는가"뿐이다.
    """
    scraper = scraper or GroupwareScraper(settings, headless=True)
    try:
        # 제목만 가볍게 먼저 확인한다. collect()는 본문 이미지를 실제로 렌더링해
        # 다운로드하므로, 아직 게시되지 않았을 때 2시간마다 큰 이미지를 헛되이
        # 내려받지 않기 위함이다.
        titles = scraper.list_recent_titles(max_pages=1)
        target_ids = [post["id"] for post in titles if _matches_target(post, target)]

        if not target_ids:
            unreadable = _unreadable_titles(titles)
            if unreadable:
                reason = (
                    "식단표 게시글로 보이는데 제목에서 주차를 읽지 못했습니다: "
                    + " | ".join(unreadable[:3])
                )
                _record_attempt(state, current, "title_unreadable", reason)
                _save_state(settings.next_week_state_path, state)
                _alert_if_stuck(settings, target, state, checked_at, send, progress)
                progress(reason)
                return NextWeekWatchResult(
                    target_week_start=target,
                    already_confirmed=False,
                    found=False,
                    message=f"{target.isoformat()} 주차 — {reason}",
                    error=reason,
                )
            _record_attempt(state, current, "not_posted")
            _save_state(settings.next_week_state_path, state)
            return NextWeekWatchResult(
                target_week_start=target,
                already_confirmed=False,
                found=False,
                message=f"{target.isoformat()} 주차 게시글이 아직 없습니다. 다음 예정 시각에 다시 확인합니다.",
            )

        # 이미 처리한 게시글뿐이고 답도 나가고 있으면 이미지를 다시 내려받지
        # 않는다. 상태 파일이 초기화된 뒤 재확인할 때 같은 이미지를 다시
        # OCR하는 낭비를 막는다.
        known = set(state.get("ingested_post_ids") or [])
        if not set(target_ids) - known and _db_can_serve_week(settings, target):
            sites = _week_locations(settings, target)
            return NextWeekWatchResult(
                target_week_start=target,
                already_confirmed=False,
                found=True,
                servable=True,
                message=(
                    f"{target.isoformat()} 주차에 새로 올라온 게시글이 없습니다. "
                    f"현재 {'·'.join(sites)} 식단으로 답하는 중입니다."
                ),
            )

        # 새 게시글이 있으므로 이미지 URL까지 수집해 저장한다.
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
        _alert_if_stuck(settings, target, state, checked_at, send, progress)
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
        _alert_if_stuck(settings, target, state, checked_at, send, progress)
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

    # 저장은 됐지만 챗봇이 답할 수 없는 경우(예: 뷰웍스 게시글 없이 다른
    # 사업장 것만 올라옴). 확보로 처리하면 폴링이 멈춰 정작 뷰웍스 식단이
    # 올라와도 아무도 가져오지 않는다.
    if not _db_can_serve_week(settings, target):
        locations = _week_locations(settings, target)
        reason = (
            f"저장은 됐지만 공통 식단을 고를 수 없습니다(사업장: {', '.join(locations) or '없음'})."
        )
        _record_attempt(state, current, "not_servable", reason)
        _save_state(settings.next_week_state_path, state)
        _alert_if_stuck(settings, target, state, checked_at, send, progress)
        message = f"{target.isoformat()} 주차 — {reason} 확보로 처리하지 않고 다시 시도합니다."
        progress(message)
        return NextWeekWatchResult(
            target_week_start=target,
            already_confirmed=False,
            found=True,
            message=message,
            stats=stats,
            error=reason,
        )

    locations = _week_locations(settings, target)
    # 사업장별로 나뉘어 올라온 주차인가. 그 자체가 "그 주에 운영 예외가 있다"는
    # 신호라 알림에 적어 준다.
    split_by_site = PRIMARY_LOCATION not in locations and len(locations) > 1
    state["ingested_post_ids"] = sorted(set(state.get("ingested_post_ids") or []) | set(target_ids))
    state["confirmed_week_start"] = target.isoformat()
    state["confirmed_at"] = current.isoformat(timespec="seconds")
    _record_attempt(state, current, "confirmed")
    _save_state(settings.next_week_state_path, state)

    notified = False
    if state.get("success_notified_week") != target.isoformat():
        subject, body = success_mail(
            target, checked_at, stats, structure,
            locations=locations, split_by_site=split_by_site,
        )
        notified = send(subject, body, progress=progress)
        if notified:
            state["success_notified_week"] = target.isoformat()
            _save_state(settings.next_week_state_path, state)

    message = (
        f"{target.isoformat()} 주차 게시글을 확인하고 수집·저장했습니다"
        f"({'·'.join(locations)}). 월요일 00시부터 바로 조회할 수 있고, 남은 폴링은 건너뜁니다."
    )
    progress(message)
    return NextWeekWatchResult(
        target_week_start=target,
        already_confirmed=False,
        found=True,
        confirmed=True,
        servable=True,
        message=message,
        stats=stats,
        notified=notified,
    )


def _week_for(today: date) -> date:
    """지금 채워져 있어야 하는 주차의 월요일.

    토·일에는 다가오는 월요일(=다음 주), 월~금에는 그 주 월요일이다. 덕분에
    일요일 밤 23시와 월요일 새벽 1시가 **같은 주차**를 가리켜, 자정을 넘겨도
    재시도가 엉뚱한 주차로 넘어가지 않는다.
    """
    if today.weekday() >= 5:
        return next_monday(today)
    return today - timedelta(days=today.weekday())


def _db_can_serve_week(settings: Settings, week_start: date) -> bool:
    """그 주차를 **챗봇이 실제로 답할 수 있는지**.

    단순히 행이 있는지로 판단하면 안 된다. 2026-08-24 주차에 [화성]과 [안양]
    게시글만 올라오고 [뷰웍스] 게시글이 없었던 적이 있는데, 그때 113건이
    저장돼 "수집 완료" 메일까지 나갔지만 챗봇은 공통 식단을 못 골라
    "확인할 수 없어요"로 답했다. 알림과 실제 응답이 어긋나면 안 되므로
    응답을 만들 때 쓰는 바로 그 기준(_choose_common_menu)으로 판단한다.
    """
    db = MenuDB(settings.database_path)
    try:
        return any(
            _choose_common_menu(db.query(week_start + timedelta(days=offset)))
            for offset in range(5)
        )
    finally:
        db.close()


def _week_locations(settings: Settings, week_start: date) -> list[str]:
    """그 주차에 저장된 사업장 목록(알림 본문에서 사정을 설명하는 데 쓴다)."""
    db = MenuDB(settings.database_path)
    try:
        found: set[str] = set()
        for offset in range(5):
            found.update(row["location"] for row in db.query(week_start + timedelta(days=offset)))
        return sorted(found)
    finally:
        db.close()


def ensure_week_menu(
    settings: Settings,
    now: datetime | None = None,
    scraper: GroupwareScraper | None = None,
    image_dir: Path = Path("data/images"),
    progress=print,
    process=process_manifest,
    send=send_mail,
) -> NextWeekWatchResult:
    """지금 필요한 주차의 식단이 DB에 없으면 다시 수집한다(1시간 간격 재시도용).

    일요일 22시 마감까지 식단표를 못 받았을 때 손을 놓지 않기 위한 장치다.
    확보 여부는 상태 파일이 아니라 **DB에 그 주차 메뉴가 있는지**로 판단한다.
    월요일 아침 정기 수집이 상태 파일을 건드리지 않고 DB를 채우는 경우가
    있어서, 상태 파일만 보면 이미 들어온 주차를 계속 다시 긁게 된다.

    DB에 이미 있으면 그룹웨어에 접속하지 않고 즉시 끝난다. 그래서 이 작업을
    한 시간마다 걸어 둬도 평소에는 사실상 아무 일도 하지 않는다.
    """
    current = now or datetime.now(ZoneInfo(settings.timezone))
    target = _week_for(current.date())
    state = _state_for_target(settings.next_week_state_path, target)
    checked_at = f"{current:%Y-%m-%d %H:%M} ({settings.timezone})"

    if _db_can_serve_week(settings, target):
        # 답할 수 있으면 그 주는 끝났다. [뷰웍스] 한 건이든 [안양]·[화성]
        # 두 건이든 마찬가지다 — 식당은 두 사업장 메뉴가 같을 때 통합으로
        # 올리고 운영 예외가 있는 주에만 나눠 올리므로, 사업장 게시글이
        # 올라왔다면 그것이 그 주 식단표다. 여기서 루프가 멈춘다
        # (그룹웨어에 접속하지 않고 즉시 끝난다).
        if state.get("confirmed_week_start") != target.isoformat():
            state["confirmed_week_start"] = target.isoformat()
            state["confirmed_at"] = current.isoformat(timespec="seconds")
            _save_state(settings.next_week_state_path, state)
        return NextWeekWatchResult(
            target_week_start=target,
            already_confirmed=True,
            found=True,
            confirmed=True,
            servable=True,
            message=f"{target.isoformat()} 주차 식단이 이미 저장돼 있어 재시도를 건너뜁니다.",
        )

    progress(f"{target.isoformat()} 주차 식단을 아직 답할 수 없어 다시 수집을 시도합니다.")
    result = _collect_week(
        settings, target, current, state, checked_at,
        scraper=scraper, image_dir=image_dir, progress=progress, process=process, send=send,
    )

    # 이미 그 주가 시작된 뒤(월~금)인데도 답할 수 없으면 사람이 알아야 한다.
    # 일요일 22시 마감 점검이 지나간 뒤에 사정이 드러나는 경우(예: 다른
    # 사업장 게시글만 올라와 확보로 잘못 처리됐던 주차)를 위한 안전망이라,
    # 주차당 한 번만 보낸다.
    if not result.servable and current.date().weekday() < 5:
        state = _state_for_target(settings.next_week_state_path, target)
        if state.get("deadline_alert_sent_week") != target.isoformat():
            subject, body = deadline_alert_mail(target, checked_at, state)
            if send(subject, body, progress=progress):
                state["deadline_alert_sent_week"] = target.isoformat()
                _save_state(settings.next_week_state_path, state)

    return result


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


def _unreadable_titles(titles: list[dict]) -> list[str]:
    """접두어는 맞는데 제목에서 날짜를 읽어 내지 못한 게시글들.

    제목 형식이 바뀌면(예: `[뷰웍스] 8/31 ~ 9/4`처럼 연도가 빠지면)
    post_from_title이 ValueError를 내고, 그 게시글은 없는 것처럼 취급된다.
    식단표가 눈앞에 올라와 있는데도 "아직 게시되지 않음"으로 넘어가는 것이
    가장 나쁜 실패다 — 아무도 이상하다고 느끼지 못한 채 그 주를 놓친다.
    따로 세어 실패로 기록하고 알림까지 잇는다.
    """
    unreadable: list[str] = []
    for post in titles:
        try:
            post_from_title(post["id"], post["title"], [])
        except ValueError:
            unreadable.append(post["title"])
    return unreadable


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
