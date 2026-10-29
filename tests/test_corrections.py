import json
from datetime import date
from pathlib import Path

import pytest

from menu_bot.corrections import (
    MIN_VOCAB_COUNT,
    build_vocabulary,
    clean_items,
    correct_item,
    is_noise,
    is_promotional_noise,
    load_vocabulary,
)


# ── 노이즈 판정 ───────────────────────────────────────────────
# 1년치 고유 항목 2211개 중 한글이 없는 항목은 15개였고 전부 장식 문구·로고
# 조각이었다. PaddleOCR이 장식 서체 줄에서 끼워 넣는 조각도 같은 모양이다.
@pytest.mark.parametrize(
    "item",
    ["004", "oo", "MW", "AL", "1R", "-11", "*:", "()", "•", "O.", "Happy New year",
     "GOPIZZA", "0ery Chirstas", "  ", "123", "I", "<", "5 3 L"],
)
def test_noise_is_dropped(item: str):
    assert is_noise(item) or not item.strip()
    assert correct_item(item) is None


@pytest.mark.parametrize(
    "item",
    [
        "천상현 셰프", "천상현 세프", "천상현세프", "이연복 쉐프", "백종원 CHEF",
        "오늘의 셰프 천상현", "현대그콘푸드", "HYUNDAI GREEN FOOD",
        "브랜드콜라보DAY", "BRAND COLLABORATION", "콜라보 DAY_호우섬",
        "여름휴가 맛집_전주편", "2호선맛집탐방! '신림", "다함께차차차 이벤트",
        "후식이벤트DAY", "**말복 특식 DAY**", "VIEWORKS 12월 특식",
    ],
)
def test_promotion_graphics_are_dropped(item: str):
    """인물·브랜드·행사가 바뀌어도 홍보 배너를 메뉴로 노출하지 않는다."""
    assert is_promotional_noise(item)
    assert is_noise(item)
    assert correct_item(item) is None


def test_person_name_is_not_hardcoded_as_noise():
    """역할 표기 없는 일반 인명 자체를 임의로 지우지 않는다."""
    assert not is_promotional_noise("천상현")


@pytest.mark.parametrize("item", ["풍요로운", "너4", "보내세요", "행복한 명절 되세요"])
def test_holiday_greeting_banner_is_dropped(item: str):
    """2026-09-24(추석 연휴 직전) 실제 서버 OCR로 확인된 명절 인사 배너 조각.

    조식 일반식·간편식, 중식 일반식 칸에 실제 메뉴 대신 인사말이 섞여
    들어왔다. "한가위"는 신뢰도 0.43으로 "너4"까지 오인식됐다.
    """
    assert is_promotional_noise(item)
    assert is_noise(item)
    assert correct_item(item) is None


@pytest.mark.parametrize("item", ["송편", "한가위 송편", "정월대보름 쇠고기무국"])
def test_real_holiday_food_names_are_kept(item: str):
    """명절 이름이 붙은 실제 음식은 인사 배너 규칙에 걸리지 않아야 한다."""
    assert not is_promotional_noise(item)
    assert correct_item(item) == item


@pytest.mark.parametrize(
    "item",
    ["멕시칸치킨플래터 특식", "말복삼계탕", "전주식콩나물국밥", "호우섬우육탕면"],
)
def test_real_special_food_names_are_kept(item: str):
    assert not is_promotional_noise(item)
    assert correct_item(item) == item


@pytest.mark.parametrize(
    "item",
    ["숭늉", "쌀밥", "*라면DAY*", "돈까스*소스", "쌀밥/ 배추김치", "PLUS 코너 현미밥",
     "#여름아부탁해_입맛아 돌아와~!", "모밀한판*무/와사비/대파", "그린샐러드*드레싱",
     "영양사픽 여름 최고강추메뉴!", "미역국"],
)
def test_real_menu_items_survive(item: str):
    assert not is_noise(item)
    assert correct_item(item) == item


