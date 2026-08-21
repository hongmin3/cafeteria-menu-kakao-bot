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
    # ── 표준 표기로 통일 ──
    # OCR 오인식인지 인쇄 표기인지 가릴 수 없지만 한쪽이 표준 표기이고 빈도도
    # 훨씬 높은 것들. `마늘쫑`(16회) 대 `마늘종`(9회)처럼 빈도가 비슷한 표기는
    # 원문일 가능성이 있어 손대지 않는다.
    "케찹": "케첩",
    "케접": "케첩",
    "모듬콩": "모둠콩",
}


def is_noise(item: str) -> bool:
    """버려야 할 조각인지.

    1년치 고유 항목 2211개를 전수 조사해 보면 한글이 한 글자도 없는 항목은
    15개뿐이고 전부 장식 문구·로고 조각이었다(`Pulmuone`, `GOPIZZA`,
    `Happy New year`, `O.`, `-11`, `1R`, `AL` 등). 실제 메뉴 이름은 예외 없이
    한글을 포함했다. PaddleOCR이 끼워 넣는 `004`, `oo`, `MW` 같은 조각이
    이 규칙에 걸린다.
    """
    return not HANGUL.search(item)


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
    for wrong, right in SUBSTITUTIONS.items():
        if wrong in text:
            text = text.replace(wrong, right)
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
