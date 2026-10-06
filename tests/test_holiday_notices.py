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


@pytest.mark.parametrize('notice', [
    '설 명절', '설날 연휴', '한가위', '한가위 연휴', '추석 명절',
    '*추석 연휴*', '【성탄절】', '임시 공휴일', '대체 휴일',
    '식당 휴무', '식당 휴점', '식당 운영하지 않습니다',
    '추석 연휴로 인해 식당 휴무입니다', '설날 연휴 기간 미운영 안내', '한글날(금)',
    '10/09(금) 한글날', '10/09 임시 공휴일', '10/09(금) 삼일절',
])
def test_other_holiday_and_closure_notices_close_day(notice):
    _, entries = parse(board(notice))
    friday = [e for e in entries if e.service_date == date(2026, 10, 9)]
    assert {(e.meal_type, e.category, e.status) for e in friday} == {
        ('조식', '안내', 'no_service'), ('중식', '안내', 'no_service'), ('석식', '안내', 'no_service'),
    }


@pytest.mark.parametrize('pieces', [('설', '연휴'), ('추석', '연휴'), ('식당', '휴무'), ('한', '글', '날')])
@pytest.mark.parametrize('horizontal', [True, False])
def test_split_notice_is_reassembled(pieces, horizontal):
    lines = board('')[:-1]
    for i, text in enumerate(pieces):
        lines.append(line(text, 0.86 + (i * 0.025 if horizontal else 0),
                          0.54 - (0 if horizontal else i * 0.03), width=0.02))
    _, entries = parse(lines)
    friday = [e for e in entries if e.service_date == date(2026, 10, 9)]
    assert len(friday) == 3
    assert all(e.category == '안내' and e.status == 'no_service' for e in friday)


@pytest.mark.parametrize('notice,closed_meals', [
    ('석식 공휴일 미운영', {'석식'}),
    ('조식·석식 미운영', {'조식', '석식'}),
    ('아침/점심 휴무', {'조식', '중식'}),
    ('추석 조식/석식 휴무', {'조식', '석식'}),
])
def test_explicit_meals_take_priority_over_holiday_word(notice, closed_meals):
    _, entries = parse(board(notice) + [line('쌀밥/김치', 0.86, 0.72)])
    friday = [e for e in entries if e.service_date == date(2026, 10, 9)]
    assert {e.meal_type for e in friday if e.category == '안내' and e.status == 'no_service'} == closed_meals


@pytest.mark.parametrize('text', ['공휴일 특식', '노동절 특식', '휴일 케이크', '한글날 정상 운영'])
def test_holiday_word_does_not_mean_closure(text):
    _, entries = parse(board(text))
    friday = [e for e in entries if e.service_date == date(2026, 10, 9)]
    assert friday and all(e.status != 'no_service' for e in friday)


@pytest.mark.parametrize('text', ['건강식 미운영', '간편식 미제공'])
def test_corner_notice_does_not_close_whole_meal(text):
    _, entries = parse(board(text) + [line('쌀밥/김치', 0.86, 0.72)])
    friday = [e for e in entries if e.service_date == date(2026, 10, 9)]
    assert all(e.category != '안내' for e in friday)
    assert any('쌀밥' in e.menu_text and e.status != 'no_service' for e in friday)


@pytest.mark.parametrize('notice', ['추석 연휴', '10/08~10/09 추석 연휴', '10/08~09 추석 연휴'])
def test_notice_spanning_date_columns_covers_each_empty_day(notice):
    lines = [l for l in board('')[:-1] if l['text'] != '쌀밥/김치']
    lines.append(line(notice, 0.68, 0.50, width=0.28))
    _, entries = parse(lines)
    for day in (date(2026, 10, 8), date(2026, 10, 9)):
        assert {e.meal_type for e in entries if e.service_date == day and e.status == 'no_service'} == {'조식', '중식', '석식'}


def test_wide_holiday_banner_preserves_neighbour_with_food():
    lines = board('')[:-1] + [line('추석 연휴', 0.68, 0.50, width=0.28)]
    _, entries = parse(lines)
    thursday = [e for e in entries if e.service_date == date(2026, 10, 8)]
    assert thursday and all(e.status != 'no_service' for e in thursday)
    assert any('쌀밥' in e.menu_text for e in thursday)
    assert len([e for e in entries if e.service_date == date(2026, 10, 9) and e.status == 'no_service']) == 3


def test_split_notice_does_not_combine_across_dates():
    _, entries = parse(board('')[:-1] + [line('설', 0.68, 0.52, width=0.02), line('연휴', 0.88, 0.52, width=0.02)])
    assert all('설연휴' not in e.menu_text for e in entries)
    assert all(e.status != 'no_service' for e in entries if e.service_date == date(2026, 10, 8))


def test_other_image_with_food_prevents_name_only_closure(tmp_path):
    from menu_bot.pipeline import image_path, process_manifest
    import json

    urls = ['https://example.com/notice.png', 'https://example.com/food.png']
    for url, lines in zip(urls, [board('추석'), board('쌀밥/김치')]):
        path = image_path(url, tmp_path)
        path.write_bytes(b'cached image')
        path.with_suffix(path.suffix + '.ocr.json').write_text(json.dumps(lines), encoding='utf-8')
    db = MenuDB(tmp_path / 'menus.db')
    try:
        stats = process_manifest([{'id': 'test', 'title': '[테스트] 2026-10-05 ~ 10-09', 'images': urls}], db, tmp_path, progress=lambda _: None, week_start=date(2026, 10, 5))
        assert not stats['errors']
        response = answer(db, '금요일 점심', 'Asia/Seoul', now=datetime(2026, 10, 6, 12))
        assert '쌀밥' in response and '<운영 안내>' not in response
    finally:
        db.close()


def test_invalid_date_in_notice_does_not_discard_other_menu():
    _, entries = parse(board('13/40 식당 휴무'))
    assert any(e.service_date == date(2026, 10, 8) and '쌀밥' in e.menu_text for e in entries)
    assert all(e.category != '안내' for e in entries)


def test_unqualified_closure_with_other_meal_is_kept_in_its_row():
    _, entries = parse(board('휴무') + [line('쌀밥/김치', 0.86, 0.72)])
    friday = [e for e in entries if e.service_date == date(2026, 10, 9)]
    assert any(e.meal_type == '중식' and e.status == 'no_service' for e in friday)
    assert any(e.meal_type == '조식' and e.status != 'no_service' for e in friday)
    assert all(e.category != '안내' for e in friday)


def test_horizontal_fragments_with_slightly_different_heights_keep_reading_order():
    _, entries = parse(board('')[:-1] + [
        line('한', 0.86, 0.52, width=0.02),
        line('글', 0.885, 0.524, width=0.02),
        line('날', 0.91, 0.52, width=0.02),
    ])
    friday = [e for e in entries if e.service_date == date(2026, 10, 9)]
    assert len(friday) == 3
    assert all('한글날' in e.menu_text and e.status == 'no_service' for e in friday)
