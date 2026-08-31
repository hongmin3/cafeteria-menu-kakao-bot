"""OCR 결과의 글자 오인식과 노이즈 조각을 손본다.

PaddleOCR은 끼니·날짜·휴무/특식 판정에는 영향이 없을 정도로 정확하지만, 글자
단위로는 `숭늉`을 `숭능`으로 읽거나 장식 서체 줄에서 `004` 같은 조각을 끼워
넣는다. 사용자에게 그대로 보여줄 값이라 여기서 정리한다.

세 겹으로 처리한다.

1. 노이즈 버리기 — 한글이 한 글자도 없는 항목은 버린다.
2. 표기 교정 — 한국어에 없는 표기를 고정 목록으로 바꾼다.
3. 어휘집 교정 — 지난 1년치에서 모은 실제 메뉴 이름과 한 글자만 다르고
   어휘집에 없는 항목을, 후보가 딱 하나일 때만 바꾼다.

3번은 어휘집 파일(`data/menu_vocab.json`, git 미추적)이 있을 때만 동작한다.
어휘집은 실제 메뉴 데이터라서 공개 저장소에 넣지 않는다.
`menu-bot build-vocab`으로 만든다.
"""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import re


HANGUL = re.compile(r"[가-힣]")

# 1년치 원본 OCR 167장 전수 조사에서 실제 메뉴에 섞인 홍보 제목의 공통 형태.
# 특정 셰프·브랜드 이름을 열거하지 않아 다음 행사에서도 같은 방식으로 처리한다.
PROMOTIONAL_NOISE = re.compile(
    r"(?:"
    r"셰프|쉐프|세프|\bCHEF\b|"
    r"콜라보(?:레이션)?|COLLAB(?:ORATION)?|"
    r"맛집(?:탐방|특집)?|"
    r"이벤트(?:\s*DAY)?|"
    # 이번 주 어두운 HYUNDAI GREEN FOOD 로고를 `현대그콘푸드`로 읽은
    # 실제 서버 OCR 결과까지 포함한다. 음식 메뉴의 일반적인 `푸드`는 건드리지 않는다.
    r"(?:HYUNDAI|현대)\s*(?:GREEN|그[린콘])\s*(?:FOOD|푸드)"
    r")",
    re.I,
)

# 음식명이 없이 행사명만 적힌 특식 배너. `멕시칸치킨플래터 특식`처럼 음식이
# 들어간 줄은 보존하고, `말복 특식 DAY` 같은 제목만 제거한다.
SPECIAL_BANNER_ONLY = re.compile(
    r"^[*\s]*(?:(?:VIEWORKS|뷰웍스)\s*)?(?:\d{1,2}월\s*)?"
    r"(?:초복|중복|말복|창립기념일|장김기념일)?\s*특식(?:\s*DAY)?[*\s]*$",
    re.I,
)

# 어휘집 항목이 교정 대상이 되기 위한 최소 등장 횟수. 어휘집은 Apple Vision
# OCR 결과에서 모은 것이라 그 자체에도 오인식이 섞여 있는데, 오인식은 보통
# 한두 번 나오고 실제 메뉴 이름은 여러 번 반복된다. 하한을 두지 않으면
# 올바로 읽은 값을 어휘집의 오인식으로 되돌리는 사고가 난다.
MIN_VOCAB_COUNT = 3

