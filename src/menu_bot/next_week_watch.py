from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from .atomic import write_bytes
from .config import Settings
from .db import MenuDB
from .notify import (
    ATTEMPT_LABELS,
    FAILURE_RESULTS,
    MEAL_ORDER,
    deadline_alert_mail,
    format_week_structure,
    send_mail,
    stuck_alert_mail,
    success_mail,
)
from .parser import post_from_title
from .pipeline import process_manifest
from .query import PRIMARY_LOCATION, _choose_common_menu, _dedupe_posts
from .scraper import GroupwareScraper


MAX_ATTEMPTS = 40
STUCK_ALERT_AFTER = 3
MAX_TITLE_PAGES = 3
MAX_PRECEDING_POSTS = 3
WEEKDAYS = 5


@dataclass(frozen=True)
class NextWeekWatchResult:
    target_week_start: date
    already_confirmed: bool
    found: bool
    message: str
    stats: dict | None = None
    confirmed: bool = False
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


def _valid_snapshot(state) -> bool:
    if not isinstance(state, dict):
        return False
    attempts = state.get("attempts", [])
    if not isinstance(attempts, list) or not all(
        isinstance(attempt, dict)
        and isinstance(attempt.get("result"), str)
        and isinstance(attempt.get("at"), str)
        and isinstance(attempt.get("error", ""), str)
        for attempt in attempts
    ):
        return False
    return all(
        isinstance(state[key], str)
        for key in (
            "target_week_start", "confirmed_week_start", "confirmed_at",
            "success_notified_week", "stuck_alert_sent_week", "deadline_alert_sent_week",
        )
        if key in state
    )


def _load_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not _valid_snapshot(state):
        return {}
    previous = state.pop("previous_week", None)
    if _valid_snapshot(previous):
        previous.pop("previous_week", None)
        state["previous_week"] = previous
    return state


def _save_state(path: Path, state: dict, progress=print) -> bool:
    try:
        write_bytes(path, json.dumps(state, ensure_ascii=False, indent=1).encode("utf-8"))
    except OSError as exc:
        progress(f"식단 확인 상태 저장 실패 ({type(exc).__name__})")
        return False
    return True


def _state_for_target(path: Path, target: date) -> dict:
    """현재 주와 다음 주 점검이 번갈아 실행돼도 각 주의 시도 기록을 남긴다."""
    state = _load_state(path)
    if state.get("target_week_start") == target.isoformat():
        state.setdefault("attempts", [])
        return state
    previous = state.pop("previous_week", {})
    if previous.get("target_week_start") == target.isoformat():
        result = previous
        result.setdefault("attempts", [])
    else:
        result = {"target_week_start": target.isoformat(), "attempts": []}
    if state.get("target_week_start"):
        result["previous_week"] = state
    return result


def latest_week_attempt(path: Path, week_start: date) -> str | None:
    attempts = _state_for_target(path, week_start)["attempts"]
    if not attempts:
        return None
    result = attempts[-1]["result"]
    return result if result in ATTEMPT_LABELS else None


def week_coverage(db: MenuDB, week_start: date) -> dict:
    """사용자에게 답할 수 있는 평일 아침·점심·저녁 칸 수를 센다."""
    covered = 0
    for offset in range(WEEKDAYS):
        day = week_start + timedelta(days=offset)
        rows = _dedupe_posts(db.query(day))
        for meal in MEAL_ORDER:
            selected = _choose_common_menu([row for row in rows if row["meal_type"] == meal])
            if any(
                row["menu_text"].strip()
                and (row["status"] in {"normal", "special"} or (
                    row["status"] == "no_service" and row["category"] == "안내"
                ))
                for row in selected
            ):
                covered += 1
    return _coverage_summary(week_start, covered)


def _coverage_summary(week_start: date, covered: int) -> dict:
    expected = WEEKDAYS * len(MEAL_ORDER)
    status = "complete" if covered == expected else "partial" if covered else "empty"
    return {"week_start": week_start.isoformat(), "covered": covered, "expected": expected, "status": status}


def _stored_week_coverage(settings: Settings, week_start: date) -> dict:
    try:
        settings.database_path.stat()
    except FileNotFoundError:
        return _coverage_summary(week_start, 0)
    with closing(MenuDB(settings.database_path, read_only=True)) as db:
        return week_coverage(db, week_start)


def _failure_streak(state: dict) -> int:
    streak = 0
    for attempt in reversed(state["attempts"]):
        if attempt["result"] not in FAILURE_RESULTS:
            break
        streak += 1
    return streak


