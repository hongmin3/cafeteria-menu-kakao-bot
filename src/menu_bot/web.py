from __future__ import annotations

from contextlib import asynccontextmanager, closing
from datetime import date, datetime, timedelta
from hmac import compare_digest
import json
import logging
import os
import re
import sqlite3
import textwrap
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import MenuDB
from .query import (
    HELP_TEXT, INGREDIENT_QUESTION, WEEK_MENU_PROMPT, answer, looks_like_menu_query, normalize_query,
    parse_query, query_issue, requested_corners, requested_locations, requested_meals, week_menu_days,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("MENUBOT_REQUIRE_TOKEN") == "1" and not get_settings().webhook_token:
        raise RuntimeError("Kakao webhook authentication is required")
    yield


app = FastAPI(title="Vieworks Menu Kakao Skill", lifespan=lifespan)
logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 64 * 1024
MAX_UTTERANCE = 250
MOBILE_TEXT_LIMIT = 480
DB_TIMEOUT = 0.75
HELP_WORDS = {"도움", "도움말", "사용법", "사용방법", "안녕", "안녕하세요"}
DETAIL = re.compile(r"^식단상세 ([1-9][0-9]{0,3}) (20\d{2}) (\d{1,2})/(\d{1,2})(?: (.*))?$")
MEAL_ORDER = ("조식", "중식", "석식")
SOURCE_LINKS = {
    "원본식단표확인": ("KAKAO_MENU_SOURCE_URL", "원본 식단표 확인"),
    "식단오류제보": ("KAKAO_MENU_REPORT_URL", "식단 오류 제보"),
}

QUICK_REPLIES = [
    {"action": "message", "label": "오늘의 아침", "messageText": "오늘 아침"},
    {"action": "message", "label": "오늘의 점심", "messageText": "오늘 점심"},
    {"action": "message", "label": "오늘의 저녁", "messageText": "오늘 저녁"},
    {"action": "message", "label": "사용방법", "messageText": "사용방법"},
]


def _button(label: str, message: str | None = None) -> dict:
    return {"action": "message", "label": label, "messageText": message or label}


def _source_link(key: str) -> str:
    value = os.getenv(SOURCE_LINKS[key][0], "").strip()
    if not value or len(value) > 240 or any(char.isspace() for char in value):
        return ""
    try:
        url = urlsplit(value)
        if url.scheme == "https" and url.hostname and not url.username and not url.password:
            return value
    except ValueError:
        pass
    return ""


def _linked_replies(labels) -> list[dict]:
    return [_button(SOURCE_LINKS[label][1]) for label in labels if _source_link(label)]


def _body_pages(title: str, body: str) -> list[str]:
    """Avoid folding ordinary results and carry every menu item to a detail page."""
    allowance = MOBILE_TEXT_LIMIT - len(title) - 1
    pages, lines = [], []
    length = 0
    for line in body.split("\n"):
        pieces = textwrap.wrap(
            line, width=allowance, replace_whitespace=False, drop_whitespace=False,
            expand_tabs=False,
        ) or [""]
        for piece in pieces:
            if lines and length + len(piece) + 1 > allowance:
                pages.append(title + "\n" + "\n".join(lines).rstrip())
                lines, length = [], 0
            if piece or lines:
                length += len(piece) + bool(lines)
                lines.append(piece)
    if lines:
        pages.append(title + "\n" + "\n".join(lines).rstrip())
    return pages or [title]


def kakao_response(
    text: str, *, replies: list[dict] | None = None, detail: str = "", offset: int = 0,
) -> dict:
    # A full-day query becomes one bubble per meal. This keeps vertical menus
    # readable and stays within Kakao's three-output response limit.
    header, *sections = re.split(r"\n\n(?=\[(?:조식|중식|석식)\]\n)", text)
    if sections:
        chunks = []
        for section in sections:
            meal, _, body = section.partition("\n")
            chunks.extend(_body_pages(f"{header}\n\n{meal}", body))
    else:
        chunks = [text]
    visible = chunks[offset:offset + 3] or ["이 페이지의 메뉴를 찾을 수 없어요. 다시 조회해 주세요."]
    buttons = list(QUICK_REPLIES if replies is None else replies)
    if detail and offset + 3 < len(chunks):
        buttons.insert(0, _button("다음 항목", f"식단상세 {offset + 3} {detail}"))
    if detail and offset > 0:
        previous = f"식단상세 {offset - 3} {detail}" if offset > 3 else _detail_utterance(detail)
        index = 1 if buttons and buttons[0]["label"] == "다음 항목" else 0
        buttons.insert(index, _button("이전 항목", previous))
    if not any(button["label"] == "사용방법" for button in buttons[:9]):
        buttons = buttons[:9] + [_button("사용방법")]
    return {
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": chunk}} for chunk in visible],
            "quickReplies": buttons[:10],
        },
    }


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _coverage(db: MenuDB, current: datetime) -> dict:
    from .next_week_watch import week_coverage

    return week_coverage(db, _week_start(current.date()))


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    try:
        with closing(MenuDB(settings.database_path, read_only=True, timeout=DB_TIMEOUT)) as db:
            current = datetime.now(ZoneInfo(settings.timezone))
            return {
                "ok": True, "entries": db.count_entries(),
                "current_week": _coverage(db, current),
            }
    except sqlite3.DatabaseError as exc:
        raise HTTPException(status_code=503, detail="Menu database unavailable") from exc