# 한국어에 없는 표기라서 어디에 나타나도 바꿔도 안전한 것들. 실제 이미지로
# PaddleOCR과 Apple Vision 결과를 대조해 모았다. 반대 방향(PaddleOCR이 더
# 정확했던 경우)은 넣지 않는다.
SUBSTITUTIONS = {
    # ── PaddleOCR(서버·Windows)이 틀리는 표기 ──
    # 1년치에서 466회 나오는 최다 항목. 이것만 세 갈래로 틀린다.
    "숭능": "숭늉",
    "숭융": "숭늉",
    "승능": "숭늉",
    "승늉": "숭늉",
    "숭늄": "숭늉",
    "승늄": "숭늉",
    "짝두기": "깍두기",
    "깥풍기": "깐풍기",
    "듬뿐": "듬뿍",
    "비빙밥": "비빔밥",
    "걸절이": "겉절이",
    "꼬배기": "꽈배기",
    "꼬리고추": "꽈리고추",
    "숫불": "숯불",
    "두부릇": "두부톳",
    "깨잎": "깻잎",
    "고줏잎": "고춧잎",
    "양넘": "양념",
    # 사용자 확인분. `복이`는 1년치에서 이 두 항목에만 나와 앞뒤를 함께
    # 고정하지 않아도 안전하지만, 뜻이 있는 글자라 코너 이름까지 묶는다.
    "제접무": "제첩무",
    "복이겨자": "목이겨자",
    "복이버섯": "목이버섯",
    # ── 장(醬)을 정·자·창·작·당·중·짱·잠으로 잘못 읽는 계통 오류 ──
    # 1년치 전수 조사에서 가장 많이 나온 오인식 묶음이다. `자조림`처럼 넓게
    # 잡으면 `감자조림`·`완자조림`이 깨지므로 앞 글자를 함께 고정한다.
    "쌈정": "쌈장",
    "쌈잠": "쌈장",
    "양념정": "양념장",
    "양념작": "양념장",
    "양념창": "양념장",
    "된정": "된장",
    "된자국": "된장국",
    "된당국": "된장국",
    "해자국": "해장국",
    "해당국": "해장국",
    "간정": "간장",
    "초간당": "초간장",
    "간자찜닭": "간장찜닭",
    "간창찜닭": "간장찜닭",
    "고추정": "고추장",
    "짱아찌": "장아찌",
    "짱국": "장국",
    "우동자국": "우동장국",
    "팽이중국": "팽이장국",
    "미소자국": "미소장국",
    "양해당국": "양해장국",
    "알자조림": "알장조림",
    "&초정": "&초장",
    # ── 그 밖의 글자 오인식 ──
    "씰밥": "쌀밥",
    "기창밥": "기장밥",
    "돗나물": "돌나물",
    "알새우집": "알새우칩",
    "삼감김밥": "삼각김밥",
    "부주잡채": "부추잡채",
    "후실리": "푸실리",
    "계팅": "계탕",
    "탄산용료": "탄산음료",
    "걸처": "컬처",
    "강주메뉴": "강추메뉴",
    "미슷가루": "미숫가루",
    "뜻배기": "뚝배기",
    "출기볶음": "줄기볶음",
    "떠국": "떡국",
    "베이그에그": "베이컨에그",
    # 2026-08-24 주차 목요일 중식 실제 서버 OCR 결과.
    "백쌈뽕": "백짬뽕",
    "짝두)": "깍두기",
    # `톳`을 `롯`으로 읽는 계통 오류. `롯` 하나만 잡으면 `롯데`류가 깨지므로
    # 뒤 글자까지 묶는다(`톳나물`은 2026-08-24, `톳두부`는 2026-08-31 확인).
    "롯나물무침": "톳나물무침",
    "롯두부": "톳두부",
    # 2026-08-31 사용자 확인분.
    "누륭지": "누룽지",
    # `나초`는 그 자체로 쓰이는 표기라 앞 글자를 함께 고정한다.
    "돈육나초": "돈육나쵸",
    "가마보끄": "가마보꼬",
    # ── 표준 표기로 통일 ──
    # OCR 오인식인지 인쇄 표기인지 가릴 수 없지만 한쪽이 표준 표기이고 빈도도
    # 훨씬 높은 것들. `마늘쫑`(16회) 대 `마늘종`(9회)처럼 빈도가 비슷한 표기는
    # 원문일 가능성이 있어 손대지 않는다.
    "케찹": "케첩",
    "케접": "케첩",
    "모듬콩": "모둠콩",
}