def _send_notice(send, subject: str, body: str, progress) -> bool:
    try:
        return send(subject, body, progress=progress)
    except Exception as exc:
        progress(f"식단 알림 발송 실패 ({type(exc).__name__})")
        return False


def _alert_if_stuck(
    settings: Settings, target: date, state: dict, checked_at: str, send, progress,
) -> None:
    streak = _failure_streak(state)
    if streak < STUCK_ALERT_AFTER or state.get("stuck_alert_sent_week") == target.isoformat():
        return
    subject, body = stuck_alert_mail(target, checked_at, state, streak)
    if _send_notice(send, subject, body, progress):
        state["stuck_alert_sent_week"] = target.isoformat()
        _save_state(settings.next_week_state_path, state, progress)


def _record_attempt(state: dict, when: datetime, result: str, error: str | None = None) -> None:
    attempts = state["attempts"]
    entry = {"at": when.isoformat(timespec="seconds"), "result": result}
    if error:
        entry["error"] = error[:500]
    attempts.append(entry)
    del attempts[:-MAX_ATTEMPTS]


def _remember_attempt(settings, target, current, state, status, error, send, progress) -> None:
    _record_attempt(state, current, status, error)
    if _save_state(settings.next_week_state_path, state, progress) and status in FAILURE_RESULTS:
        _alert_if_stuck(settings, target, state, _checked_at(settings, current), send, progress)


def _checked_at(settings: Settings, current: datetime) -> str:
    return f"{current:%Y-%m-%d %H:%M} ({settings.timezone})"


def _local_now(settings: Settings, now: datetime | None) -> datetime:
    zone = ZoneInfo(settings.timezone)
    if now is None:
        return datetime.now(zone)
    if now.tzinfo is None:
        return now.replace(tzinfo=zone)
    return now.astimezone(zone)


def _mark_confirmed(state: dict, target: date, current: datetime) -> None:
    state["confirmed_week_start"] = target.isoformat()
    state["confirmed_at"] = current.isoformat(timespec="seconds")


def _attempt_result(target, coverage, found, message, stats=None, error=None) -> NextWeekWatchResult:
    # 수정본을 가져오지 못해도 이미 DB에 있는 식단의 제공 가능 상태는 유지한다.
    return NextWeekWatchResult(
        target, False, found, message, stats=stats,
        confirmed=coverage["status"] == "complete", servable=bool(coverage["covered"]), error=error,
    )


def check_next_week_posted(
    settings: Settings,
    now: datetime | None = None,
    scraper: GroupwareScraper | None = None,
    image_dir: Path = Path("data/images"),
    progress=print,
    process=process_manifest,
    send=send_mail,
) -> NextWeekWatchResult:
    """다음 주 식단을 미리 받아 두고 평일 세 끼의 확보 상태를 확인한다."""
    current = _local_now(settings, now)
    target = next_monday(current.date())
    state = _state_for_target(settings.next_week_state_path, target)
    return _check_week(settings, target, current, state, scraper, image_dir, progress, process, send)