# ── 표기 교정(고정 목록) ──────────────────────────────────────
@pytest.mark.parametrize(
    ("wrong", "right"),
    [
        # 1년치 466회로 최다 항목인데 세 갈래로 틀린다.
        ("숭능", "숭늉"),
        ("숭융", "숭늉"),
        ("승능", "숭늉"),
        ("승늉", "숭늉"),
        ("숭늄", "숭늉"),
        ("짝두기", "깍두기"),
        ("쌀밥/짝두기", "쌀밥/깍두기"),
        ("레몬크림치킨깥풍기", "레몬크림치킨깐풍기"),
        ("계란듬뿐모닝샌드위치*곤약젤리*음료", "계란듬뿍모닝샌드위치*곤약젤리*음료"),
        ("앵콜!마늘종비빙밥", "앵콜!마늘종비빔밥"),
        ("청경채걸절이", "청경채겉절이"),
        ("애기새송이볶음/부추걸절이", "애기새송이볶음/부추겉절이"),
        ("콩고물꼬배기", "콩고물꽈배기"),
        ("꼬리고추감자조림", "꽈리고추감자조림"),
        ("숫불제육볶음", "숯불제육볶음"),
        ("두부릇무침", "두부톳무침"),
        ("깨잎무쌈/콩나물국", "깻잎무쌈/콩나물국"),
    ],
)
def test_known_misreadings_are_fixed(wrong: str, right: str):
    assert correct_item(wrong) == right


@pytest.mark.parametrize(
    ("wrong", "right"),
    # 1년치 전수 조사에서 가장 많았던 오인식 묶음: 장(醬)을 정·자·창·작·당·중·짱·잠으로 읽는다.
    [
        ("열무된자국", "열무된장국"),
        ("시금치된당국", "시금치된장국"),
        ("된정찌개", "된장찌개"),
        ("배추된정나물", "배추된장나물"),
        ("봄동된자국", "봄동된장국"),
        ("아욱된자국", "아욱된장국"),
        ("북어해자국", "북어해장국"),
        ("북어해당국", "북어해장국"),
        ("양해당국", "양해장국"),
        ("고추정찌개", "고추장찌개"),
        ("호박고추정찌개", "호박고추장찌개"),
        ("상추쌈&쌈정", "상추쌈&쌈장"),
        ("채소스틱&쌈잠", "채소스틱&쌈장"),
        ("양파적채쌈정무침", "양파적채쌈장무침"),
        ("순두부백탕*양념작", "순두부백탕*양념장"),
        ("순두부백탕*양념정", "순두부백탕*양념장"),
        ("순두부백탕*양념창", "순두부백탕*양념장"),
        ("김구이*간정", "김구이*간장"),
        ("녹두빈대떡&양파간정", "녹두빈대떡&양파간장"),
        ("김말이튀김*초간당", "김말이튀김*초간장"),
        ("순살간자찜닭", "순살간장찜닭"),
        ("순살간창찜닭", "순살간장찜닭"),
        ("양파짱아찌", "양파장아찌"),
        ("깐마늘짱아찌", "깐마늘장아찌"),
        ("가쓰오짱국/배추김치", "가쓰오장국/배추김치"),
        ("우동자국", "우동장국"),
        ("팽이중국", "팽이장국"),
        ("미소자국", "미소장국"),
        ("메추리알자조림", "메추리알장조림"),
        ("브로콜리숙회&초정", "브로콜리숙회&초장"),
    ],
)
def test_jang_family_misreadings_are_fixed(wrong: str, right: str):
    assert correct_item(wrong) == right


@pytest.mark.parametrize(
    ("wrong", "right"),
    [
        ("씰밥", "쌀밥"),
        ("씰밥/ 깍두기", "쌀밥/ 깍두기"),
        ("귀리기창밥", "귀리기장밥"),
        ("돗나물무침", "돌나물무침"),
        ("알새우집", "알새우칩"),
        ("삼감김밥*몬스터크랩*컵라면", "삼각김밥*몬스터크랩*컵라면"),
        ("부주잡채", "부추잡채"),
        ("참치후실리샐러드", "참치푸실리샐러드"),
        ("새싹삼삼계팅", "새싹삼삼계탕"),
        ("풀무원푸드앤걸처", "풀무원푸드앤컬처"),
        ("영양사픽 여름 최고강주메뉴!", "영양사픽 여름 최고강추메뉴!"),
        ("미슷가루", "미숫가루"),
        ("[뜻배기]순두부찌개", "[뚝배기]순두부찌개"),
        ("미역출기볶음", "미역줄기볶음"),
        ("조랭이떠국", "조랭이떡국"),
        ("베이그에그마요샐러드볼", "베이컨에그마요샐러드볼"),
        ("핫도그*케찹", "핫도그*케첩"),
        ("불닭크로켓*케접", "불닭크로켓*케첩"),
        ("모듬콩조림", "모둠콩조림"),
    ],
)
def test_other_year_long_misreadings_are_fixed(wrong: str, right: str):
    assert correct_item(wrong) == right


