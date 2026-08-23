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
    ],
)
def test_this_week_misreadings_are_fixed(wrong: str, right: str):
    """2026-08-24 주차 실제 수집분에서 사용자가 잡아 준 오인식."""
    assert correct_item(wrong) == right


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