def _check_week(
    settings, target, current, state, scraper, image_dir, progress, process, send, *, refresh=False,
) -> NextWeekWatchResult:
    def finish(status, message, *, found=False, coverage=None, stats=None, error=None):
        _remember_attempt(settings, target, current, state, status, error, send, progress)
        if error:
            progress(message)
        return _attempt_result(
            target, coverage or before, found, message, stats=stats, error=error,
        )

    def missing_target():
        unreadable = _unreadable_titles(titles)
        if unreadable:
            reason = "식단표 게시글에서 주차를 읽지 못했습니다: " + " | ".join(unreadable[:3])
            return finish("title_unreadable", f"{target.isoformat()} 주차 — {reason}", error=reason)
        if before["covered"]:
            status = "refresh_not_found" if before["status"] == "complete" else "partial"
            return finish(status, f"{target.isoformat()} 주차 게시글을 목록에서 추가 확인하지 못했습니다.")
        return finish(
            "not_posted", f"최근 목록에서 {target.isoformat()} 주차 게시글을 찾지 못했습니다. 다음 예정 시각에 다시 확인합니다.",
        )

    before = _coverage_summary(target, 0)
    try:
        before = _stored_week_coverage(settings, target)
    except (OSError, sqlite3.Error) as exc:
        reason = _db_error(exc)
        return finish("db_error", f"{target.isoformat()} 주차 — {reason}", error=reason)

    if before["status"] == "complete":
        if not refresh:
            if state.get("confirmed_week_start") != target.isoformat():
                _mark_confirmed(state, target, current)
                _record_attempt(state, current, "confirmed")
                _save_state(settings.next_week_state_path, state, progress)
            return NextWeekWatchResult(
                target, True, True, f"{target.isoformat()} 주차 식단이 이미 저장돼 있어 재시도를 건너뜁니다.",
                confirmed=True, servable=True,
            )
        progress(f"{target.isoformat()} 주차 식단의 변경 사항을 확인합니다.")
    else:
        state.pop("confirmed_week_start", None)
        state.pop("confirmed_at", None)

    scraper = scraper or GroupwareScraper(settings, headless=True)
    try:
        titles = scraper.list_recent_titles(max_pages=MAX_TITLE_PAGES)
        matched = [post for post in titles if _matches_target(post, target)]
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        return finish("error", f"{target.isoformat()} 주차 목록 확인 실패: {reason}", error=reason)

    preceding = []
    if before["status"] != "complete":
        previous_week = target - timedelta(days=7)
        preceding = [post for post in titles if _matches_target(post, previous_week)][:MAX_PRECEDING_POSTS]
    if not matched and not preceding:
        return missing_target()

    try:
        matched_rows = _collect_rows(scraper, matched)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        return finish("error", f"{target.isoformat()} 주차 첨부 수집 실패: {reason}", found=True, error=reason)

    try:
        with closing(MenuDB(settings.database_path)) as db:
            stats = process(matched_rows, db, image_dir, progress=progress, week_start=target)
            after = week_coverage(db, target)
            if preceding and after["status"] != "complete":
                # 지난 주 제목이 붙어 있어도 첨부의 실제 날짜로 대상 주차만 저장한다.
                try:
                    fallback_rows = _collect_rows(scraper, preceding)
                except Exception as exc:
                    reason = f"이전 주차 첨부 확인 실패 ({type(exc).__name__})"
                    return finish("error", reason, found=bool(matched), coverage=after, stats=stats, error=reason)
                more = process(fallback_rows, db, image_dir, progress=progress, week_start=target)
                stats = _combine_ingest_stats(stats, more)
                after = week_coverage(db, target)
            if after["status"] == "complete" and not stats.get("errors") and stats.get("entries"):
                structure = format_week_structure(db, target)
                locations = _week_locations(db, target)
    except (OSError, sqlite3.Error) as exc:
        reason = _db_error(exc)
        return finish("db_error", f"{target.isoformat()} 주차 — {reason}", found=True, error=reason)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        return finish("ingest_failed", f"{target.isoformat()} 주차 수집 실패: {reason}", found=True, error=reason)

    if not matched and not stats.get("entries") and not stats.get("errors"):
        return missing_target()
    if stats.get("errors") or not stats.get("entries"):
        reason = _ingest_error(stats)
        return finish(
            "ingest_failed",
            f"{target.isoformat()} 주차에서 식단 처리에 실패한 항목이 있습니다. 다음 예정 시각에 다시 확인합니다.",
            found=True, coverage=after, stats=stats, error=reason,
        )

    if after["status"] != "complete":
        if after["status"] == "empty":
            reason = f"{target.isoformat()} 주차에서 조회 가능한 끼니를 확인하지 못했습니다."
            return finish("not_servable", reason, found=True, coverage=after, stats=stats, error=reason)
        total = f"{after['covered']}/{after['expected']}"
        message = f"{target.isoformat()} 주차 식단 {total}끼니를 확인했습니다. 누락 끼니는 계속 확인합니다."
        return finish("partial", message, found=True, coverage=after, stats=stats)

    _mark_confirmed(state, target, current)
    _record_attempt(state, current, "confirmed")
    recorded = _save_state(settings.next_week_state_path, state, progress)
    notified = False
    if recorded and before["status"] != "complete" and state.get("success_notified_week") != target.isoformat():
        subject, body = success_mail(
            target, _checked_at(settings, current), stats, structure,
            locations=locations, split_by_site=PRIMARY_LOCATION not in locations and len(locations) > 1,
        )
        notified = _send_notice(send, subject, body, progress)
        if notified:
            state["success_notified_week"] = target.isoformat()
            _save_state(settings.next_week_state_path, state, progress)

    message = f"{target.isoformat()} 주차 식단을 확인하고 저장했습니다. 평일 세 끼가 모두 확보됐습니다."
    progress(message)
    return NextWeekWatchResult(
        target, False, True, message,
        stats=stats, confirmed=True, servable=True, notified=notified,
    )