@pytest.mark.parametrize(
    "item",
    # (1) PaddleOCR이 더 정확했던 표기 (2) 교정 규칙과 글자가 겹치지만 멀쩡한 실제 메뉴.
    # `자조림`을 넓게 잡으면 감자조림·완자조림이 깨지므로 앞 글자를 함께 고정했다.
    [
        "북어해장국", "매운가쓰오장국", "부추잡채", "영양사픽 여름 최고강추메뉴!", "쌀밥/배추김치",
        "감자조림", "알감자조림", "비엔나감자조림", "완자조림", "베이컨크림알감자조림",
        "뼈없는순살감자탕", "시래기순살감자탕", "감자수제비국", "감자된장찌개",
        "에그함박스테이크정식", "근본!집밥정식", "쇠고기미역국정식", "바비큐BBQ플래터정식",
        "초생강*락교", "정월대보름 쇠고기무국", "제육볶음", "장조림버터볶음밥",
        "돈육느타리장조림", "계란장조림", "모둠메추리알장조림", "메추리알고추장조림",
        "양파간장초절임", "콩나물표고밥*달래양념간장", "구운김*양념장", "산고추지",
        "중국식오이무침", "얼큰!교동짬뽕", "마늘종지무침", "마늘종볶음",
    ],
)
def test_real_items_are_not_broken_by_the_rules(item: str):
    assert correct_item(item) == item


@pytest.mark.parametrize("item", ["행", "주", "하", "남", "돼", "지", "집", "매", " 매 "])
def test_single_character_fragments_are_dropped(item: str):
    """1년치에서 한 글자 항목 7개는 전부 조각이었다. 두 글자부터는 멀쩡한 메뉴가 많다."""
    assert correct_item(item) is None


@pytest.mark.parametrize("item", ["숭늉", "쌀밥", "잡채", "식혜", "닭죽", "팝콘", "수박", "떡국", "쫄면"])
def test_two_character_menus_survive(item: str):
    assert correct_item(item) == item


@pytest.mark.parametrize(
    ("wrong", "right"),
    [
        ("고줏잎무침", "고춧잎무침"),
        ("홍합탕 · 고줏잎무침", "홍합탕 · 고춧잎무침"),
        ("열무비빔밥*양넘고추장", "열무비빔밥*양념고추장"),
        ("승늄", "숭늉"),
        ("롯나물무침", "톳나물무침"),
    ],
)
def test_this_week_misreadings_are_fixed(wrong: str, right: str):
    """2026-08-24 주차 실제 수집분에서 사용자가 잡아 준 오인식."""
    assert correct_item(wrong) == right


def test_current_thursday_special_is_cleaned_from_real_server_values():
    items = [
        "현대그콘푸드", "천상현 세프", "해물백쌈뽕", "유린기", "유부겨자냉채",
        "짜사이", "천상현세프", "쌀밥/짝두)", "그린샐러드*드레싱",
    ]
    assert clean_items(items) == [
        "해물백짬뽕", "유린기", "유부겨자냉채", "짜사이", "쌀밥/깍두기",
        "그린샐러드*드레싱",
    ]


@pytest.mark.parametrize("item", ["마늘쫑지무침", "마늘쫑볶음", "햄마늘쫑볶음"])
def test_balanced_spelling_variants_are_left_to_the_source(item: str):
    """`마늘쫑`(16회) 대 `마늘종`(9회)처럼 빈도가 비슷하면 원문 표기일 수 있어 손대지 않는다."""
    assert correct_item(item) == item


# ── 어휘집 교정 ───────────────────────────────────────────────
def _vocab(**counts: int) -> dict[str, int]:
    return dict(counts)


def test_vocabulary_fixes_single_character_error():
    vocabulary = {"미역국": MIN_VOCAB_COUNT, "쌀밥": 200}
    assert correct_item("미역굽", vocabulary) == "미역국"


def test_vocabulary_ignores_rare_entries():
    """어휘집 자체에도 오인식이 섞여 있다.

    오인식은 보통 한두 번 나오고 실제 메뉴 이름은 여러 번 반복되므로, 등장
    횟수가 하한에 못 미치는 항목은 교정 후보로 쓰지 않는다. 실제로 어휘집에는
    Apple Vision이 잘못 읽은 '부주잡채'(1회)가 들어 있는데, 이것 때문에
    올바른 '부추잡채'가 되돌려지면 안 된다.
    """
    vocabulary = {"부주잡채": 1}
    assert correct_item("부추잡채", vocabulary) == "부추잡채"


