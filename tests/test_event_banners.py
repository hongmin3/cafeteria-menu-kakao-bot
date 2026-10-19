"""Validates: REQ-OCR-003, REQ-OCR-004.

좌표는 2026-10-19 주차 운영 서버 OCR 캐시(목요일 체육대회 그림)에서 가져왔다.
"""
from datetime import date, datetime

from menu_bot.db import MenuDB
from menu_bot.models import SourcePost
from menu_bot.parser import parse_ocr_lines
from menu_bot.query import answer


def line(text, x, y, width=0.07, height=0.026):
    return dict(text=text, x=x, y=y, width=width, height=height, confidence=0.99)


LABELS = [
    line('일반식', 0.074, 0.772, 0.033, 0.028), line('조식', 0.012, 0.736, 0.033, 0.038),
    line('PLUS코너', 0.064, 0.677, 0.053, 0.026), line('간편식', 0.074, 0.643, 0.033, 0.029),
    line('일반식', 0.074, 0.534, 0.034, 0.027), line('중식', 0.012, 0.465, 0.031, 0.037),
    line('PLUS코너', 0.063, 0.392, 0.054, 0.026), line('건강식', 0.074, 0.325, 0.034, 0.029),
    line('석식', 0.01, 0.211, 0.034, 0.04), line('일반식', 0.074, 0.231, 0.034, 0.029),
    line('PLUS 코너', 0.061, 0.135, 0.058, 0.026),
]
HEADERS = [
    line('10/21(수)', 0.532, 0.862, 0.066, 0.04),
    line('10/22(목)', 0.706, 0.868, 0.064, 0.031),
    line('10/23(금)', 0.878, 0.867, 0.065, 0.033),
]
WEDNESDAY = [
    line('건새우아욱국', 0.532, 0.835, 0.063, 0.029),
    line('미나리돼지곰탕', 0.528, 0.582, 0.071, 0.026),
    line('사골만두떡국', 0.532, 0.295, 0.063, 0.026),
]
FRIDAY = [
    line('얼큰양해장국', 0.877, 0.835, 0.065, 0.029),
    line('부추잔치국수', 0.878, 0.582, 0.063, 0.026),
    line('버터장조림비빔밥', 0.865, 0.295, 0.089, 0.026),
]
# 목요일 칸 전체를 덮은 체육대회 그림. 글씨 높이가 일반 메뉴의 약 4배다.
SPORTS_DAY = [
    line('뷰웍스', 0.675, 0.641, 0.118, 0.095),
    line('체육대황', 0.66, 0.553, 0.165, 0.099),
]


def post(start, title):
    return SourcePost(post_id='test-event', title=title, location='테스트', start_date=start)


def this_week():
    return post(date(2026, 10, 19), '[테스트] 2026-10-19 ~ 2026-10-23')


def parse(source, lines):
    return parse_ocr_lines(source, 'https://example.com/menu.png', lines)


def by_day(entries, day):
    return {(e.meal_type, e.category, e.status, e.menu_text) for e in entries if e.service_date == day}


def test_event_banner_only_column_closes_all_meals(tmp_path):
    source = this_week()
    entries = parse(source, LABELS + HEADERS + WEDNESDAY + FRIDAY + SPORTS_DAY)
    message = '뷰웍스 체육대회 (식당 미운영)'
    assert by_day(entries, date(2026, 10, 22)) == {
        ('조식', '안내', 'no_service', message),
        ('중식', '안내', 'no_service', message),
        ('석식', '안내', 'no_service', message),
    }
    db = MenuDB(tmp_path / 'menus.db')
    try:
        db.save_post(source)
        db.replace_entries(source.post_id, entries)
        now = datetime(2026, 10, 20, 12)
        for question in ('목요일', '목요일 아침', '목요일 점심', '목요일 저녁'):
            response = answer(db, question, 'Asia/Seoul', now=now)
            assert '식당 미운영' in response
            assert '체육대황' not in response
            assert '<일반식>' not in response
        assert '부추잔치국수' in answer(db, '금요일 점심', 'Asia/Seoul', now=now)
    finally:
        db.close()


def test_neighbour_days_keep_their_menus():
    entries = parse(this_week(), LABELS + HEADERS + WEDNESDAY + FRIDAY + SPORTS_DAY)
    for day, food in ((date(2026, 10, 21), '미나리돼지곰탕'), (date(2026, 10, 23), '부추잔치국수')):
        assert all(status == 'normal' for _, _, status, _ in by_day(entries, day))
        assert any(food in text for _, _, _, text in by_day(entries, day))


def test_large_banner_beside_food_does_not_close_the_day():
    lunch_food = line('돈버섯불고기', 0.706, 0.582, 0.064, 0.026)
    entries = parse(this_week(), LABELS + HEADERS + FRIDAY + SPORTS_DAY + [lunch_food])
    thursday = by_day(entries, date(2026, 10, 22))
    assert all(status != 'no_service' for _, _, status, _ in thursday)
    assert any('돈버섯불고기' in text for _, _, _, text in thursday)


def test_normal_size_short_items_are_not_treated_as_banner():
    small = [line('김밥', 0.72, 0.582, 0.03, 0.026), line('숭늉', 0.72, 0.134, 0.025, 0.029)]
    entries = parse(this_week(), LABELS + HEADERS + FRIDAY + small)
    thursday = by_day(entries, date(2026, 10, 22))
    assert thursday and all(status == 'normal' for _, _, status, _ in thursday)


def test_next_week_board_attached_to_previous_post_keeps_friday():
    previous = post(date(2026, 10, 12), '[테스트] 2026-10-12 ~ 2026-10-16')
    entries = parse(previous, LABELS + HEADERS + WEDNESDAY + FRIDAY + SPORTS_DAY)
    days = {e.service_date for e in entries}
    assert days == {date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)}
    assert any('부추잔치국수' in e.menu_text for e in entries if e.service_date == date(2026, 10, 23))


def test_header_far_from_post_week_is_ignored():
    old = post(date(2026, 10, 5), '[테스트] 2026-10-05 ~ 2026-10-09')
    entries = parse(old, LABELS + HEADERS + WEDNESDAY + FRIDAY)
    # 10/21까지는 16일, 10/23까지는 18일이라 날짜 줄로 받지 않는다.
    assert entries == []
