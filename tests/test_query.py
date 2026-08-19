from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

from menu_bot.db import MenuDB
from menu_bot.models import MenuEntry
from menu_bot.query import answer, looks_like_menu_query, parse_query
from menu_bot.web import HELP_TEXT, kakao_response


NOW = datetime(2026, 8, 19, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))


def test_friday_breakfast():
    parsed = parse_query("금요일 아침", NOW)
    assert parsed.day.isoformat() == "2026-08-21"
    assert parsed.meal_type == "조식"


def test_tuesday_lunch():
    parsed = parse_query("화요일 점심", NOW)
    assert parsed.day.isoformat() == "2026-08-18"
    assert parsed.meal_type == "중식"


def test_plain_breakfast_means_today():
    parsed = parse_query("아침", NOW)
    assert parsed.day.isoformat() == "2026-08-19"
    assert parsed.meal_type == "조식"


def test_location_and_next_week():
    parsed = parse_query("평촌 다음주 화요일 저녁", NOW)
    assert parsed.day.isoformat() == "2026-08-25"
    assert parsed.location is None
    assert parsed.meal_type == "석식"


def test_weekend_weekday_means_next_week():
    weekend = datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    parsed = parse_query("월요일 아침", weekend)
    assert parsed.day.isoformat() == "2026-08-24"
    assert parsed.scope == "next_week"


def test_single_weekday_character_returns_all_meals():
    parsed = parse_query("월", NOW)
    assert parsed.day.isoformat() == "2026-08-17"
    assert parsed.meal_type is None


def test_vertical_menu_format(tmp_path: Path):
    db = MenuDB(tmp_path / "menus.db")
    try:
        db.replace_entries(
            "post-1",
            [
                MenuEntry(date(2026, 8, 19), "뷰웍스", "중식", "일반식", "라면 · 연근", source_post_id="post-1"),
                MenuEntry(date(2026, 8, 19), "뷰웍스", "중식", "간편식", "샌드위치", source_post_id="post-1"),
                MenuEntry(date(2026, 8, 19), "뷰웍스", "중식", "PLUS 코너", "수정과 · 현미밥", source_post_id="post-1"),
            ],
        )
        result = answer(db, "오늘 점심", "Asia/Seoul", now=NOW)
    finally:
        db.close()
    assert "<일반식>\n- 라면\n- 연근" in result
    assert "<간편식>\n- 샌드위치" in result
    assert "<공통 PLUS>\n- 수정과\n- 현미밥" in result
    assert "- 연근\n\n<간편식>" in result
    assert "- 샌드위치\n\n<공통 PLUS>" in result


def test_full_day_response_splits_into_meal_bubbles():
    response = kakao_response("날짜\n\n[조식]\n- A\n\n[중식]\n- B\n\n[석식]\n- C")
    outputs = response["template"]["outputs"]
    assert len(outputs) == 3
    assert outputs[0]["simpleText"]["text"].startswith("날짜\n\n[조식]")
    assert response["template"]["quickReplies"] == [
        {"action": "message", "label": "사용방법", "messageText": "사용방법"}
    ]


def test_help_text_is_short_enough_for_one_bubble():
    assert len(HELP_TEXT) < 1000
    assert "금요일 점심" in HELP_TEXT


def test_weekend_reports_restaurant_closed(tmp_path: Path):
    db = MenuDB(tmp_path / "menus.db")
    try:
        result = answer(db, "토요일 점심", "Asia/Seoul", now=NOW)
    finally:
        db.close()
    assert result == "08월 22일(토) 주말에는 식당을 운영하지 않습니다."


@pytest.mark.parametrize(
    ("utterance", "expected_day", "expected_meal"),
    [
        ("낼점심", "2026-08-20", "중식"),
        ("금욜 저녁", "2026-08-21", "석식"),
        ("담주월 아침", "2026-08-24", "조식"),
        ("점심머야?", "2026-08-19", "중식"),
        ("목요일, 점심!", "2026-08-20", "중식"),
        ("토욜", "2026-08-22", None),
    ],
)
def test_common_casual_inputs(utterance: str, expected_day: str, expected_meal: str | None):
    parsed = parse_query(utterance, NOW)
    assert parsed.day.isoformat() == expected_day
    assert parsed.meal_type == expected_meal


@pytest.mark.parametrize(
    "utterance",
    ["오늘 뭐먹어", "밥 뭐야", "이번주 메뉴", "평촌점심", "주말", "월", "화", "수", "목", "금", "토", "일"],
)
def test_menu_intent_variations(utterance: str):
    assert looks_like_menu_query(utterance)


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("토", "08월 22일(토) 주말에는 식당을 운영하지 않습니다."),
        ("토요일", "08월 22일(토) 주말에는 식당을 운영하지 않습니다."),
        ("일", "08월 23일(일) 주말에는 식당을 운영하지 않습니다."),
        ("일요일", "08월 23일(일) 주말에는 식당을 운영하지 않습니다."),
    ],
)
def test_weekend_shorthand_reports_closed(tmp_path: Path, utterance: str, expected: str):
    db = MenuDB(tmp_path / "menus.db")
    try:
        result = answer(db, utterance, "Asia/Seoul", now=NOW)
    finally:
        db.close()
    assert result == expected


@pytest.mark.parametrize("utterance", ["asdf", "배고프다아아", "ㅎㅇ", "아무말"])
def test_unrecognized_inputs_get_help(utterance: str):
    assert not looks_like_menu_query(utterance)
