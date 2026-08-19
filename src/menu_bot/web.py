from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from .config import get_settings
from .db import MenuDB
from .query import answer


app = FastAPI(title="Vieworks Menu Kakao Skill")


def kakao_response(text: str) -> dict:
    outputs = []
    if len(text) <= 900:
        chunks = [text]
    else:
        header, *sections = text.split("\n\n[")
        chunks = [header + "\n\n[" + section for section in sections[:3]] if sections else [text[:900]]
    for chunk in chunks:
        outputs.append({"simpleText": {"text": chunk[:1000]}})
    return {
        "version": "2.0",
        "template": {"outputs": outputs},
    }


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    db = MenuDB(settings.database_path)
    try:
        return {"ok": True, "entries": db.count_entries()}
    finally:
        db.close()


@app.post("/kakao/skill")
@app.post("/kakao/skill/{token}")
async def kakao_skill(request: Request, token: str = "") -> dict:
    settings = get_settings()
    if settings.webhook_token and token != settings.webhook_token:
        raise HTTPException(status_code=404)
    payload = await request.json()
    utterance = str(payload.get("userRequest", {}).get("utterance", "")).strip()
    if not utterance:
        return kakao_response("‘오늘 점심’, ‘평촌 금요일 아침’처럼 물어봐 주세요.")
    db = MenuDB(settings.database_path)
    try:
        return kakao_response(answer(db, utterance, settings.timezone, settings.default_location))
    finally:
        db.close()

