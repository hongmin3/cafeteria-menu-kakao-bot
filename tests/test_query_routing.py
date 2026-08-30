"""질문을 어디로 보낼지에 대한 규칙.

예전에는 날짜만 알아들으면 나머지를 무시하고 그날 전체 식단을 보여줬다.
그래서 "오늘 커피"에도 세 끼니를 다 보여주며 답한 것처럼 굴었다. 여기서는
(1) 코너 이름으로 끼니를 알 수 있는 경우, (2) 모르는 말이 섞인 경우,
(3) 끼니를 정할 수 없는 경우를 각각 어떻게 처리하는지 고정한다.
"""
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from menu_bot.db import MenuDB
from menu_bot.models import MenuEntry
from menu_bot.query import (
    HELP_TEXT,
    answer,
    looks_like_menu_query,
    parse_query,
    query_issue,
    unknown_terms,
)


# 2026-08-21은 금요일. 이번 주는 08-17(월)~08-21(금).
NOW = datetime(2026, 8, 21, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))


@pytest.fixture
def db(tmp_path: Path):
    database = MenuDB(tmp_path / "menus.db")
    rows = []
    for offset, day in enumerate([date(2026, 8, 17 + i) for i in range(5)]):
        rows += [
            MenuEntry(day, "뷰웍스", "조식", "일반식", f"조식일반{offset}", source_post_id="p"),
            MenuEntry(day, "뷰웍스", "조식", "간편식", f"조식간편{offset}", source_post_id="p"),
            MenuEntry(day, "뷰웍스", "조식", "PLUS 코너", "숭늉", source_post_id="p"),
            MenuEntry(day, "뷰웍스", "중식", "일반식", f"중식일반{offset}", source_post_id="p"),
            MenuEntry(day, "뷰웍스", "중식", "건강식", f"중식건강{offset}", source_post_id="p"),
            MenuEntry(day, "뷰웍스", "석식", "일반식", f"석식일반{offset}", source_post_id="p"),
        ]
    database.replace_entries("p", rows)
    yield database
    database.close()


def meals_in(text: str) -> list[str]:
    return [line.strip("[]") for line in text.split("\n") if line.startswith("[")]


def is_help(text: str) -> bool:
    return HELP_TEXT in text


# ── 코너 이름으로 끼니 알아내기 ───────────────────────────────
# 1년치(게시물 72개·이미지 168장) 전수 파싱 결과, 간편식은 조식에만 133회,
# 건강식은 중식에만 127회 나오고 다른 끼니에는 한 번도 없었다.
@pytest.mark.parametrize(
    ("utterance", "expected_day", "expected_meal"),
    [
        ("간편식", "2026-08-21", "조식"),
        ("오늘 간편식", "2026-08-21", "조식"),
        ("간편식 뭐야", "2026-08-21", "조식"),
        ("금요일 간편식", "2026-08-21", "조식"),
        ("월요일 간편식", "2026-08-17", "조식"),
        ("내일 간편식", "2026-08-22", "조식"),
        ("8/19 간편식", "2026-08-19", "조식"),
        ("건강식", "2026-08-21", "중식"),
        ("오늘 건강식", "2026-08-21", "중식"),
        ("수요일 건강식", "2026-08-19", "중식"),
        ("평촌 건강식", "2026-08-21", "중식"),
    ],
)
def test_category_implies_its_meal(utterance: str, expected_day: str, expected_meal: str):
    parsed = parse_query(utterance, NOW)
    assert parsed.day.isoformat() == expected_day
    assert parsed.meal_type == expected_meal


@pytest.mark.parametrize(
    ("utterance", "expected_meal"),
    [("오늘 간편식", "조식"), ("간편식", "조식"), ("건강식", "중식"), ("금요일 건강식", "중식")],
)
def test_category_answer_shows_only_that_meal(db, utterance: str, expected_meal: str):
    result = answer(db, utterance, "Asia/Seoul", now=NOW)
    assert meals_in(result) == [expected_meal]
    assert not is_help(result)


@pytest.mark.parametrize("utterance", ["점심 간편식", "저녁 간편식", "아침 건강식", "석식 건강식"])
def test_category_conflicting_with_meal_is_explained(db, utterance: str):
    """‘점심 간편식’처럼 코너와 끼니가 어긋나면 임의로 고르지 않는다."""
    result = answer(db, utterance, "Asia/Seoul", now=NOW)
    assert "에만 나와요" in result
    assert not result.startswith("🍽")


def test_two_categories_ask_for_one(db):
    result = answer(db, "간편식 건강식", "Asia/Seoul", now=NOW)
    assert "코너를 하나만" in result


