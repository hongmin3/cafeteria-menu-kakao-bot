from __future__ import annotations

from contextlib import closing
import logging
import sqlite3

from fastapi import FastAPI, HTTPException, Request

from .config import get_settings
from .db import MenuDB
from .query import HELP_TEXT, answer, looks_like_menu_query


app = FastAPI(title="Vieworks Menu Kakao Skill")
logger = logging.getLogger(__name__)


QUICK_REPLIES = [
    {"action": "message", "label": "오늘의 아침", "messageText": "오늘 아침"},
    {"action": "message", "label": "오늘의 점심", "messageText": "오늘 점심"},
    {"action": "message", "label": "오늘의 저녁", "messageText": "오늘 저녁"},
    {"action": "message", "label": "사용방법", "messageText": "사용방법"},
]


def kakao_response(text: str) -> dict:
    # A full-day query becomes one bubble per meal. This keeps vertical menus
    # readable and stays within Kakao's three-output response limit.
    header, *sections = text.split("\n\n[")
    chunks = [header + "\n\n[" + section for section in sections[:3]] if sections else [text]
    outputs = []
    for chunk in chunks:
        if len(chunk) > 1000:
            chunk = chunk[:960].rstrip() + "\n…메뉴가 길어 일부 생략됐어요."
        outputs.append({"simpleText": {"text": chunk}})
    return {
        "version": "2.0",
        "template": {
            "outputs": outputs,
            # Users can open today's meal without typing. Keep help available
            # alongside the three most common actions on every response.
            "quickReplies": QUICK_REPLIES,
        },
    }


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    try:
        with closing(MenuDB(settings.database_path, read_only=True)) as db:
            return {"ok": True, "entries": db.count_entries()}
    except sqlite3.DatabaseError as exc:
        raise HTTPException(status_code=503, detail="Menu database unavailable") from exc


@app.post("/kakao/skill")
@app.post("/kakao/skill/{token}")
async def kakao_skill(request: Request, token: str = "") -> dict:
    settings = get_settings()
    if settings.webhook_token and token != settings.webhook_token:
        raise HTTPException(status_code=404)
    payload = await request.json()
    utterance = str(payload.get("userRequest", {}).get("utterance", "")).strip()
    normalized = utterance.replace(" ", "")
    if not utterance or normalized in {"도움", "도움말", "사용법", "사용방법", "안녕", "안녕하세요"}:
        return kakao_response(HELP_TEXT)
    if not looks_like_menu_query(utterance):
        return kakao_response("무슨 말씀인지 잘 못 알아들었어요. 😅\n\n" + HELP_TEXT)
    try:
        with closing(MenuDB(settings.database_path, read_only=True)) as db:
            text = answer(
                db, utterance, settings.timezone, settings.default_location,
                locations=settings.post_prefixes,
            )
    except sqlite3.DatabaseError as exc:
        error_name = getattr(exc, "sqlite_errorname", type(exc).__name__)
        logger.warning("Kakao menu database unavailable (%s)", error_name)
        text = "지금은 식단을 조회하기 어려워요. 잠시 후 다시 물어봐 주세요."
    return kakao_response(text)
