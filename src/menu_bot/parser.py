from __future__ import annotations

from collections import defaultdict
from datetime import date
import re

from .corrections import active_vocabulary, clean_items, is_promotional_noise
from .models import MenuEntry, SourcePost


DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[./]\s*(\d{1,2})(?!\d)")
MEAL_WORDS = {"조식": "조식", "아침": "조식", "중식": "중식", "점심": "중식", "석식": "석식", "저녁": "석식"}
CATEGORIES = {
    "일반식": "일반식", "PLUS코너": "PLUS 코너", "PLUS 코너": "PLUS 코너",
    "PLUS": "PLUS 코너", "간편식": "간편식", "건강식": "건강식",
}
NO_SERVICE_PATTERNS = re.compile(r"대체\s*휴무|휴무|미운영|미제공|운영\s*없|제공\s*없|공휴일|휴일")
FULL_DAY_PATTERNS = re.compile(r"대체\s*휴무|대체\s*공휴일|공휴일|전사\s*휴무|노동절")
SPECIAL_PATTERNS = re.compile(r"특식|DAY|데이|영양사\s*픽|스페셜", re.I)


def post_from_title(post_id: str, title: str, image_urls: list[str]) -> SourcePost:
    location_match = re.match(r"\[([^]]+)]", title)
    if not location_match:
        raise ValueError(f"지원하지 않는 게시물 제목: {title}")
    ymd = re.search(r"(20\d{2})[-년]\s*(\d{1,2})(?:[-월]\s*)(\d{1,2})", title)
    if not ymd:
        raise ValueError(f"게시물 날짜를 읽을 수 없습니다: {title}")
    return SourcePost(
        post_id=post_id,
        title=title,
        location=location_match.group(1),
        start_date=date(*map(int, ymd.groups())),
        image_urls=image_urls,
    )


def _center(line: dict) -> tuple[float, float]:
    return line["x"] + line["width"] / 2, line["y"] + line["height"] / 2