def test_vocabulary_leaves_ambiguous_items_alone():
    """한 글자만 다른 후보가 둘 이상이면 손대지 않는다."""
    vocabulary = {"쌀밥": 200, "쌈밥": 50}
    assert correct_item("쌐밥", vocabulary) == "쌐밥"


def test_vocabulary_requires_same_length():
    vocabulary = {"미역국": 100}
    assert correct_item("미역", vocabulary) == "미역"
    assert correct_item("미역국물", vocabulary) == "미역국물"


def test_vocabulary_keeps_known_items_untouched():
    vocabulary = {"쌀밥": 200, "쌈밥": 50}
    assert correct_item("쌈밥", vocabulary) == "쌈밥"


def test_substitution_runs_before_vocabulary():
    """고정 목록으로 이미 바로잡힌 값을 어휘집이 다시 흔들지 않아야 한다."""
    vocabulary = {"숭늉": 466, "숭늄": 400}
    assert correct_item("숭능", vocabulary) == "숭늉"


# ── 항목 목록 처리 ────────────────────────────────────────────
def test_clean_items_drops_noise_and_dedupes():
    items = ["우삼겹마라유부떡볶이", "004", "핫도그*케첩", "oo", "핫도그*케첩", "단무지"]
    assert clean_items(items) == ["우삼겹마라유부떡볶이", "핫도그*케첩", "단무지"]


def test_clean_items_dedupes_after_correction():
    """교정 결과가 같아지면 한 번만 남는다(같은 셀에 숭능/숭융이 함께 잡힐 때)."""
    assert clean_items(["숭능", "숭융"]) == ["숭늉"]


def test_clean_items_keeps_order():
    items = ["쌀밥", "배추김치", "미역국"]
    assert clean_items(items) == items


# ── 어휘집 파일 입출력 ────────────────────────────────────────
def test_build_and_load_vocabulary(tmp_path: Path):
    path = tmp_path / "vocab.json"
    vocabulary = build_vocabulary(["숭늉", "숭늉", "쌀밥"])
    assert vocabulary == {"숭늉": 2, "쌀밥": 1}
    path.write_text(json.dumps(vocabulary, ensure_ascii=False), encoding="utf-8")
    assert load_vocabulary(path) == vocabulary


def test_missing_vocabulary_is_not_an_error(tmp_path: Path):
    assert load_vocabulary(tmp_path / "없는파일.json") == {}


def test_corrupt_vocabulary_is_not_an_error(tmp_path: Path):
    path = tmp_path / "vocab.json"
    path.write_text("{ 깨진 json", encoding="utf-8")
    assert load_vocabulary(path) == {}


def test_legacy_list_vocabulary_is_accepted(tmp_path: Path):
    """예전 형식(항목 목록)도 읽어준다. 횟수를 모르니 하한은 통과시킨다."""
    path = tmp_path / "vocab.json"
    path.write_text(json.dumps(["미역국"], ensure_ascii=False), encoding="utf-8")
    vocabulary = load_vocabulary(path)
    assert vocabulary["미역국"] >= MIN_VOCAB_COUNT
    assert correct_item("미역굽", vocabulary) == "미역국"


# ── 파서까지 이어지는지 ───────────────────────────────────────
def test_parser_applies_corrections(monkeypatch):
    """파서를 통과한 menu_text에 교정과 노이즈 제거가 반영돼야 한다."""
    import menu_bot.corrections as corrections
    from menu_bot.models import SourcePost
    from menu_bot.parser import parse_ocr_lines

    monkeypatch.setattr(corrections, "_cached_vocabulary", {})

    def line(text, x, y, width=0.1, height=0.02, confidence=0.9):
        return {"text": text, "x": x, "y": y, "width": width, "height": height,
                "confidence": confidence}

    lines = [
        line("8/24", 0.30, 0.90),                 # 날짜 헤더
        line("조식", 0.05, 0.60),                  # 끼니
        line("일반식", 0.05, 0.62),                 # 코너
        line("PLUS", 0.05, 0.40),
        line("쌀밥/짝두기", 0.30, 0.58),             # 오인식
        line("천상현 셰프", 0.30, 0.59),             # 위쪽 가로 특식 홍보 배너
        line("천상현 셰프", 0.33, 0.53),             # 오른쪽 아래 명패
        line("브랜드콜라보DAY", 0.30, 0.57),         # 1년치에 반복된 행사 제목
        line("004", 0.30, 0.55),                  # 노이즈
        line("숭능", 0.30, 0.38),                  # 오인식
    ]
    post = SourcePost(post_id="p", title="[뷰웍스] 2026-08-24 ~ 08-28",
                      location="뷰웍스", start_date=date(2026, 8, 24))
    entries = parse_ocr_lines(post, "http://example.com/a.png", lines)
    texts = {(e.meal_type, e.category): e.menu_text for e in entries}
    joined = " | ".join(texts.values())
    assert "깍두기" in joined and "짝두기" not in joined
    assert "숭늉" in joined and "숭능" not in joined
    assert "004" not in joined
    assert "천상현" not in joined and "셰프" not in joined
    assert "브랜드콜라보" not in joined
    general = next(entry for entry in entries if entry.category == "일반식")
    assert general.status == "special"