@pytest.mark.parametrize("utterance", ["일반식", "오늘 일반식", "PLUS", "plus", "공통", "플러스", "금요일 일반식"])
def test_ambiguous_category_asks_for_meal(db, utterance: str):
    """일반식(1026회)과 PLUS 코너(445회)는 세 끼니에 모두 나와 끼니를 고를 수 없다."""
    result = answer(db, utterance, "Asia/Seoul", now=NOW)
    assert "끼니를 알려주셔야" in result
    assert not result.startswith("🍽")


@pytest.mark.parametrize(
    ("utterance", "expected_meal"),
    [("점심 일반식", "중식"), ("아침 일반식", "조식"), ("저녁 PLUS", "석식")],
)
def test_ambiguous_category_with_meal_is_answered(db, utterance: str, expected_meal: str):
    result = answer(db, utterance, "Asia/Seoul", now=NOW)
    assert meals_in(result) == [expected_meal]


# ── 모르는 말이 섞였을 때 ─────────────────────────────────────
@pytest.mark.parametrize(
    ("utterance", "expected_term"),
    [
        ("오늘 커피", "커피"),
        ("오늘 짜장면 나와?", "짜장면"),
        ("오늘 삼각김밥 있어?", "삼각김밥"),      # ‘밥’이 조사로 잘려나가면 안 된다
        ("금요일 치킨", "치킨"),
        ("점심 파스타 있나요", "파스타"),
        ("내일 아침 계란", "계란"),
        ("오늘 탕수육 먹고싶다", "탕수육"),
        ("월요일 초밥 뭐야", "초밥"),
    ],
)
def test_unknown_word_gets_help_with_the_word_quoted(db, utterance: str, expected_term: str):
    assert expected_term in unknown_terms(utterance)
    result = answer(db, utterance, "Asia/Seoul", now=NOW)
    assert is_help(result)
    assert f"‘{expected_term}’" in result
    assert not result.startswith("🍽")


@pytest.mark.parametrize(
    "utterance",
    # 예전부터 받아 온 표현들. 여기서 "모르는 말"로 오판하면 회귀다.
    ["오늘 점심", "아침", "점심", "저녁", "금요일", "금요일 점심", "내일 저녁", "모레 아침",
     "오늘 뭐먹어", "밥 뭐야", "오늘메뉴", "금주 메뉴", "낼점심", "금욜 저녁", "점심머야?",
     "목요일, 점심!", "평촌점심", "월", "화", "수", "목", "금", "8/19 점심", "8월 19일 점심",
     "오늘 식단", "식단표", "점심 알려줘", "오늘 저녁 메뉴 보여줘", "수요일 아침 뭐 나와",
     "간편식", "건강식", "오늘 간편식"],
)
def test_supported_phrasings_have_no_unknown_terms(utterance: str):
    assert unknown_terms(utterance) == []


@pytest.mark.parametrize(
    "utterance",
    ["오늘 점심", "금요일", "아침", "8/19 점심", "간편식", "건강식", "오늘 뭐먹어", "평촌점심"],
)
def test_supported_phrasings_return_a_menu(db, utterance: str):
    result = answer(db, utterance, "Asia/Seoul", now=NOW)
    assert result.startswith("🍽"), result


def test_multiple_unknown_words_are_all_quoted(db):
    result = answer(db, "오늘 커피랑 케이크", "Asia/Seoul", now=NOW)
    assert is_help(result)
    assert "‘커피랑’" in result or "‘커피’" in result


# ── 기존 안내들이 그대로인지 ─────────────────────────────────
@pytest.mark.parametrize(
    ("utterance", "expected_part"),
    [
        ("다음주 월요일 점심", "다음 주 식단은 제공하지 않아요"),
        ("지난주 월요일", "지난 주 식단은 제공하지 않아요"),
        ("다다음주 월요일", "다다음 주 식단은 제공하지 않아요"),
        ("오늘 내일 점심", "날짜를 하나만"),
        ("월 화 점심", "요일을 하나만"),
        ("아침 점심", "끼니를 하나만"),
        ("이번주 점심", "요일을 함께"),
        ("2월 30일 점심", "날짜를 확인"),
    ],
)
def test_existing_guidance_is_unchanged(db, utterance: str, expected_part: str):
    result = answer(db, utterance, "Asia/Seoul", now=NOW)
    assert expected_part in result


@pytest.mark.parametrize("utterance", ["토", "일", "토요일", "일요일 점심", "주말"])
def test_weekend_is_still_reported_closed(db, utterance: str):
    result = answer(db, utterance, "Asia/Seoul", now=NOW)
    assert "운영하지 않습니다" in result


def test_missing_day_reports_not_uploaded(db):
    """데이터가 없는 날은 있는 척하지 않는다."""
    result = answer(db, "8월 28일 점심", "Asia/Seoul", now=NOW)
    assert "이번 주 식단만" in result or "업로드되지 않았습니다" in result


