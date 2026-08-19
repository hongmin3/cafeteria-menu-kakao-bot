from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from zoneinfo import ZoneInfo

from .db import MenuDB


WEEKDAYS = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
MEALS = {"아침": "조식", "조식": "조식", "점심": "중식", "중식": "중식", "저녁": "석식", "석식": "석식"}
LOCATIONS = ("평촌", "안양", "화성", "뷰웍스")


@dataclass(frozen=True)
class ParsedQuery:
    day: date
    meal_type: str | None
    location: str | None
    scope: str


def parse_query(text: str, now: datetime) -> ParsedQuery:
    normalized = re.sub(r"\s+", " ", text.strip())
    meal = next((value for key, value in MEALS.items() if key in normalized), None)
    location = next((name for name in LOCATIONS if name in normalized), None)
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
    return ParsedQuery(target, meal, location, scope)


def _choose_location(rows: list, requested: str | None, default_location: str) -> tuple[list, str | None]:
    locations = sorted({row["location"] for row in rows})
    wanted = requested or default_location or None
    if wanted:
        exact = [row for row in rows if row["location"] == wanted]
        if exact:
            return exact, wanted
        common = [row for row in rows if row["location"] == "뷰웍스"]
        if common:
            return common, "뷰웍스(공통)"
        return [], wanted
    non_common = [name for name in locations if name != "뷰웍스"]
    if len(non_common) > 1:
        return [], None
    if "뷰웍스" in locations:
        return [row for row in rows if row["location"] == "뷰웍스"], "뷰웍스(공통)"
    if len(locations) == 1:
        return rows, locations[0]
    return [], None


def answer(db: MenuDB, text: str, timezone: str, default_location: str = "", now: datetime | None = None) -> str:
    current = now or datetime.now(ZoneInfo(timezone))
    parsed = parse_query(text, current)
    this_monday = current.date() - timedelta(days=current.date().weekday())
    allowed_mondays = {this_monday, this_monday + timedelta(days=7)}
    target_monday = parsed.day - timedelta(days=parsed.day.weekday())
    if parsed.scope == "explicit" and target_monday not in allowed_mondays:
        return "과거 식단 조회는 지원하지 않아요. 이번 주 또는 다음 주 요일로 물어봐 주세요."
    rows = db.query(parsed.day, parsed.meal_type)
    if not rows:
        weekday = "월화수목금토일"[parsed.day.weekday()]
        return f"{parsed.day:%m월 %d일}({weekday}) 식단표가 아직 업로드되지 않았습니다."
    selected, location_label = _choose_location(rows, parsed.location, default_location)
    if not selected:
        choices = ", ".join(sorted({row["location"] for row in rows}))
        if parsed.location:
            return f"{parsed.day:%m월 %d일} {parsed.location} 식단은 없어요. 확인 가능한 지점: {choices}"
        return f"지점을 함께 말해 주세요. 예: ‘평촌 금요일 점심’\n확인 가능한 지점: {choices}"

    weekday = "월화수목금토일"[parsed.day.weekday()]
    title = f"🍽 {parsed.day:%m월 %d일}({weekday}) {location_label}"
    parts = [title]
    grouped: dict[str, list] = {}
    for row in selected:
        grouped.setdefault(row["meal_type"], []).append(row)
    for meal in ("조식", "중식", "석식"):
        meal_rows = grouped.get(meal)
        if not meal_rows:
            continue
        parts.append(f"\n[{meal}]")
        notices = [row for row in meal_rows if row["status"] == "no_service" and row["category"] == "안내"]
        if notices:
            notices = list(dict.fromkeys(row["menu_text"] for row in notices))
            parts.append("운영 없음 — " + " / ".join(notices))
            continue
        plus_rows = [row for row in meal_rows if row["category"] == "PLUS 코너"]
        main_rows = [row for row in meal_rows if row["category"] != "PLUS 코너"]
        for row in main_rows:
            if row["status"] == "no_service":
                parts.append(f"{row['category']}: 미제공 ({row['menu_text']})")
                continue
            marker = "✨ " if row["status"] == "special" else ""
            parts.append(f"{marker}{row['category']}: {row['menu_text']}")
        if plus_rows:
            plus_text = " / ".join(dict.fromkeys(row["menu_text"] for row in plus_rows))
            parts.append(f"공통 PLUS: {plus_text}")
    return "\n".join(parts)
