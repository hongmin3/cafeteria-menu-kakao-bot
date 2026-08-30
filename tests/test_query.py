from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

from menu_bot.db import MenuDB
from menu_bot.models import MenuEntry
from menu_bot.pipeline import filter_entries_to_week
from menu_bot.query import answer, looks_like_menu_query, parse_query, query_issue
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


def test_next_week_can_be_parsed_but_is_rejected_by_answer_validation():
    parsed = parse_query("평촌 다음주 화요일 저녁", NOW)
    assert parsed.day.isoformat() == "2026-08-25"
    assert parsed.location is None
    assert parsed.meal_type == "석식"


def test_weekend_weekday_still_means_current_week():
    weekend = datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    parsed = parse_query("월요일 아침", weekend)
    assert parsed.day.isoformat() == "2026-08-17"
    assert parsed.scope == "current_week"


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


def test_special_status_is_explicitly_emphasized(tmp_path: Path):
    db = MenuDB(tmp_path / "menus.db")
    try:
        db.replace_entries(
            "special",
            [MenuEntry(date(2026, 8, 19), "뷰웍스", "중식", "일반식", "해물백짬뽕 · 유린기",
                       status="special", source_post_id="special")],
        )
        result = answer(db, "오늘 점심", "Asia/Seoul", now=NOW)
    finally:
        db.close()
    assert "✨ 특식 <일반식>" in result
    assert "해물백짬뽕" in result


def test_full_day_response_splits_into_meal_bubbles():
    response = kakao_response("날짜\n\n[조식]\n- A\n\n[중식]\n- B\n\n[석식]\n- C")
    outputs = response["template"]["outputs"]
    assert len(outputs) == 3
    assert outputs[0]["simpleText"]["text"].startswith("날짜\n\n[조식]")
    assert response["template"]["quickReplies"] == [
        {"action": "message", "label": "오늘의 아침", "messageText": "오늘 아침"},
        {"action": "message", "label": "오늘의 점심", "messageText": "오늘 점심"},
        {"action": "message", "label": "오늘의 저녁", "messageText": "오늘 저녁"},
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


@pytest.mark.parametrize(
    ("utterance", "message_part"),
    [
        ("다음주", "이번 주 식단만"),
        ("다음 주 점심", "이번 주 식단만"),
        ("담주 메뉴", "이번 주 식단만"),
        ("차주 저녁", "이번 주 식단만"),
        ("이번주", "요일을 함께"),
        ("이번 주 아침", "요일을 함께"),
        ("금주 메뉴", "요일을 함께"),
        ("오늘 내일 점심", "날짜를 하나만"),
        ("이번주 다음주 월요일", "이번 주 식단만"),
        ("다음주 오늘 점심", "이번 주 식단만"),
        ("이번주 오늘 점심", "주차와 날짜 표현"),
        ("오늘 수요일 점심", "날짜와 요일을 하나만"),
        ("월요일 화요일", "요일을 하나만"),
        ("월 화 점심", "요일을 하나만"),
        ("화요일 아침 점심", "끼니를 하나만"),
        ("지난주 월요일", "이번 주 식단만"),
        ("저번주 금요일", "이번 주 식단만"),
        ("다다음주 월요일", "이번 주 식단만"),
        ("2월 30일 점심", "날짜를 확인"),
        ("13/40 저녁", "날짜를 확인"),
    ],
)
def test_ambiguous_or_unsupported_queries_get_clarification(utterance: str, message_part: str):
    issue = query_issue(utterance, NOW.date())
    assert issue is not None
    assert message_part in issue


@pytest.mark.parametrize(
    "utterance",
    [
        "이번주 목요일",
        "오늘",
        "내일 점심",
        "8월 20일 점심",
        "8/20 저녁",
        "화요일",
        "아침",
    ],
)
def test_unambiguous_queries_do_not_get_clarification(utterance: str):
    assert query_issue(utterance, NOW.date()) is None


def test_next_week_is_never_served_or_falls_back_to_today(tmp_path: Path):
    db = MenuDB(tmp_path / "menus.db")
    try:
        db.replace_entries(
            "post-today",
            [MenuEntry(date(2026, 8, 19), "뷰웍스", "중식", "일반식", "오늘메뉴", source_post_id="post-today")],
        )
        result = answer(db, "다음주", "Asia/Seoul", now=NOW)
    finally:
        db.close()
    assert "이번 주 식단만" in result
    assert "오늘메뉴" not in result


def test_explicit_next_week_date_is_rejected(tmp_path: Path):
    db = MenuDB(tmp_path / "menus.db")
    try:
        db.replace_entries(
            "post-next",
            [MenuEntry(date(2026, 8, 24), "뷰웍스", "중식", "일반식", "차주메뉴", source_post_id="post-next")],
        )
        result = answer(db, "8월 24일 점심", "Asia/Seoul", now=NOW)
    finally:
        db.close()
    assert "이번 주 식단만" in result
    assert "차주메뉴" not in result


def test_operational_ingest_keeps_only_current_week_entries():
    entries = [
        MenuEntry(date(2026, 8, 16), "뷰웍스", "중식", "일반식", "지난주", source_post_id="p"),
        MenuEntry(date(2026, 8, 17), "뷰웍스", "중식", "일반식", "이번주월", source_post_id="p"),
        MenuEntry(date(2026, 8, 21), "뷰웍스", "중식", "일반식", "이번주금", source_post_id="p"),
        MenuEntry(date(2026, 8, 23), "뷰웍스", "중식", "일반식", "이번주일", source_post_id="p"),
        MenuEntry(date(2026, 8, 24), "뷰웍스", "중식", "일반식", "다음주", source_post_id="p"),
    ]
    selected, filtered = filter_entries_to_week(entries, date(2026, 8, 17))
    assert [entry.menu_text for entry in selected] == ["이번주월", "이번주금", "이번주일"]
    assert filtered == 2