# ── 식단 질문으로 받아줄지(카카오 1차 관문) ──────────────────
@pytest.mark.parametrize(
    "utterance",
    ["간편식", "건강식", "일반식", "PLUS", "플러스", "오늘 커피", "금요일 치킨",
     "오늘 뭐먹어", "밥 뭐야", "점심", "월"],
)
def test_gate_accepts_menu_shaped_questions(utterance: str):
    assert looks_like_menu_query(utterance)


@pytest.mark.parametrize("utterance", ["asdf", "배고프다아아", "ㅎㅇ", "아무말", "ㅋㅋㅋ", "고마워요"])
def test_gate_rejects_non_menu_chatter(utterance: str):
    assert not looks_like_menu_query(utterance)


# ── 사용방법 안내문 ──────────────────────────────────────────
def test_help_text_fits_one_kakao_bubble():
    assert len(HELP_TEXT) < 1000


@pytest.mark.parametrize(
    "fragment",
    ["금요일 점심", "간편식", "건강식", "조식", "중식", "석식", "주말", "사용방법", "8/25 점심"],
)
def test_help_text_explains_each_supported_form(fragment: str):
    assert fragment in HELP_TEXT


def test_help_text_promotes_today_meal_buttons():
    assert "입력하지 않아도 오늘 식단" in HELP_TEXT
    assert "오늘의 아침" in HELP_TEXT
    assert "오늘의 점심" in HELP_TEXT
    assert "오늘의 저녁" in HELP_TEXT


def test_help_text_stays_one_bubble_when_prefixed():
    """카카오 응답은 '\\n\\n[' 를 기준으로 말풍선을 나눈다. 안내문이 쪼개지면 안 된다."""
    from menu_bot.web import kakao_response

    response = kakao_response("‘커피’(은)는 제가 알아듣지 못했어요. 😅\n\n" + HELP_TEXT)
    assert len(response["template"]["outputs"]) == 1
    assert "…메뉴가 길어" not in response["template"]["outputs"][0]["simpleText"]["text"]


# ── 지점 게시글만 올라온 주차 ────────────────────────────────
@pytest.fixture
def sites_db(tmp_path: Path):
    """뷰웍스 게시글 없이 [안양]·[화성] 게시글만 올라온 주차(2026-08-24 실제 상황).

    두 지점 식단은 42칸 중 31칸이 같고, 진짜 차이는 조식 미운영 요일뿐이다.
    """
    database = MenuDB(tmp_path / "menus.db")
    monday, tuesday = date(2026, 8, 17), date(2026, 8, 18)
    rows = []
    for site in ("안양", "화성"):
        # 월요일 중식은 두 지점이 같다.
        rows.append(MenuEntry(monday, site, "중식", "일반식", "제육볶음 · 콩나물국",
                              source_post_id=site))
        rows.append(MenuEntry(monday, site, "중식", "PLUS 코너", "숭늉", source_post_id=site))
    # 화요일 조식만 갈린다: 안양 미운영, 화성 운영.
    rows.append(MenuEntry(tuesday, "안양", "조식", "안내", "조식 미운영",
                          status="no_service", source_post_id="안양"))
    rows.append(MenuEntry(tuesday, "화성", "조식", "일반식", "*볶음밥DAY* · 참치김치볶음밥",
                          status="special", source_post_id="화성"))
    rows.append(MenuEntry(tuesday, "화성", "조식", "PLUS 코너", "숭늉", source_post_id="화성"))
    database.replace_entries("sites", rows)
    yield database
    database.close()


def test_identical_site_menus_are_merged_without_labels(sites_db):
    """두 사업장이 같은 끼니는 사업장을 밝히지 않고 한 번만 보여준다."""
    result = answer(sites_db, "월요일 점심", "Asia/Seoul", now=NOW)
    assert "제육볶음" in result
    for site in ("안양", "화성", "뷰웍스", "사업장"):
        assert site not in result, result
    assert result.count("제육볶음") == 1


def test_differing_meal_shows_both_sites(sites_db):
    """한쪽만 쉬는 끼니는 두 사업장을 나란히 보여준다.

    사업장을 나눠 올렸다는 것 자체가 그 주에 운영 예외가 있다는 뜻이고,
    사용자는 둘 중 한 곳에 있다. 한쪽만 골라 보여주면 나머지 절반이 닫힌
    식당으로 가게 된다.
    """
    result = answer(sites_db, "화요일 아침", "Asia/Seoul", now=NOW)
    assert "〔안양〕" in result and "조식 미운영" in result
    assert "〔화성〕" in result and "볶음밥DAY" in result
    # 다만 "뷰웍스 식단표가 없어서…" 같은 사정 설명은 넣지 않는다.
    assert "뷰웍스" not in result


def test_query_issue_uses_configured_locations():
    """사업장 이름은 설정값(POST_PREFIXES)에서 온다."""
    assert query_issue("안양점심", NOW.date(), ("안양",)) is None
    assert "알아듣지 못했어요" in (query_issue("안양점심", NOW.date(), ("뷰웍스",)) or "")