def _valid_token(supplied: str, expected: str) -> bool:
    return bool(expected) and compare_digest(supplied.encode(), expected.encode())


@app.get("/kakao/probe")
def kakao_probe(request: Request):
    settings = get_settings()
    scheme, _, supplied = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not _valid_token(supplied, os.getenv("MENUBOT_PROBE_TOKEN", "")):
        raise HTTPException(status_code=404)
    from .ops import storage_signal

    storage = storage_signal(settings.database_path)
    current = datetime.now(ZoneInfo(settings.timezone))
    try:
        with closing(MenuDB(settings.database_path, read_only=True, timeout=DB_TIMEOUT)) as db:
            coverage = _coverage(db, current)
            # On weekdays the check uses the same answer generation as the user path.
            # Each answer may describe either a meal or a verified closure.
            ok = current.weekday() >= 5 or any(
                answer(db, f"오늘 {meal}", settings.timezone, now=current).startswith("🍽")
                for meal in ("중식", "조식", "석식")
            )
    except sqlite3.DatabaseError:
        return JSONResponse({
            "ok": False, "status": "db_unavailable", "covered": 0, "expected": 15, "storage": storage,
        }, status_code=503)
    return {"ok": ok, **coverage, "storage": storage}


def _detail_utterance(detail: str) -> str:
    year, short_date, *rest = detail.split(maxsplit=2)
    month, day = short_date.split("/")
    return " ".join((f"{year}년 {month}월 {day}일", *rest))


def _detail_context(query: str, current: datetime, locations: tuple[str, ...]) -> str:
    parsed = parse_query(query, current, locations)
    return " ".join(filter(None, (
        f"{parsed.day:%Y %m/%d}", parsed.location, parsed.meal_type, parsed.category,
    )))


def _menu_replies(menu_found: bool, query: str, current: datetime, locations: tuple[str, ...]) -> list[dict]:
    if menu_found:
        parsed = parse_query(query, current, locations)
        replies = [_button("오늘 전체"), _button("내일 식단"), _button("이번 주")]
        if parsed.day == current.date() and parsed.meal_type != "석식":
            replies.insert(0, _button("오늘 저녁"))
        return replies + _linked_replies(SOURCE_LINKS)
    return [_button("다시 조회", query), _button("이번 주")] + _linked_replies(SOURCE_LINKS)