# 위 목록은 근거를 확인해 코드에 고정한 것이고, 아래 파일은 **운영하면서
# 눈에 띈 것을 그때그때 넣는 자리**다. 코드를 고치고 배포하지 않아도 되도록
# 분리했다. JSON이 아니라 한 줄에 하나인 텍스트인 이유는, 쉼표 하나 빠뜨리면
# 전체가 깨지는 형식을 사람 손에 맡기지 않기 위해서다.
USER_CORRECTIONS_PATH = "data/menu_corrections.txt"

USER_CORRECTIONS_HEADER = """\
# 메뉴 표기 교정 목록
#
# 한 줄에 하나씩,  잘못읽은표기 = 올바른표기  형식으로 적습니다.
# '#'으로 시작하는 줄과 빈 줄은 무시합니다.
#
# 이름 일부만 적어도 되고(예: 누륭지 = 누룽지), 전체를 적어도 됩니다.
# 짧게 적을수록 널리 적용되니, 다른 메뉴에도 들어갈 수 있는 글자라면
# 앞뒤를 함께 적어 좁히세요(예: 나초 = 나쵸  ← 위험 / 돈육나초 = 돈육나쵸  ← 안전).
#
# 고친 뒤 이미 저장된 식단에도 반영하려면:  menu-bot correct apply
"""


def parse_user_corrections(text: str) -> dict[str, str]:
    """`잘못 = 올바름` 줄들을 읽는다. 이해할 수 없는 줄은 조용히 건너뛴다.

    한 줄이 잘못됐다고 나머지 교정까지 버리면, 오타 하나로 식단 표기가 통째로
    되돌아간다. 파일을 편집하는 사람이 개발자가 아니라는 전제로 만든다.
    """
    rules: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        wrong, _, right = stripped.partition("=")
        wrong, right = wrong.strip(), right.strip()
        # 빈 쪽이 있거나 서로 같으면 규칙이 아니다. 자기 자신으로 바꾸는
        # 규칙을 허용하면 무한히 같은 값을 덮어쓰는 혼란만 남는다.
        if wrong and right and wrong != right:
            rules[wrong] = right
    return rules


def load_user_corrections(path: str | Path | None = None) -> dict[str, str]:
    """사용자 교정 파일을 읽는다. 없거나 읽을 수 없으면 빈 dict."""
    resolved = Path(path or os.getenv("MENU_CORRECTIONS_PATH") or USER_CORRECTIONS_PATH)
    try:
        return parse_user_corrections(resolved.read_text(encoding="utf-8"))
    except OSError:
        return {}


_cached_substitutions: dict[str, str] | None = None


def active_substitutions() -> dict[str, str]:
    """코드에 고정된 목록 + 사용자 파일. 사용자 파일이 이긴다.

    같은 표기를 두 곳에서 다르게 고치라고 하면 사람이 방금 적은 쪽을 따른다.
    현장에서 본 것이 1년치 조사보다 최신이기 때문이다.
    """
    global _cached_substitutions
    if _cached_substitutions is None:
        _cached_substitutions = {**SUBSTITUTIONS, **load_user_corrections()}
    return _cached_substitutions


def reset_substitutions_cache() -> None:
    """교정 파일을 고친 뒤 다시 읽게 한다(같은 프로세스에서 이어 쓸 때)."""
    global _cached_substitutions
    _cached_substitutions = None


def apply_substitutions(text: str, table: dict[str, str] | None = None) -> str:
    """표기 교정만 적용한다(노이즈 판정·어휘집 교정 없이).

    이미 저장된 식단에 새 교정을 다시 입힐 때 쓴다. 저장된 값은 이미 한 번
    걸러진 결과라, 그 위에 노이즈 규칙을 다시 돌리면 멀쩡한 안내 문구까지
    지울 위험이 있다. 새로 추가한 규칙만 반영하는 것이 목적이다.
    """
    for wrong, right in (table if table is not None else active_substitutions()).items():
        if wrong in text:
            text = text.replace(wrong, right)
    return text


