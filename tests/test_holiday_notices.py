"""Validates: REQ-OCR-001. 공휴일 글자가 음식 메뉴로 저장되는 회귀를 막는다."""
from datetime import date, datetime

import pytest

from menu_bot.db import MenuDB
from menu_bot.models import SourcePost
from menu_bot.parser import parse_ocr_lines
from menu_bot.query import answer


def line(text, x, y, width=0.1, height=0.02):
    return dict(text=text, x=x, y=y, width=width, height=height, confidence=0.99)


def board(notice):
    return [
        line('10/08(목)', 0.68, 0.87), line('10/09(금)', 0.877, 0.868, 0.0664, 0.034),
        line('조식', 0.011, 0.741, 0.032, 0.034),
        line('중식', 0.011, 0.467, 0.031, 0.037),
        line('석식', 0.011, 0.213, 0.033, 0.038),
        line('일반식', 0.074, 0.775, 0.034, 0.030),
        line('일반식', 0.074, 0.536, 0.033, 0.027),
        line('일반식', 0.073, 0.232, 0.035, 0.032),
        line('PLUS', 0.061, 0.137, 0.058, 0.026),
        line('쌀밥/김치', 0.68, 0.52),
        # 운영 OCR의 한글날 좌표: 중식 행 중앙에 있는 전일 휴무 그림.
        line(notice, 0.8536, 0.5066, 0.1212, 0.0832),
    ]


def parse(lines):
    post = SourcePost(post_id='test-holiday', title='[테스트] 2026-10-05 ~ 10-09',
                      location='테스트', start_date=date(2026, 10, 5))
    return post, parse_ocr_lines(post, 'https://example.com/menu.png', lines)


@pytest.mark.parametrize('notice', [
    '한글날', '개천절', '한 글 날', '(한글날)', '한글날 휴무',
    '신정', '설날', '설 연휴', '삼일절', '3·1절', '어린이날',
    '부처님 오신 날', '석가탄신일', '현충일', '광복절',
    '추석', '추석 연휴', '성탄절', '크리스마스', '근로자의 날',
])
def test_holiday_only_column_closes_all_meals(tmp_path, notice):
    post, entries = parse(board(notice))
    friday = [e for e in entries if e.service_date == date(2026, 10, 9)]
    assert {(e.meal_type, e.category, e.status) for e in friday} == {
        ('조식', '안내', 'no_service'), ('중식', '안내', 'no_service'), ('석식', '안내', 'no_service'),
    }
    db = MenuDB(tmp_path / 'menus.db')
    try:
        db.save_post(post)
        db.replace_entries(post.post_id, entries)
        for question in ('금요일', '금요일 아침', '금요일 점심', '금요일 저녁'):
            response = answer(db, question, 'Asia/Seoul', now=datetime(2026, 10, 6, 12))
            assert '식당 미운영' in response
            assert '<일반식>' not in response
        assert '쌀밥' in answer(db, '목요일 점심', 'Asia/Seoul', now=datetime(2026, 10, 6, 12))
    finally:
        db.close()


@pytest.mark.parametrize('text', ['한글날 특식', '추석 송편', '어린이날 돈까스', '크리스마스 케이크'])
def test_holiday_food_or_event_is_not_closed(text):
    _, entries = parse(board(text))
    friday = [e for e in entries if e.service_date == date(2026, 10, 9)]
    assert friday and all(e.status != 'no_service' for e in friday)
    assert any(text in e.menu_text for e in friday)


def test_holiday_label_with_actual_menu_does_not_close_day():
    _, entries = parse(board('한글날') + [line('쌀밥/김치', 0.86, 0.72)])
    friday = [e for e in entries if e.service_date == date(2026, 10, 9)]
    assert friday and all(e.status != 'no_service' for e in friday)
    assert any('쌀밥' in e.menu_text for e in friday)
    assert all('한글날' not in e.menu_text for e in friday)


def test_holiday_named_meal_closure_stays_meal_specific():
    _, entries = parse(board('한글날 중식 미운영') + [line('쌀밥/김치', 0.86, 0.72)])
    friday = [e for e in entries if e.service_date == date(2026, 10, 9)]
    closed = [e for e in friday if e.status == 'no_service']
    assert [(e.meal_type, e.category) for e in closed] == [('중식', '안내')]
    assert any(e.meal_type == '조식' and '쌀밥' in e.menu_text for e in friday)
