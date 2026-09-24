"""셀 상태 분류(미운영 · 특식 · 일반) 회귀 검사.

Validates: REQ-PARSE-002

SPEC 11절 TEST-PARSE-002가 이 파일이다. 그룹웨어도 OCR provider도 타지 않고, OCR 줄을
직접 만들어 파서만 검사하므로 어느 플랫폼에서든 같은 결과가 나온다. 저장된 OCR 캐시는 쓰지
않는다(캐시를 저장소에 둘지는 SPEC 14절에 미정으로 남아 있다).

fixture 좌표 규약은 `tests/test_corrections.py::test_parser_applies_corrections`와 같다.
"""

from datetime import date

import pytest

from menu_bot.models import SourcePost
from menu_bot.parser import parse_ocr_lines

IMAGE = "http://example.invalid/menu.png"


def line(text, x, y, width=0.1, height=0.02, confidence=0.9):
    return {"text": text, "x": x, "y": y, "width": width, "height": height,
            "confidence": confidence}


def scaffold():
    """실제 식단 이미지의 왼쪽 열 — 끼니 이름과 코너 이름.

    파서는 끼니 라벨이 하나도 없으면 빈 결과를 돌려준다(`if not meal_labels: return []`).
    실제 이미지에는 항상 있으므로, 이 줄들이 없는 fixture는 이미지가 아니라 파서의
    사전 조건을 검사하게 된다.
    """
    return [
        line("조식", 0.05, 0.70), line("일반식", 0.05, 0.68),
        line("중식", 0.05, 0.50), line("일반식", 0.05, 0.48),
        line("석식", 0.05, 0.30), line("일반식", 0.05, 0.28),
    ]


def post():
    return SourcePost(post_id="p", title="[뷰웍스] 2026-08-24 ~ 08-28",
                      location="뷰웍스", start_date=date(2026, 8, 24))


def statuses(entries, *, meal=None, day=None):
    return {e.status for e in entries
            if (meal is None or e.meal_type == meal)
            and (day is None or e.service_date == day)}


def by_meal(entries, day):
    out = {}
    for e in entries:
        if e.service_date == day:
            out.setdefault(e.meal_type, set()).add(e.status)
    return out


def test_whole_day_closure_marks_all_three_meals(monkeypatch):
    """하루 전체를 뜻하는 문구는 조식·중식·석식 세 끼 모두에 미운영로 들어간다."""
    import menu_bot.corrections as corrections
    monkeypatch.setattr(corrections, "_cached_vocabulary", {})
    entries = parse_ocr_lines(post(), IMAGE, scaffold() + [
        line("8/24", 0.30, 0.90),
        line("대체휴무", 0.30, 0.60),
    ])
    day = date(2026, 8, 24)
    meals = by_meal(entries, day)
    assert set(meals) == {"조식", "중식", "석식"}, meals
    for meal, values in meals.items():
        assert values == {"no_service"}, (meal, values)


@pytest.mark.parametrize("phrase", ["공휴일", "전사휴무"])
def test_other_whole_day_phrases_close_the_whole_day(phrase, monkeypatch):
    import menu_bot.corrections as corrections
    monkeypatch.setattr(corrections, "_cached_vocabulary", {})
    entries = parse_ocr_lines(post(), IMAGE, scaffold() + [
        line("8/25", 0.30, 0.90),
        line(phrase, 0.30, 0.60),
    ])
    meals = by_meal(entries, date(2026, 8, 25))
    assert set(meals) == {"조식", "중식", "석식"}, (phrase, meals)
    assert all(v == {"no_service"} for v in meals.values()), (phrase, meals)


def test_named_meal_closure_touches_only_that_meal(monkeypatch):
    """`조식 미제공`처럼 끼니가 명시된 문구는 그 끼니에만 들어간다.

    이 단언이 이 검사의 핵심이다 — 전일 휴무와 끼니별 휴무를 같게 처리하면 하루치 식단이
    통째로 사라지고, 사용자는 그 차이를 응답에서만 본다.
    """
    import menu_bot.corrections as corrections
    monkeypatch.setattr(corrections, "_cached_vocabulary", {})
    entries = parse_ocr_lines(post(), IMAGE, scaffold() + [
        line("8/26", 0.30, 0.90),
        line("조식 미제공", 0.30, 0.60),
    ])
    meals = by_meal(entries, date(2026, 8, 26))
    assert meals == {"조식": {"no_service"}}, meals


def test_special_meal_is_marked_special_not_closed(monkeypatch):
    """특식은 미운영이 아니다. 두 상태를 섞으면 있는 식단을 없다고 답한다."""
    import menu_bot.corrections as corrections
    monkeypatch.setattr(corrections, "_cached_vocabulary", {})
    entries = parse_ocr_lines(post(), IMAGE, scaffold() + [
        line("8/27", 0.30, 0.90),
        line("영양사 픽 스테이크덮밥", 0.30, 0.50),
    ])
    values = statuses(entries, day=date(2026, 8, 27))
    assert values == {"special"}, values


def test_ordinary_menu_stays_normal(monkeypatch):
    """감도: 평범한 식단이 normal이어야 위 세 검사가 의미를 갖는다.

    이 단언이 없으면 분류기가 무엇이든 no_service로 답해도 위 검사들은 통과한다.
    """
    import menu_bot.corrections as corrections
    monkeypatch.setattr(corrections, "_cached_vocabulary", {})
    entries = parse_ocr_lines(post(), IMAGE, scaffold() + [
        line("8/28", 0.30, 0.90),
        line("제육볶음", 0.30, 0.50),
    ])
    values = statuses(entries, day=date(2026, 8, 28))
    assert values == {"normal"}, values