def is_noise(item: str) -> bool:
    """버려야 할 조각인지.

    두 가지를 버린다. 둘 다 1년치 전수 조사로 근거를 확인했다.

    1. 한글이 한 글자도 없는 항목 — 고유 항목 2211개 중 15개뿐이고 전부
       장식 문구·로고 조각이었다(`Pulmuone`, `Happy New year`, `-11`, `1R`,
       `AL` 등). PaddleOCR이 끼워 넣는 `004`, `oo`, `MW`가 여기 걸린다.
    2. 한 글자짜리 항목 — 7개뿐이고 전부 조각이었다(`행`, `주`, `하`, `남`,
       `돼`, `지`, `집`). 두 글자부터는 `숭늉`(466회), `쌀밥`(243회), `잡채`,
       `식혜`, `닭죽`처럼 멀쩡한 메뉴가 많으므로 딱 한 글자만 버린다.
    """
    text = item.strip()
    return len(text) <= 1 or not HANGUL.search(text) or is_promotional_noise(text)


def is_promotional_noise(item: str) -> bool:
    """셰프·콜라보·행사 제목처럼 메뉴가 아닌 홍보 문구인지."""
    text = item.strip()
    return bool(PROMOTIONAL_NOISE.search(text) or SPECIAL_BANNER_ONLY.fullmatch(text))


def load_vocabulary(path: str | Path | None = None) -> dict[str, int]:
    """어휘집(메뉴 이름 → 등장 횟수)을 읽는다. 없으면 빈 dict."""
    resolved = Path(path or os.getenv("MENU_VOCAB_PATH") or "data/menu_vocab.json")
    if not resolved.exists():
        return {}
    try:
        loaded = json.loads(resolved.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(loaded, dict):
        return {str(key): int(value) for key, value in loaded.items()}
    # 예전 형식(항목 목록)도 받아준다. 횟수를 모르니 하한을 통과시킨다.
    return {str(item): MIN_VOCAB_COUNT for item in loaded}


def build_vocabulary(items: list[str]) -> dict[str, int]:
    return dict(Counter(items))


def _vocabulary_fix(item: str, vocabulary: dict[str, int]) -> str | None:
    """어휘집에 없는 항목을, 한 글자만 다른 어휘집 항목으로 고친다.

    길이가 같고 한 글자만 다른 경우만 본다. OCR 오인식은 대개 글자 하나가
    다른 글자로 바뀌는 형태이고, 길이까지 다른 후보를 허용하면 전혀 다른
    메뉴로 바꿔 버릴 위험이 커진다. 후보가 둘 이상이면 손대지 않는다.
    """
    if not vocabulary or item in vocabulary:
        return None
    candidates = [
        known
        for known, count in vocabulary.items()
        if count >= MIN_VOCAB_COUNT
        and len(known) == len(item)
        and sum(a != b for a, b in zip(known, item)) == 1
    ]
    return candidates[0] if len(candidates) == 1 else None


def correct_item(item: str, vocabulary: dict[str, int] | None = None) -> str | None:
    """항목 하나를 손본다. 버려야 하면 None."""
    text = item.strip()
    if not text or is_noise(text):
        return None
    text = apply_substitutions(text)
    fixed = _vocabulary_fix(text, vocabulary or {})
    return fixed or text


def clean_items(items: list[str], vocabulary: dict[str, int] | None = None) -> list[str]:
    """항목 목록을 손보고 중복을 없앤다(순서 유지)."""
    cleaned: list[str] = []
    for item in items:
        fixed = correct_item(item, vocabulary)
        if fixed and fixed not in cleaned:
            cleaned.append(fixed)
    return cleaned


_cached_vocabulary: dict[str, int] | None = None


def active_vocabulary() -> dict[str, int]:
    """어휘집을 한 번만 읽어 재사용한다(이미지마다 다시 읽지 않도록)."""
    global _cached_vocabulary
    if _cached_vocabulary is None:
        _cached_vocabulary = load_vocabulary()
    return _cached_vocabulary
