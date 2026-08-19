from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from zoneinfo import ZoneInfo

from .db import MenuDB


WEEKDAYS = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
MEALS = {"아침": "조식", "조식": "조식", "점심": "중식", "중식": "중식", "저녁": "석식", "석식": "석식"}

HELP_TEXT = """🍚 뷰밥 메뉴 알리미 사용법
원하는 날짜와 끼니를 편하게 말해 주세요.

• 아침 → 오늘 조식
• 금요일 점심 → 이번 주 금요일 중식
• 월 → 월요일의 모든 식단
• 내일 저녁 → 내일 석식

토·일요일에는 월~금 요일을 다음 주로 해석해요.
주말 식사는 운영하지 않아요.
언제든 ‘사용방법’ 또는 ‘도움말’을 입력해 다시 볼 수 있어요."""

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
}


def normalize_query(text: str) -> str:
    normalized = text.strip()
    for casual, standard in CASUAL_REPLACEMENTS.items():
        normalized = normalized.replace(casual, standard)
    normalized = re.sub(r"(다음주|이번주)([월화수목금토일])(?=\s|$)", r"\1 \2요일", normalized)
    normalized = re.sub(r"[?!,.]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def looks_like_menu_query(text: str) -> bool:
    normalized = normalize_query(text).replace(" ", "")
    hints = (
        *MEALS.keys(), "오늘", "내일", "모레", "어제", "이번주", "다음주",
        "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일",
        "식단", "메뉴", "밥", "뭐먹", "뭐나와", "주말",
    )
    return any(hint in normalized for hint in hints)


@dataclass(frozen=True)
class ParsedQuery:
    day: date
    meal_type: str | None
    location: str | None
    scope: str


def parse_query(text: str, now: datetime) -> ParsedQuery:
    normalized = normalize_query(text)
    meal = next((value for key, value in MEALS.items() if key in normalized), None)
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
                    # 주말에는 새로 게시된 다음 주 식단을 묻는 것이 기본 동작이다.
                    week_shift = 7 if today.weekday() >= 5 else 0
                    scope = "next_week" if week_shift else "current_week"
                monday = today - timedelta(days=today.weekday()) + timedelta(days=week_shift)
                target = monday + timedelta(days=target_weekday)
            else:
                target = today
    return ParsedQuery(target, meal, None, scope)


def _choose_common_menu(rows: list) -> list:
    locations = sorted({row["location"] for row in rows})
    common = [row for row in rows if row["location"] == "뷰웍스"]
    if common:
        return common
    if len(locations) == 1:
        return rows
    return []


def _menu_items(menu_text: str) -> list[str]:
    """Split OCR-normalized menu cells without breaking meaningful slash pairs."""
    return [item.strip() for item in menu_text.split(" · ") if item.strip()]


def answer(db: MenuDB, text: str, timezone: str, default_location: str = "", now: datetime | None = None) -> str:
    current = now or datetime.now(ZoneInfo(timezone))
    if "주말" in normalize_query(text):
        return "주말에는 식당을 운영하지 않습니다."
    parsed = parse_query(text, current)
    this_monday = current.date() - timedelta(days=current.date().weekday())
    allowed_mondays = {this_monday, this_monday + timedelta(days=7)}
    target_monday = parsed.day - timedelta(days=parsed.day.weekday())
    if parsed.scope == "explicit" and target_monday not in allowed_mondays:
        return "과거 식단 조회는 지원하지 않아요. 이번 주 또는 다음 주 요일로 물어봐 주세요."
    if parsed.day.weekday() >= 5:
        weekday = "토" if parsed.day.weekday() == 5 else "일"
        return f"{parsed.day:%m월 %d일}({weekday}) 주말에는 식당을 운영하지 않습니다."
    rows = db.query(parsed.day, parsed.meal_type)
    if not rows:
        weekday = "월화수목금토일"[parsed.day.weekday()]
        return f"{parsed.day:%m월 %d일}({weekday}) 식단표가 아직 업로드되지 않았습니다."
    selected = _choose_common_menu(rows)
    if not selected:
        weekday = "월화수목금토일"[parsed.day.weekday()]
        return f"{parsed.day:%m월 %d일}({weekday}) 공통 식단표를 확인할 수 없습니다."

    weekday = "월화수목금토일"[parsed.day.weekday()]
    title = f"🍽 {parsed.day:%m월 %d일}({weekday})"
    parts = [title]
    grouped: dict[str, list] = {}
    for row in selected:
        grouped.setdefault(row["meal_type"], []).append(row)
    for meal in ("조식", "중식", "석식"):
        meal_rows = grouped.get(meal)
        if not meal_rows:
            continue
        meal_parts = [f"[{meal}]"]
        notices = [row for row in meal_rows if row["status"] == "no_service" and row["category"] == "안내"]
        if notices:
            notices = list(dict.fromkeys(row["menu_text"] for row in notices))
            meal_parts.append("<운영 안내>")
            meal_parts.extend(f"- {notice}" for notice in notices)
            parts.append("\n".join(meal_parts))
            continue
        plus_rows = [row for row in meal_rows if row["category"] == "PLUS 코너"]
        main_rows = [row for row in meal_rows if row["category"] != "PLUS 코너"]
        for row in main_rows:
            marker = "✨ " if row["status"] == "special" else ""
            meal_parts.append(f"{marker}<{row['category']}>")
            if row["status"] == "no_service":
                meal_parts.append(f"- 미제공 ({row['menu_text']})")
                continue
            meal_parts.extend(f"- {item}" for item in _menu_items(row["menu_text"]))
        if plus_rows:
            plus_items = []
            for row in plus_rows:
                plus_items.extend(_menu_items(row["menu_text"]))
            meal_parts.append("<공통 PLUS>")
            meal_parts.extend(f"- {item}" for item in dict.fromkeys(plus_items))
        parts.append("\n".join(meal_parts))
    return "\n\n".join(parts)
