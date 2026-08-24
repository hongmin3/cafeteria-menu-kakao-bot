from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from zoneinfo import ZoneInfo

from .db import MenuDB


WEEKDAYS = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
MEALS = {"아침": "조식", "조식": "조식", "점심": "중식", "중식": "중식", "저녁": "석식", "석식": "석식"}

# 코너 이름만 말해도 그 코너가 실제로 나오는 끼니를 보여준다.
# 최근 1년치(게시물 72개·이미지 168장)를 전수 파싱해 코너×끼니를 세어 보면
# 간편식은 조식에만 133회, 건강식은 중식에만 127회 나오고 다른 끼니에는 한
# 번도 나오지 않는다. 그래서 이 둘은 끼니를 특정할 수 있다.
CATEGORY_MEALS = {"간편식": "조식", "건강식": "중식"}

# 반면 일반식(1026회)과 PLUS 코너(445회)는 세 끼니에 모두 나오므로 코너
# 이름만으로 끼니를 고를 수 없다. 임의로 고르지 않고 끼니를 되묻는다.
AMBIGUOUS_CATEGORY_WORDS = ("일반식", "PLUS", "plus", "플러스", "공통")

# 기본 사업장 이름(POST_PREFIXES 기본값과 같다). "평촌점심"처럼 사업장을 붙여
# 묻는 사람이 있어서, 아는 말로 취급해야 "모르는 말"로 오판하지 않는다.
DEFAULT_LOCATIONS = ("뷰웍스", "안양", "화성", "평촌")

WEEK_SCOPE_WORDS = ("다다음주", "이번주", "다음주", "지난주", "저번주")
RELATIVE_DAY_WORDS = ("모레", "오늘", "내일", "어제")

# 질문의 뼈대가 아니라 말투·조사에 해당하는 표현들. 아래 표현과 날짜·요일·
# 끼니·코너·사업장을 모두 지운 뒤에도 두 글자 이상 남으면 우리가 모르는
# 말이 섞인 것으로 보고, 오늘 전체 식단으로 넘기지 않고 사용방법을 안내한다.
FILLER_WORDS = (
    "식단표", "알려줘", "무엇", "뭔지", "뭐야", "머야", "뭐먹", "먹어", "보여줘",
    "식단", "메뉴", "주말", "부탁", "확인", "있어", "있나", "알려", "보여",
    "먹", "밥", "뭐", "머", "표", "줘", "좀", "야", "어", "요", "나와", "나옴", "나오",
)


def _structural_words(locations: tuple[str, ...]) -> tuple[str, ...]:
    """질문의 뼈대에 해당하는 표현. 긴 것부터 지워야 "일반식"에서 "일"이 먼저
    사라져 "반식"이 남는 식으로 말이 조각나지 않는다."""
    words = (
        *WEEK_SCOPE_WORDS, *RELATIVE_DAY_WORDS, *MEALS, *CATEGORY_MEALS,
        *AMBIGUOUS_CATEGORY_WORDS, *locations,
    )
    return tuple(sorted(set(words), key=len, reverse=True))