def test_holiday_greeting_banner_does_not_become_a_fake_menu_day(monkeypatch):
    """2026-09-24(추석 연휴 직전 목요일) 실제 사고 재현.

    `[뷰웍스] 2026-09-21 ~ 2026-09-25` 게시물 이미지 한 장(원본:
    data/images/09161979294653b39319ba06.png, 운영 서버에서 직접 확인)에는
    목요일 칸에 실제 메뉴 대신 명절 인사 배너가 겹쳐 있다. 고치기 전에는
    이 좌표 그대로 파서를 통과시키면 09/24에 "풍요로운"(조식 일반식)·
    "너4"(조식 간편식, "한가위"의 심한 오인식)·"보내세요"(중식 일반식)가
    가짜 메뉴 항목으로 저장됐다. 09/23·09/25는 원래 이미지에도 내용이 없어
    실제로 빈 채로 남아야 한다.
    """
    import menu_bot.corrections as corrections
    from menu_bot.models import SourcePost
    from menu_bot.parser import parse_ocr_lines

    monkeypatch.setattr(corrections, "_cached_vocabulary", {})

    lines = [
        {"text": "Weekly", "confidence": 0.9988839626312256, "x": 0.28914919852034526, "y": 0.9061135371179039, "width": 0.18680641183723798, "height": 0.09388646288209607},
        {"text": "menu", "confidence": 0.9981221556663513, "x": 0.4882860665844636, "y": 0.9268558951965066, "width": 0.14118372379778052, "height": 0.056768558951965066},
        {"text": "뷰웍스", "confidence": 0.9813935160636902, "x": 0.6381011097410604, "y": 0.925764192139738, "width": 0.08631319358816276, "height": 0.05349344978165939},
        {"text": "HYUN", "confidence": 0.9982978105545044, "x": 0.8803945745992602, "y": 0.9508733624454149, "width": 0.056103575832305796, "height": 0.03384279475982533},
        {"text": "G RE EN  FOOD", "confidence": 0.8802316188812256, "x": 0.9001233045622689, "y": 0.9213973799126638, "width": 0.058569667077681874, "height": 0.015283842794759825},
        {"text": "09/21(월)", "confidence": 0.9996505975723267, "x": 0.18372379778051787, "y": 0.8646288209606987, "width": 0.06658446362515413, "height": 0.03275109170305677},
        {"text": "09/22(화)", "confidence": 0.9997840523719788, "x": 0.3563501849568434, "y": 0.8635371179039302, "width": 0.06843403205918619, "height": 0.03384279475982533},
        {"text": "09/23(수)", "confidence": 0.9991559982299805, "x": 0.530209617755857, "y": 0.861353711790393, "width": 0.06781750924784218, "height": 0.03711790393013101},
        {"text": "09/24(목)", "confidence": 0.9997769594192505, "x": 0.7046855733662145, "y": 0.8635371179039302, "width": 0.0659679408138101, "height": 0.03384279475982533},
        {"text": "09/25(금)", "confidence": 0.9992350339889526, "x": 0.8773119605425401, "y": 0.8635371179039302, "width": 0.06781750924784218, "height": 0.03384279475982533},
        {"text": "돈육김치찌개", "confidence": 0.9996728897094727, "x": 0.18557336621454995, "y": 0.8329694323144105, "width": 0.06350184956843404, "height": 0.027292576419213975},
        {"text": "*라면DAY*", "confidence": 0.9991160035133362, "x": 0.36066584463625156, "y": 0.8329694323144106, "width": 0.058569667077681874, "height": 0.02947598253275109},
        {"text": "해물완자조림", "confidence": 0.9966862201690674, "x": 0.18495684340320592, "y": 0.8013100436681223, "width": 0.06350184956843404, "height": 0.026200873362445413},
        {"text": "참깨라면", "confidence": 0.9994816184043884, "x": 0.3680641183723798, "y": 0.8013100436681222, "width": 0.04438964241676942, "height": 0.027292576419213975},
        {"text": "일반식", "confidence": 0.9996792674064636, "x": 0.07274969173859433, "y": 0.7707423580786026, "width": 0.03390875462392109, "height": 0.028384279475982533},
        {"text": "도시락김", "confidence": 0.9987876415252686, "x": 0.19543773119605426, "y": 0.7696506550218342, "width": 0.043773119605425403, "height": 0.026200873362445413},
        {"text": "어묵볶음", "confidence": 0.9992229342460632, "x": 0.3680641183723798, "y": 0.7674672489082969, "width": 0.04438964241676942, "height": 0.03165938864628821},
        {"text": "조식", "confidence": 0.9995326995849609, "x": 0.010480887792848335, "y": 0.7358078602620087, "width": 0.030826140567200986, "height": 0.03384279475982533},
        {"text": "쌀밥", "confidence": 0.99345862865448, "x": 0.20406905055487054, "y": 0.7368995633187774, "width": 0.02651048088779285, "height": 0.03056768558951965},
        {"text": "단무지", "confidence": 0.9996898770332336, "x": 0.37299630086313196, "y": 0.7368995633187774, "width": 0.03390875462392109, "height": 0.02947598253275109},
        {"text": "풍요로운", "confidence": 0.9408910274505615, "x": 0.688039457459926, "y": 0.6834061135371179, "width": 0.09309494451294698, "height": 0.09606986899563319},
        {"text": "깍두기", "confidence": 0.9629416465759277, "x": 0.19852034525277434, "y": 0.7041484716157206, "width": 0.03514180024660912, "height": 0.03384279475982533},
        {"text": "쌀밥/배추김치", "confidence": 0.9991680383682251, "x": 0.3557336621454994, "y": 0.7074235807860262, "width": 0.0690505548705302, "height": 0.026200873362445413},
        {"text": "PLUS코너", "confidence": 0.9932112693786621, "x": 0.06226880394574599, "y": 0.6768558951965066, "width": 0.05363748458692972, "height": 0.02292576419213974},
        {"text": "숭능", "confidence": 0.7155684232711792, "x": 0.20468557336621454, "y": 0.6724890829694323, "width": 0.02466091245376079, "height": 0.03056768558951965},
        {"text": "닭죽", "confidence": 0.9982502460479736, "x": 0.37792848335388407, "y": 0.6724890829694323, "width": 0.025893958076448828, "height": 0.03056768558951965},
        {"text": "너4", "confidence": 0.4289083778858185, "x": 0.6732429099876696, "y": 0.5993449781659389, "width": 0.1381011097410604, "height": 0.09934497816593886},
        {"text": "간편식", "confidence": 0.9998449683189392, "x": 0.07151664611590629, "y": 0.6408296943231441, "width": 0.03390875462392109, "height": 0.028384279475982533},
        {"text": "삼각김밥*반숙란*컵라면", "confidence": 0.9984562993049622, "x": 0.16029593094944514, "y": 0.6430131004366813, "width": 0.11282367447595561, "height": 0.026200873362445413},
        {"text": "핫크리스피핫도그*견과류*음료", "confidence": 0.9969892501831055, "x": 0.3205918618988903, "y": 0.6441048034934497, "width": 0.13933415536374846, "height": 0.02292576419213974},
        {"text": "유니자장면", "confidence": 0.9997395277023315, "x": 0.19112207151664612, "y": 0.6102620087336245, "width": 0.0530209617755857, "height": 0.026200873362445413},
        {"text": "돈육바싹불고기", "confidence": 0.9919099807739258, "x": 0.35450061652281134, "y": 0.6135371179039301, "width": 0.07151664611590629, "height": 0.021834061135371178},
        {"text": "군만두*초간장", "confidence": 0.9997571706771851, "x": 0.18310727496917387, "y": 0.5786026200873362, "width": 0.06720098643649815, "height": 0.027292576419213975},
        {"text": "한식잡채", "confidence": 0.9997246265411377, "x": 0.3686806411837238, "y": 0.5786026200873362, "width": 0.04315659679408138, "height": 0.027292576419213975},
        {"text": "해물짱뽕국", "confidence": 0.9448281526565552, "x": 0.18988902589395806, "y": 0.5469432314410481, "width": 0.05363748458692972, "height": 0.027292576419213975},
        {"text": "부추겉절이", "confidence": 0.9615575671195984, "x": 0.3637484586929716, "y": 0.5469432314410481, "width": 0.05240443896424168, "height": 0.027292576419213975},
        {"text": "보내세요", "confidence": 0.8740538358688354, "x": 0.6750924784217016, "y": 0.48471615720524025, "width": 0.12392108508014797, "height": 0.0982532751091703},
        {"text": "일반식", "confidence": 0.9995307326316833, "x": 0.0721331689272503, "y": 0.5316593886462881, "width": 0.03390875462392109, "height": 0.027292576419213975},
        {"text": "단무지", "confidence": 0.9998641014099121, "x": 0.1997533908754624, "y": 0.5141921397379913, "width": 0.0345252774352651, "height": 0.028384279475982533},
        {"text": "흑미잡곡밥/쌀밥", "confidence": 0.9920769929885864, "x": 0.34956843403205917, "y": 0.5141921397379913, "width": 0.08138101109741061, "height": 0.03275109170305677},
        {"text": "름", "confidence": 0.42589861154556274, "x": 0.7965474722564735, "y": 0.490174672489083, "width": 0.02342786683107275, "height": 0.0425764192139738},
        {"text": "쌀밥", "confidence": 0.9952734708786011, "x": 0.20468557336621454, "y": 0.482532751091703, "width": 0.025893958076448828, "height": 0.02947598253275109},
        {"text": "중식", "confidence": 0.9997343420982361, "x": 0.008631319358816275, "y": 0.4639737991266375, "width": 0.031442663378545004, "height": 0.03820960698689956},
        {"text": "들깨미역국", "confidence": 0.9997259378433228, "x": 0.3643649815043157, "y": 0.4836244541484716, "width": 0.05240443896424168, "height": 0.026200873362445413},
        {"text": "배추김치", "confidence": 0.9997348785400391, "x": 0.19543773119605426, "y": 0.45196506550218335, "width": 0.043773119605425403, "height": 0.026200873362445413},
        {"text": "포기김치", "confidence": 0.9993228912353516, "x": 0.3686806411837238, "y": 0.4541484716157205, "width": 0.04315659679408138, "height": 0.02292576419213974},
        {"text": "그린샐러드*드레싱", "confidence": 0.9997795820236206, "x": 0.17324290998766953, "y": 0.42030567685589526, "width": 0.08754623921085081, "height": 0.02947598253275109},
        {"text": "그린샐러드*드레싱", "confidence": 0.9996746778488159, "x": 0.3477188655980271, "y": 0.4213973799126638, "width": 0.08569667077681874, "height": 0.028384279475982533},
        {"text": "HYUNDAI GREEN FOOD", "confidence": 0.9525379538536072, "x": 0.6418002466091245, "y": 0.3995633187772926, "width": 0.18618988902589395, "height": 0.036026200873362446},
        {"text": "PLUS코너", "confidence": 0.9988055229187012, "x": 0.06103575832305795, "y": 0.39082969432314413, "width": 0.054870530209617754, "height": 0.026200873362445413},
        {"text": "꽃빵연유튀김", "confidence": 0.9958023428916931, "x": 0.1843403205918619, "y": 0.3864628820960699, "width": 0.06473489519112208, "height": 0.03056768558951965},
        {"text": "송편", "confidence": 0.9987276792526245, "x": 0.37792848335388407, "y": 0.3864628820960699, "width": 0.02527743526510481, "height": 0.03056768558951965},
        {"text": "현미밥", "confidence": 0.9986462593078613, "x": 0.2003699136868064, "y": 0.3548034934497817, "width": 0.03390875462392109, "height": 0.03275109170305677},
        {"text": "현미밥", "confidence": 0.998885452747345, "x": 0.37422934648581996, "y": 0.3569868995633188, "width": 0.03329223181257707, "height": 0.027292576419213975},
        {"text": "건강식", "confidence": 0.9997758865356445, "x": 0.07151664611590629, "y": 0.32096069868995636, "width": 0.0345252774352651, "height": 0.03275109170305677},
        {"text": "참치푸실리샐러드", "confidence": 0.9995759725570679, "x": 0.17570900123304561, "y": 0.32641921397379914, "width": 0.08076448828606658, "height": 0.02292576419213974},
        {"text": "새우파스타샐러드", "confidence": 0.9911922812461853, "x": 0.34956843403205917, "y": 0.32641921397379914, "width": 0.08014796547472257, "height": 0.02292576419213974},
        {"text": "에비동(새우튀김덮밥)", "confidence": 0.9978965520858765, "x": 0.16707768187422933, "y": 0.29257641921397376, "width": 0.09864364981504316, "height": 0.026200873362445413},
        {"text": "김말이강정", "confidence": 0.9998488426208496, "x": 0.19112207151664612, "y": 0.2609170305676856, "width": 0.05240443896424168, "height": 0.027292576419213975},
        {"text": "석식", "confidence": 0.9993886947631836, "x": 0.008631319358816275, "y": 0.20742358078602618, "width": 0.03329223181257707, "height": 0.0425764192139738},
        {"text": "일반식", "confidence": 0.9998230338096619, "x": 0.0721331689272503, "y": 0.22925764192139741, "width": 0.0345252774352651, "height": 0.028384279475982533},
        {"text": "불닭팽이버섯구이", "confidence": 0.9936714172363281, "x": 0.17632552404438964, "y": 0.22925764192139736, "width": 0.08199753390875462, "height": 0.026200873362445413},
        {"text": "석식 미운영", "confidence": 0.9873544573783875, "x": 0.3588162762022195, "y": 0.22925764192139736, "width": 0.06288532675709001, "height": 0.026200873362445413},
        {"text": "당근라페양배추샐러드", "confidence": 0.9983986616134644, "x": 0.16522811344019728, "y": 0.1975982532751092, "width": 0.10234278668310727, "height": 0.027292576419213975},
        {"text": "다시마미소국/깍두기", "confidence": 0.9957463145256042, "x": 0.16707768187422933, "y": 0.16703056768558955, "width": 0.09864364981504316, "height": 0.028384279475982533},
        {"text": "PLUS 코너", "confidence": 0.9531804919242859, "x": 0.059802712700369916, "y": 0.13318777292576417, "width": 0.05733662145499383, "height": 0.026200873362445413},
        {"text": "숭능", "confidence": 0.7149524688720703, "x": 0.2059186189889026, "y": 0.13318777292576417, "width": 0.02281134401972873, "height": 0.026200873362445413},
        {"text": "*배추김치(배추·국내산,고줏가루:중국산),두부(콩:외국산),밥/죽/누룸지(쌀:국내산)/ 원산지명은 끼니별 메뉴표에 별도 표기", "confidence": 0.9710178375244141, "x": 0.18680641183723798, "y": 0.09825327510917028, "width": 0.625154130702836, "height": 0.027292576419213975},
        {"text": "간편식 원산지명은 제품표시사항을 확인해주시길 바랍니다.", "confidence": 0.9930469989776611, "x": 0.34956843403205917, "y": 0.07096069868995628, "width": 0.3002466091245376, "height": 0.027292576419213975},
        {"text": "메뉴에 따라 뼈/가시,조개/갑각류 껍질,씨앗/견과류,튀김류 등 딱딱한 식재료가 포함될 수 있으니 주의바랍니다.", "confidence": 0.9802072048187256, "x": 0.21639950678175093, "y": 0.04257641921397377, "width": 0.5647348951911221, "height": 0.026200873362445413},
        {"text": "산지 및 기타 사정에 따라 메뉴가 변경될 수 있으니 이점 미리 양해부탁드립니다!", "confidence": 0.9707025289535522, "x": 0.3008631319358816, "y": 0.01528384279475984, "width": 0.3970406905055487, "height": 0.027292576419213975},
    ]
    post = SourcePost(post_id="BA733297495412510085890", title="[뷰웍스] 2026-09-21 ~ 2026-09-25",
                      location="뷰웍스", start_date=date(2026, 9, 21))
    entries = parse_ocr_lines(post, "https://example.com/weekly.png", lines)
    by_day: dict[date, list] = {}
    for entry in entries:
        by_day.setdefault(entry.service_date, []).append(entry)

    assert by_day.get(date(2026, 9, 24), []) == []
    assert by_day.get(date(2026, 9, 23), []) == []
    assert by_day.get(date(2026, 9, 25), []) == []

    monday_texts = " | ".join(e.menu_text for e in by_day[date(2026, 9, 21)])
    assert "돈육김치찌개" in monday_texts
    assert "숭늉" in monday_texts and "숭능" not in monday_texts