def _resolve_date(month: int, day: int, anchor: date) -> date:
    candidates = []
    for year in (anchor.year - 1, anchor.year, anchor.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        candidates.append(candidate)
    return min(candidates, key=lambda d: abs((d - anchor).days))


def parse_ocr_lines(post: SourcePost, image_url: str, lines: list[dict]) -> list[MenuEntry]:
    date_headers: list[tuple[float, date]] = []
    date_header_ys: list[float] = []
    for line in lines:
        match = DATE_RE.search(line["text"])
        x, _ = _center(line)
        # 휴무 안내 그림 안의 `8.17` 같은 큰 숫자를 날짜 헤더로 오인하지 않는다.
        if match and line["y"] > 0.78:
            parsed = _resolve_date(int(match.group(1)), int(match.group(2)), post.start_date)
            if abs((parsed - post.start_date).days) <= 10:
                date_headers.append((x, parsed))
                date_header_ys.append(_center(line)[1])
    dedup_dates: dict[date, float] = {}
    for x, day in date_headers:
        dedup_dates.setdefault(day, x)
    date_headers = sorted((x, day) for day, x in dedup_dates.items())
    if not date_headers:
        return []

    meal_labels: list[tuple[float, str]] = []
    category_labels: list[tuple[float, str, str]] = []
    for line in lines:
        text = re.sub(r"\s+", " ", line["text"].strip())
        x, y = _center(line)
        if x > 0.16:
            continue
        compact = text.replace(" ", "")
        if compact in MEAL_WORDS:
            meal_labels.append((y, MEAL_WORDS[compact]))
        for raw, normalized in CATEGORIES.items():
            if compact.upper() == raw.replace(" ", "").upper():
                category_labels.append((y, normalized, ""))
                break
    if not meal_labels:
        return []

    meal_labels.sort(reverse=True)
    labeled_categories: list[tuple[float, str, str]] = []
    ordered_meals = [meal for _, meal in meal_labels]
    meal_index = -1
    for cy, category, _ in sorted(category_labels, reverse=True):
        # 각 끼니는 일반식으로 시작하고 이어서 PLUS/간편식/건강식이 나온다.
        # 세로 병합된 끼니명 중앙보다 이 반복 순서가 실제 표 구조를 더 잘 표현한다.
        if category == "일반식" and meal_index + 1 < len(ordered_meals):
            meal_index += 1
        if meal_index >= 0:
            meal = ordered_meals[min(meal_index, len(ordered_meals) - 1)]
        else:
            meal = min(meal_labels, key=lambda item: abs(item[0] - cy))[1]
        labeled_categories.append((cy, category, meal))

    # 끼니명은 세로 병합 셀의 중앙에 있어 단순 최근접 배정 시 중식 특식이
    # 조식으로 올라갈 수 있다. 인접 끼니의 실제 코너 행 사이를 경계로 삼는다.
    meal_boundaries: list[tuple[float, str, str]] = []
    for upper, lower in zip(ordered_meals, ordered_meals[1:]):
        upper_ys = [y for y, _, meal in labeled_categories if meal == upper]
        lower_ys = [y for y, _, meal in labeled_categories if meal == lower]
        if upper_ys and lower_ys:
            margin = 0.09 if len(lower_ys) >= 3 else 0.07
            boundary = max(lower_ys) + margin
        else:
            upper_label = next(y for y, meal in meal_labels if meal == upper)
            lower_label = next(y for y, meal in meal_labels if meal == lower)
            boundary = (upper_label + lower_label) / 2
        meal_boundaries.append((boundary, upper, lower))

    def meal_for_y(y: float) -> str:
        for boundary, upper, _ in meal_boundaries:
            if y >= boundary:
                return upper
        return ordered_meals[-1]

    def category_for_y(meal: str, y: float) -> str:
        categories = sorted(
            [(cy, category) for cy, category, owner in labeled_categories if owner == meal],
            reverse=True,
        )
        if not categories:
            return "일반식"
        for index, (_, category) in enumerate(categories[:-1]):
            lower_y = categories[index + 1][0]
            if y >= lower_y + 0.015:
                return category
        return categories[-1][1]

    cells: dict[tuple[date, str, str], list[tuple[float, str, float]]] = defaultdict(list)
    full_day_texts: dict[date, list[str]] = defaultdict(list)
    meal_exception_texts: dict[tuple[date, str], list[str]] = defaultdict(list)
    excluded = set(MEAL_WORDS) | {k.replace(" ", "") for k in CATEGORIES}
    min_date_x, max_date_x = min(x for x, _ in date_headers), max(x for x, _ in date_headers)

    content_top = min(date_header_ys) - 0.015
    content_bottom = max(0.10, min((y for y, _, _ in labeled_categories), default=0.12) - 0.02)
    for line in lines:
        text = re.sub(r"\s+", " ", line["text"].strip()).strip(" ,")
        if not text or DATE_RE.search(text) or text.replace(" ", "") in excluded:
            continue
        x, y = _center(line)
        if x < max(0.13, min_date_x - 0.12) or x > min(0.99, max_date_x + 0.12) or y < content_bottom or y > content_top:
            continue
        if re.search(r"GREEN\s*FOOD|HYUNDAI|그린미네", text, re.I):
            continue
        day_x, service_day = min(date_headers, key=lambda item: abs(item[0] - x))
        if abs(day_x - x) > 0.13:
            continue
        meal = meal_for_y(y)
        named_meal = next((value for word, value in MEAL_WORDS.items() if word in text), None)
        if FULL_DAY_PATTERNS.search(text):
            full_day_texts[service_day].append(text)
            continue
        if named_meal and NO_SERVICE_PATTERNS.search(text):
            meal_exception_texts[(service_day, named_meal)].append(text)
            continue
        category = category_for_y(meal, y)
        confidence = float(line.get("confidence", 0.0))
        cells[(service_day, meal, category)].append((-y, text, confidence))

    entries: list[MenuEntry] = []
    vocabulary = active_vocabulary()
    for (service_day, meal, category), values in cells.items():
        values.sort()
        # OCR 글자 오인식과 장식 서체에서 끼어든 조각을 여기서 걸러낸다
        # (corrections 참고). 원본 OCR 결과는 <이미지>.ocr.json 캐시에 남아
        # 있으므로 교정 규칙을 고친 뒤 다시 만들 수 있다.
        texts = clean_items([text for _, text, _ in values], vocabulary)
        menu_text = " · ".join(texts)
        if len(menu_text) < 2:
            continue
        # 셰프 협업 배너는 목록에서는 제거하지만 그 배너가 뜻하는 특식 상태는
        # 보존한다. 따라서 사용자는 셰프 이름 대신 `✨ 특식`과 실제 메뉴만 본다.
        has_special_promotion = any(is_promotional_noise(text) for _, text, _ in values)
        status = "no_service" if NO_SERVICE_PATTERNS.search(menu_text) else (
            "special" if has_special_promotion or SPECIAL_PATTERNS.search(menu_text) else "normal"
        )
        entries.append(MenuEntry(
            service_date=service_day,
            location=post.location,
            meal_type=meal,
            category=category,
            menu_text=menu_text,
            status=status,
            source_post_id=post.post_id,
            source_title=post.title,
            source_image_url=image_url,
            confidence=sum(v[2] for v in values) / len(values),
        ))

    # 대체휴무/공휴일처럼 명시적인 전일 휴무만 세 끼 전체에 적용한다.
    for service_day, messages in full_day_texts.items():
        message = " · ".join(dict.fromkeys(messages))
        for meal in ("조식", "중식", "석식"):
            entries.append(MenuEntry(
                service_date=service_day, location=post.location, meal_type=meal,
                category="안내", menu_text=message, status="no_service",
                source_post_id=post.post_id, source_title=post.title,
                source_image_url=image_url, confidence=1.0,
            ))

    # `조식 운영 없음`, `석식 미제공`은 명시된 끼니에만 적용한다.
    for (service_day, meal), messages in meal_exception_texts.items():
        entries.append(MenuEntry(
            service_date=service_day, location=post.location, meal_type=meal,
            category="안내", menu_text=" · ".join(dict.fromkeys(messages)), status="no_service",
            source_post_id=post.post_id, source_title=post.title,
            source_image_url=image_url, confidence=1.0,
        ))
    return entries
