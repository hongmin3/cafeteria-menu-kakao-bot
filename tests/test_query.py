from datetime import datetime
from zoneinfo import ZoneInfo

from menu_bot.query import parse_query


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
    assert parsed.location == "평촌"
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