def _collect_rows(scraper, candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []
    candidate_ids = {post["id"] for post in candidates}
    last_page = min(MAX_TITLE_PAGES, max(post.get("page", 1) for post in candidates))
    collected = scraper.collect(max_pages=last_page, target_post_ids=candidate_ids)
    return [post for post in collected if post["id"] in candidate_ids]


def _combine_ingest_stats(first: dict, second: dict) -> dict:
    counts = {
        key: first.get(key, 0) + second.get(key, 0)
        for key in ("posts", "images", "entries", "filtered_entries", "skipped_images")
    }
    return {**counts, "errors": first.get("errors", []) + second.get("errors", [])}


def _db_error(exc: Exception) -> str:
    error_name = getattr(exc, "sqlite_errorname", type(exc).__name__)
    return f"식단 DB 접근 실패 ({error_name})"


def _week_for(today: date) -> date:
    if today.weekday() >= WEEKDAYS:
        return next_monday(today)
    return today - timedelta(days=today.weekday())


def _week_locations(db: MenuDB, week_start: date) -> list[str]:
    return sorted({
        row["location"]
        for offset in range(WEEKDAYS)
        for row in db.query(week_start + timedelta(days=offset))
    })


def ensure_week_menu(
    settings: Settings,
    now: datetime | None = None,
    scraper: GroupwareScraper | None = None,
    image_dir: Path = Path("data/images"),
    progress=print,
    process=process_manifest,
    send=send_mail,
    *,
    refresh: bool = False,
) -> NextWeekWatchResult:
    """필요한 주차를 다시 수집하며, 정정 확인이 지정되면 확보된 주차도 갱신한다."""
    current = _local_now(settings, now)
    target = _week_for(current.date())
    state = _state_for_target(settings.next_week_state_path, target)
    result = _check_week(
        settings, target, current, state, scraper, image_dir, progress, process, send, refresh=refresh,
    )
    if not result.confirmed and current.date().weekday() < WEEKDAYS:
        _send_deadline_notice(settings, target, current, state, send, progress)
    return result


def check_next_week_deadline(
    settings: Settings,
    now: datetime | None = None,
    progress=print,
    send=send_mail,
) -> DeadlineCheckResult:
    """마감 점검은 상태 파일의 성공 기록 대신 현재 DB의 확보 범위를 확인한다."""
    current = _local_now(settings, now)
    target = next_monday(current.date())
    state = _state_for_target(settings.next_week_state_path, target)
    try:
        coverage = _stored_week_coverage(settings, target)
    except (OSError, sqlite3.Error) as exc:
        reason = _db_error(exc)
        _remember_attempt(settings, target, current, state, "db_error", reason, send, progress)
    else:
        if coverage["status"] == "complete":
            return DeadlineCheckResult(target, True, False, False, f"{target.isoformat()} 주차 식단은 확보돼 있습니다.")
        state.pop("confirmed_week_start", None)
        state.pop("confirmed_at", None)

    already_alerted = state.get("deadline_alert_sent_week") == target.isoformat()
    if already_alerted:
        return DeadlineCheckResult(target, False, False, True, f"{target.isoformat()} 주차 미확보 알림은 이미 보냈습니다.")
    alerted = _send_deadline_notice(settings, target, current, state, send, progress)
    message = "알림 메일을 보냈습니다." if alerted else "알림 메일 발송에 실패했습니다."
    return DeadlineCheckResult(target, False, alerted, False, f"{target.isoformat()} 주차 식단 미확보 — {message}")


def _send_deadline_notice(settings, target, current, state, send, progress) -> bool:
    if state.get("deadline_alert_sent_week") == target.isoformat():
        return False
    subject, body = deadline_alert_mail(target, _checked_at(settings, current), state)
    if not _send_notice(send, subject, body, progress):
        _save_state(settings.next_week_state_path, state, progress)
        return False
    state["deadline_alert_sent_week"] = target.isoformat()
    _save_state(settings.next_week_state_path, state, progress)
    return True


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
    return target <= parsed.start_date < target + timedelta(days=7)


def _ingest_error(stats: dict) -> str:
    if stats.get("errors"):
        return f"process_manifest 오류: {stats['errors']}"
    return (
        f"이미지 {stats.get('images', 0)}장 중 식단표로 인식된 것이 없어 "
        f"메뉴 항목 0건(제외 {stats.get('skipped_images', 0)}장)"
    )