def _handle_utterance(settings, utterance: str) -> dict:
    normalized = normalize_query(utterance).replace(" ", "")
    if not normalized or normalized in HELP_WORDS:
        return kakao_response(
            HELP_TEXT,
            replies=list(QUICK_REPLIES[:3]) + [
                _button("오늘 전체"), _button("내일 식단"), _button("이번 주"),
            ] + _linked_replies(SOURCE_LINKS),
        )
    if normalized in SOURCE_LINKS:
        link = _source_link(normalized)
        text = f"{SOURCE_LINKS[normalized][1]}\n{link}" if link else (
            "사내 그룹웨어의 원본 식단표를 보거나 담당자에게 문의해 주세요."
        )
        return kakao_response(text)
    if INGREDIENT_QUESTION.search(utterance):
        return kakao_response(
            "원재료와 알레르기는 식단명만으로 확인하기 어려워요. 원본 식단표나 식당 담당자에게 확인해 주세요.",
            replies=_linked_replies(("원본식단표확인",)),
        )
    current = datetime.now(ZoneInfo(settings.timezone))
    issues = query_issue(utterance, current.date(), settings.post_prefixes)
    if issues == WEEK_MENU_PROMPT:
        days = week_menu_days(utterance, current.date(), settings.post_prefixes)
        filters = (*requested_locations(utterance, settings.post_prefixes), *requested_meals(utterance),
                   *requested_corners(utterance))
        weekdays = "월화수목금토일"
        buttons = [
            _button(f"{weekdays[index]}요일", " ".join((f"{weekdays[index]}요일", *filters)))
            for index in days
        ]
        return kakao_response(WEEK_MENU_PROMPT, replies=buttons)

    offset = 0
    requested_detail = DETAIL.fullmatch(utterance)
    if requested_detail:
        offset = int(requested_detail[1])
        utterance = _detail_utterance(utterance.split(maxsplit=2)[2])
        issues = query_issue(utterance, current.date(), settings.post_prefixes)
    if not looks_like_menu_query(utterance):
        return kakao_response("무슨 말씀인지 잘 못 알아들었어요. 😅\n\n" + HELP_TEXT)
    if issues:
        # Where the date is recognizable, offer a fresh explicit choice. Ambiguous
        # dates must never be converted into an implicit today query.
        date_words = list(dict.fromkeys(re.findall(
            r"(?:20\d{2}년\s*)?\d{1,2}월\s*\d{1,2}일|\d{1,2}/\d{1,2}|[월화수목금토일]요일|오늘|내일|모레|어제",
            normalize_query(utterance),
        )))
        buttons = [_button("이번 주"), _button("오늘 전체")]
        if len(date_words) == 1 and ("알아듣지 못했어요" in issues or "끼니를" in issues):
            prefix = date_words[0]
            buttons = [_button(meal, f"{prefix} {meal}") for meal in MEAL_ORDER] + buttons
        return kakao_response(issues.split("\n\n" + HELP_TEXT, 1)[0], replies=buttons)

    from .next_week_watch import latest_week_attempt
    try:
        with closing(MenuDB(settings.database_path, read_only=True, timeout=DB_TIMEOUT)) as db:
            last = latest_week_attempt(settings.next_week_state_path, _week_start(current.date()))
            text = answer(
                db, utterance, settings.timezone, settings.default_location, now=current,
                locations=settings.post_prefixes, collection_status=last,
            )
    except sqlite3.DatabaseError as exc:
        error_name = getattr(exc, "sqlite_errorname", type(exc).__name__)
        logger.warning("Kakao menu database unavailable (%s)", error_name)
        text = "지금은 식단을 조회하기 어려워요. 잠시 후 다시 물어봐 주세요."
    menu_found = text.startswith("🍽")
    detail = _detail_context(utterance, current, settings.post_prefixes) if menu_found else ""
    return kakao_response(text, replies=_menu_replies(menu_found, utterance, current, settings.post_prefixes),
                          detail=detail, offset=offset if detail else 0)


@app.post("/kakao/skill")
@app.post("/kakao/skill/{token}")
async def kakao_skill(request: Request, token: str = "") -> dict:
    settings = get_settings()
    if not settings.webhook_token or not (
        _valid_token(token, settings.webhook_token)
        or _valid_token(token, os.getenv("KAKAO_WEBHOOK_TOKEN_PREVIOUS", ""))
    ):
        raise HTTPException(status_code=404)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(status_code=400, detail="Invalid Kakao request")
        body.extend(chunk)
    try:
        utterance = json.loads(body)["userRequest"]["utterance"]
    except (ValueError, TypeError, KeyError, RecursionError):
        raise HTTPException(status_code=400, detail="Invalid Kakao request") from None
    if not isinstance(utterance, str) or len(utterance) > MAX_UTTERANCE:
        raise HTTPException(status_code=400, detail="Invalid Kakao request")
    return await run_in_threadpool(_handle_utterance, settings, utterance.strip())