def unknown_terms(text: str, locations: tuple[str, ...] = DEFAULT_LOCATIONS) -> list[str]:
    """질문에서 우리가 해석하지 못한 낱말들.

    지우는 표현을 두 층으로 나눈다. 날짜·요일·끼니·코너·사업장은 뼈대라서
    지운 뒤 되돌리지 않지만, 말투·조사(밥·뭐·있어 …)는 모르는 낱말 안에
    묻혀 있을 수 있어 되살린다. 한 층으로 처리하면 "삼각김밥"에서 "밥"이
    빠져 "삼각김"이라고 되묻는 꼴이 된다.
    """
    normalized = normalize_query(text)
    size = len(normalized)
    structural = [False] * size   # 뼈대로 소비된 자리
    filler = [False] * size       # 말투·조사로 소비된 자리

    def mask(flags: list[bool], start: int, end: int) -> None:
        for index in range(start, end):
            flags[index] = True

    def free(start: int, end: int) -> bool:
        return not any(structural[start:end] or filler[start:end])

    for pattern in (
        r"(?:20\d{2}년\s*)?\d{1,2}월\s*\d{1,2}일",
        r"(?<!\d)\d{1,2}/\d{1,2}(?!\d)",
        r"[월화수목금토일]요일",
    ):
        for match in re.finditer(pattern, normalized):
            mask(structural, *match.span())
    for word in _structural_words(locations):
        start = 0
        while (found := normalized.find(word, start)) >= 0:
            if free(found, found + len(word)):
                mask(structural, found, found + len(word))
            start = found + 1
    # 요일 한 글자는 낱개로 남았을 때만 뼈대로 본다("월요일"·"일반식" 같은 긴
    # 표현은 위에서 이미 소비됐다).
    for match in re.finditer(r"(?<![가-힣])[월화수목금토일](?![가-힣])", normalized):
        if free(*match.span()):
            mask(structural, *match.span())
    for word in sorted(set(FILLER_WORDS), key=len, reverse=True):
        start = 0
        while (found := normalized.find(word, start)) >= 0:
            if free(found, found + len(word)):
                mask(filler, found, found + len(word))
            start = found + 1

    def is_wordish(index: int) -> bool:
        return bool(re.match(r"[0-9A-Za-z가-힣]", normalized[index]))

    terms: list[str] = []
    index = 0
    while index < size:
        if structural[index] or filler[index] or not is_wordish(index):
            index += 1
            continue
        start, end = index, index
        while end < size and not structural[end] and is_wordish(end):
            end += 1
        # 모르는 낱말에 붙어 있던 말투·조사를 되살려 낱말을 온전히 보여준다.
        while start > 0 and filler[start - 1] and is_wordish(start - 1):
            start -= 1
        term = normalized[start:end]
        if re.fullmatch(r"[가-힣]{2,}|[A-Za-z]{2,}", term):
            terms.append(term)
        index = end + 1
    return terms


HELP_TEXT = """🍚 뷰밥 메뉴 알리미

안녕하세요! 사내 식당 식단을 알려드려요.
아래처럼 편하게 물어보시면 됩니다 😊

🍳 끼니만 말하기
 ‘아침’ ‘점심’ ‘저녁’ → 오늘 그 끼니

📅 날짜와 함께
 ‘금요일 점심’ → 이번 주 금요일 중식
 ‘금요일’ → 그날 조식·중식·석식 전부
 ‘내일 저녁’ ‘모레 아침’ ‘8/25 점심’도 됩니다

🥗 코너로 찾기
 ‘간편식’ → 그날 조식 (조식에만 나와요)
 ‘건강식’ → 그날 중식 (중식에만 나와요)

💡 알아두시면 좋아요
 · 요일은 늘 이번 주로 봐요. 지난 주·다음 주는 조회할 수 없어요.
 · 주말(토·일)은 식당을 운영하지 않아요.
 · ‘금욜’ ‘낼점심’처럼 줄여 말해도 알아들어요.
 · 특식은 ✨, 미운영은 안내 문구로 표시해요.

이 안내가 다시 필요하면 아래 ‘사용방법’ 버튼을 눌러 주세요!"""

CASUAL_REPLACEMENTS = {
    "월욜": "월요일",
    "화욜": "화요일",
    "수욜": "수요일",
    "목욜": "목요일",
    "금욜": "금요일",
    "토욜": "토요일",
    "일욜": "일요일",
    "낼모레": "모레",
    "낼": "내일",
    "담주": "다음주",
    "차주": "다음주",
    "금주": "이번주",
}


def normalize_query(text: str) -> str:
    normalized = text.strip()
    normalized = re.sub(r"(다음|이번|담|차|금)\s+주", r"\1주", normalized)
    for casual, standard in CASUAL_REPLACEMENTS.items():
        normalized = normalized.replace(casual, standard)
    normalized = re.sub(r"(다음주|이번주)([월화수목금토일])(?=\s|$)", r"\1 \2요일", normalized)
    normalized = re.sub(r"[?!,.]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def looks_like_menu_query(text: str) -> bool:
    normalized = normalize_query(text).replace(" ", "")
    # A single weekday character is a supported shorthand (for example,
    # "월" for all Monday meals and "토" for the weekend closure notice).
    if normalized in WEEKDAYS:
        return True
    if re.search(r"(?:(?:20\d{2})년)?\d{1,2}월\d{1,2}일|(?<!\d)\d{1,2}/\d{1,2}(?!\d)", normalized):
        return True
    hints = (
        *MEALS.keys(), "오늘", "내일", "모레", "어제", "이번주", "다음주",
        "지난주", "저번주", "다다음주",
        "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일",
        "식단", "메뉴", "밥", "뭐먹", "뭐나와", "주말",
        # 코너 이름만 말해도 식단 질문으로 받는다(끼니는 CATEGORY_MEALS로
        # 정하거나, 정할 수 없으면 되묻는다).
        *CATEGORY_MEALS, *AMBIGUOUS_CATEGORY_WORDS,
    )
    return any(hint in normalized for hint in hints)


def query_issue(
    text: str, today: date | None = None, locations: tuple[str, ...] = DEFAULT_LOCATIONS
) -> str | None:
    """Return a clarification for ambiguous or unsupported date/meal input."""
    normalized = normalize_query(text)
    compact = normalized.replace(" ", "")
    if any(token in compact for token in ("지난주", "저번주")):
        return "지난 주 식단은 제공하지 않아요. 이번 주 식단만 조회할 수 있어요."
    if "다다음주" in compact:
        return "다다음 주 식단은 제공하지 않아요. 이번 주 식단만 조회할 수 있어요."

    # 모르는 말이 섞였으면 오늘 전체 식단으로 넘기지 않는다. 예전에는
    # "오늘 커피"처럼 날짜만 알아들어도 그날 세 끼니를 다 보여줘서, 답을
    # 못 하는 질문에 엉뚱한 답을 준 것처럼 보였다.
    unknown = unknown_terms(normalized, locations)
    if unknown:
        quoted = ", ".join(f"‘{term}’" for term in dict.fromkeys(unknown))
        return f"{quoted}(은)는 제가 알아듣지 못했어요. 😅\n\n{HELP_TEXT}"

    # 코너 이름으로 물었을 때. 간편식·건강식은 나오는 끼니가 정해져 있어
    # 그 끼니를 보여주지만(parse_query 참고), 일반식·PLUS는 세 끼니에 모두
    # 나와서 끼니를 임의로 고를 수 없다.
    category_meals = {value for key, value in CATEGORY_MEALS.items() if key in compact}
    meal_types_now = {value for key, value in MEALS.items() if key in compact}
    if len(category_meals) > 1:
        return "코너를 하나만 말해 주세요. 예: ‘간편식’(조식) 또는 ‘건강식’(중식)"
    if category_meals and meal_types_now and category_meals != meal_types_now:
        category = next(key for key in CATEGORY_MEALS if key in compact)
        return (
            f"‘{category}’은 {CATEGORY_MEALS[category]}에만 나와요.\n"
            f"‘{category}’이라고만 말하면 그날 {CATEGORY_MEALS[category]}을 보여드려요."
        )
    if not category_meals and any(word in compact for word in AMBIGUOUS_CATEGORY_WORDS):
        if not meal_types_now:
            return (
                "일반식과 PLUS 코너는 조식·중식·석식에 모두 나와서 끼니를 알려주셔야 해요.\n"
                "예: ‘점심’ 또는 ‘금요일 저녁’\n"
                "하루 전체를 보시려면 ‘금요일’처럼 요일만 말해 주세요."
            )

    week_scopes = {token for token in ("이번주", "다음주") if token in compact}
    relative_days = {token for token in ("어제", "오늘", "내일", "모레") if token in compact}
    weekdays = set(re.findall(r"([월화수목금토일])요일", normalized))
    weekdays.update(re.findall(r"(?<!\S)([월화수목금토일])(?!\S)", normalized))
    meal_types = {value for key, value in MEALS.items() if key in compact}
    explicit = list(re.finditer(r"(?:(20\d{2})년\s*)?(\d{1,2})월\s*(\d{1,2})일", normalized))
    slashes = list(re.finditer(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", normalized))

    if "다음주" in week_scopes:
        return "다음 주 식단은 제공하지 않아요. 이번 주 식단만 조회할 수 있어요."
    if len(week_scopes) > 1 or len(relative_days) > 1 or len(explicit) + len(slashes) > 1:
        return "날짜를 하나만 말해 주세요. 예: ‘내일 점심’ 또는 ‘이번주 월요일’."
    if week_scopes and (relative_days or explicit or slashes):
        return "주차와 날짜 표현을 함께 쓰면 헷갈릴 수 있어요. 하나만 말해 주세요. 예: ‘오늘 점심’ 또는 ‘이번주 월요일’."
    if (relative_days or explicit or slashes) and weekdays:
        return "날짜와 요일을 하나만 말해 주세요. 예: ‘내일 점심’ 또는 ‘목요일 점심’."
    if len(weekdays) > 1:
        return "요일을 하나만 말해 주세요. 예: ‘월요일’ 또는 ‘화요일 점심’."
    if len(meal_types) > 1:
        return "끼니를 하나만 말해 주세요. 하루 전체 식단은 ‘화요일’처럼 요일만 입력해 주세요."
    if week_scopes and not weekdays:
        return "이번 주 식단을 보려면 요일을 함께 말해 주세요.\n예: ‘이번주 월요일’ 또는 ‘이번주 화요일 점심’"

    reference_year = (today or date.today()).year
    try:
        for match in explicit:
            date(int(match.group(1) or reference_year), int(match.group(2)), int(match.group(3)))
        for match in slashes:
            date(reference_year, int(match.group(1)), int(match.group(2)))
    except ValueError:
        return "날짜를 확인해 주세요. 예: ‘8월 20일 점심’ 또는 ‘8/20 점심’."
    return None


@dataclass(frozen=True)
class ParsedQuery:
    day: date
    meal_type: str | None
    location: str | None
    scope: str


def parse_query(text: str, now: datetime) -> ParsedQuery:
    normalized = normalize_query(text)
    meal = next((value for key, value in MEALS.items() if key in normalized), None)
    if meal is None:
        # 끼니를 직접 말하지 않았어도 코너 이름으로 알 수 있는 경우가 있다.
        # ‘간편식’은 조식에만, ‘건강식’은 중식에만 나온다(CATEGORY_MEALS).
        meal = next((value for key, value in CATEGORY_MEALS.items() if key in normalized), None)
    today = now.date()
    scope = "today"
    if "모레" in normalized:
        target = today + timedelta(days=2)
    elif "내일" in normalized:
        target = today + timedelta(days=1)
    elif "어제" in normalized:
        target = today - timedelta(days=1)
    elif "오늘" in normalized:
        target = today
    else:
        explicit = re.search(r"(?:(20\d{2})년\s*)?(\d{1,2})월\s*(\d{1,2})일", normalized)
        slash = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", normalized)
        if explicit:
            year = int(explicit.group(1) or today.year)
            target = date(year, int(explicit.group(2)), int(explicit.group(3)))
            scope = "explicit"
        elif slash:
            target = date(today.year, int(slash.group(1)), int(slash.group(2)))
            scope = "explicit"
        else:
            weekday_match = re.search(r"([월화수목금토일])요일", normalized)
            if not weekday_match:
                weekday_match = re.search(r"(?:^|\s)([월화수목금토일])(?:\s|$)", normalized)
            if weekday_match:
                target_weekday = WEEKDAYS[weekday_match.group(1)]
                if "다음주" in normalized or "다음 주" in normalized:
                    week_shift, scope = 7, "next_week"
                elif "이번주" in normalized or "이번 주" in normalized:
                    week_shift, scope = 0, "current_week"
                else:
                    week_shift, scope = 0, "current_week"
                monday = today - timedelta(days=today.weekday()) + timedelta(days=week_shift)
                target = monday + timedelta(days=target_weekday)
            else:
                target = today
    return ParsedQuery(target, meal, None, scope)


# 챗봇이 답하는 기준 사업장. 다른 사업장 게시글만 올라온 주차에는
# 그것으로 대신 답하되(_merge_sites), 이 게시글을 계속 기다린다.
PRIMARY_LOCATION = "뷰웍스"
MERGED_LOCATION = "공통"


def _meal_is_closed(meal_rows: list) -> bool:
    return any(row["status"] == "no_service" and row["category"] == "안내" for row in meal_rows)


def _row_dict(row, location: str) -> dict:
    return {
        "service_date": row["service_date"], "location": location,
        "meal_type": row["meal_type"], "category": row["category"],
        "menu_text": row["menu_text"], "status": row["status"],
    }


def _merge_sites(rows: list) -> list:
    """여러 사업장 게시글만 올라온 주차를 끼니 단위로 합친다.

    2026-08-24 주차에 [화성]·[안양] 게시글만 올라온 적이 있는데, 두 식단을
    셀 단위로 대조해 보니 42칸 중 31칸이 완전히 같고 실제 차이는 "어느 요일
    조식을 쉬는가"뿐이었다(안양은 화요일, 화성은 목요일 조식 미운영).
    나머지 차이는 전부 OCR 오인식이었다.

    그래서 끼니별로 운영/미운영이 같으면 같은 식단으로 보고 하나로 합치고,
    운영 여부가 갈리는 끼니만 사업장을 나란히 보여준다. 합칠 때는 코너별로
    더 풍부하게 읽힌 쪽을 채택한다(pipeline의 중복 처리와 같은 원칙).
    """
    by_meal: dict[str, dict[str, list]] = {}
    for row in rows:
        by_meal.setdefault(row["meal_type"], {}).setdefault(row["location"], []).append(row)

    merged: list = []
    for per_site in by_meal.values():
        closed = {site: _meal_is_closed(site_rows) for site, site_rows in per_site.items()}
        if len(set(closed.values())) > 1:
            # 운영 여부가 사업장마다 다르다(안양은 화요일, 화성은 목요일 조식
            # 미운영). 식당은 평소 두 사업장 메뉴가 같아 [뷰웍스] 하나로
            # 올리고, 이런 예외가 있는 주에만 사업장을 나눠 올린다. 즉 이
            # 차이는 진짜다. 사용자는 둘 중 한 곳에 있으므로 한쪽만 골라
            # 보여주면 나머지 절반은 닫힌 식당으로 가게 된다.
            for site in sorted(per_site):
                merged.extend(_row_dict(row, site) for row in per_site[site])
            continue
        best: dict[str, dict] = {}
        for site_rows in per_site.values():
            for row in site_rows:
                candidate = _row_dict(row, MERGED_LOCATION)
                previous = best.get(row["category"])
                if previous is None or _richer(candidate, previous):
                    best[row["category"]] = candidate
        merged.extend(best.values())
    return merged


def _richer(candidate: dict, previous: dict) -> bool:
    """항목 수가 많은 쪽, 같으면 글자가 긴 쪽을 고른다."""
    return (
        len(_menu_items(candidate["menu_text"])), len(candidate["menu_text"])
    ) > (
        len(_menu_items(previous["menu_text"])), len(previous["menu_text"])
    )


def _choose_common_menu(rows: list) -> list:
    locations = sorted({row["location"] for row in rows})
    common = [row for row in rows if row["location"] == PRIMARY_LOCATION]
    if common:
        return common
    if len(locations) == 1:
        return rows
    if locations:
        return _merge_sites(rows)
    return []


def _menu_items(menu_text: str) -> list[str]:
    """Split OCR-normalized menu cells without breaking meaningful slash pairs."""
    return [item.strip() for item in menu_text.split(" · ") if item.strip()]


def answer(
    db: MenuDB,
    text: str,
    timezone: str,
    default_location: str = "",
    now: datetime | None = None,
    locations: tuple[str, ...] = DEFAULT_LOCATIONS,
) -> str:
    current = now or datetime.now(ZoneInfo(timezone))
    if "주말" in normalize_query(text):
        return "주말에는 식당을 운영하지 않습니다."
    issue = query_issue(text, current.date(), locations)
    if issue:
        return issue
    parsed = parse_query(text, current)
    this_monday = current.date() - timedelta(days=current.date().weekday())
    target_monday = parsed.day - timedelta(days=parsed.day.weekday())
    if target_monday != this_monday:
        return "이번 주 식단만 조회할 수 있어요. 이번 주 요일로 물어봐 주세요."
    if parsed.day.weekday() >= 5:
        weekday = "토" if parsed.day.weekday() == 5 else "일"
        return f"{parsed.day:%m월 %d일}({weekday}) 주말에는 식당을 운영하지 않습니다."
    rows = db.query(parsed.day, parsed.meal_type)
    if not rows:
        # 주말 폴링이나 월요일 수집이 아직 식단표를 못 받은 상태. 없는 식단을
        # 지어내지 않고 사정을 그대로 알린다. 서버는 확보될 때까지 1시간 간격
        # 으로 계속 다시 확인한다(menubot-ensure.timer).
        weekday = "월화수목금토일"[parsed.day.weekday()]
        return (
            f"{parsed.day:%m월 %d일}({weekday}) 식단표가 아직 그룹웨어에 올라오지 않았어요.\n"
            "올라오면 자동으로 반영되니 조금 뒤에 다시 물어봐 주세요. 🙏"
        )
    selected = _choose_common_menu(rows)
    if not selected:
        weekday = "월화수목금토일"[parsed.day.weekday()]
        return (
            f"{parsed.day:%m월 %d일}({weekday}) 공통 식단표를 확인할 수 없어요.\n"
            "사업장별 식단만 올라온 것 같아요. 담당자에게 확인이 필요합니다."
        )

    weekday = "월화수목금토일"[parsed.day.weekday()]
    # 어느 사업장 게시글에서 왔는지 설명하는 문구는 넣지 않는다. 다만 그 주에
    # 실제로 사업장별 차이가 있어 나뉘어 올라온 것이므로, 차이나는 끼니만은
    # 사업장을 밝혀 보여준다. 한쪽만 골라 보여주면 나머지 절반의 사용자가
    # 닫힌 식당으로 가게 된다.
    parts = [f"🍽 {parsed.day:%m월 %d일}({weekday})"]
    grouped: dict[str, list] = {}
    for row in selected:
        grouped.setdefault(row["meal_type"], []).append(row)
    for meal in ("조식", "중식", "석식"):
        meal_rows = grouped.get(meal)
        if not meal_rows:
            continue
        sites = sorted({row["location"] for row in meal_rows})
        if len(sites) > 1:
            meal_parts = [f"[{meal}]", "※ 이 끼니는 사업장에 따라 달라요"]
            for site in sites:
                meal_parts.append("")
                meal_parts.append(f"〔{site}〕")
                meal_parts.extend(
                    _render_meal_body([r for r in meal_rows if r["location"] == site])
                )
        else:
            meal_parts = [f"[{meal}]", *_render_meal_body(meal_rows)]
        parts.append("\n".join(meal_parts))
    return "\n\n".join(parts)


def _render_meal_body(meal_rows: list) -> list[str]:
    notices = [row for row in meal_rows if row["status"] == "no_service" and row["category"] == "안내"]
    if notices:
        unique = list(dict.fromkeys(row["menu_text"] for row in notices))
        return ["<운영 안내>", *(f"- {notice}" for notice in unique)]

    lines: list[str] = []
    plus_rows = [row for row in meal_rows if row["category"] == "PLUS 코너"]
    main_rows = [row for row in meal_rows if row["category"] != "PLUS 코너"]
    for row in main_rows:
        if lines and lines[-1] != "":
            lines.append("")
        marker = "✨ " if row["status"] == "special" else ""
        lines.append(f"{marker}<{row['category']}>")
        if row["status"] == "no_service":
            lines.append(f"- 미제공 ({row['menu_text']})")
            continue
        lines.extend(f"- {item}" for item in _menu_items(row["menu_text"]))
    if plus_rows:
        plus_items: list[str] = []
        for row in plus_rows:
            plus_items.extend(_menu_items(row["menu_text"]))
        if lines and lines[-1] != "":
            lines.append("")
        lines.append("<공통 PLUS>")
        lines.extend(f"- {item}" for item in dict.fromkeys(plus_items))
    return lines
