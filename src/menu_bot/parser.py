from __future__ import annotations

from collections import defaultdict
from datetime import date
import re

from .corrections import active_vocabulary, clean_items, is_promotional_noise
from .models import MenuEntry, SourcePost
from .service_notices import INFERRED_SUFFIX, NO_SERVICE_PATTERNS, OPEN_PATTERNS, classify_notice


DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[./]\s*(\d{1,2})(?!\d)")
MEAL_WORDS = {"조식": "조식", "아침": "조식", "중식": "중식", "점심": "중식", "석식": "석식", "저녁": "석식"}
CATEGORIES = {
    "일반식": "일반식", "PLUS코너": "PLUS 코너", "PLUS 코너": "PLUS 코너",
    "PLUS": "PLUS 코너", "간편식": "간편식", "건강식": "건강식",
}
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


def _resolve_date(month: int, day: int, anchor: date) -> date | None:
    candidates = []
    for year in (anchor.year - 1, anchor.year, anchor.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        candidates.append(candidate)
    return min(candidates, key=lambda d: abs((d - anchor).days)) if candidates else None


def _join_notice_fragments(lines: list[dict], date_headers: list[tuple[float, date]]) -> list[dict]:
    """같은 날짜에서 붙어 있는 글자가 알려진 안내를 이룰 때만 합친다."""
    grouped = defaultdict(list)
    for line in lines:
        x, _ = _center(line)
        day = min(date_headers, key=lambda item: abs(item[0] - x))[1]
        grouped[day].append(line)
    joined = []
    for group in grouped.values():
        remaining = sorted(group, key=lambda line: (-_center(line)[1], line['x']))
        while remaining:
            first = remaining.pop(0)
            best = []
            for horizontal in (True, False):
                parts = [first]
                available = list(remaining)
                while len(parts) < 4:
                    last = parts[-1]
                    lx, ly = _center(last)
                    nearby = []
                    for other in available:
                        ox, oy = _center(other)
                        if horizontal:
                            left = min(p['x'] for p in parts)
                            right = max(p['x'] + p['width'] for p in parts)
                            gaps = [gap for gap in (other['x'] - right, left - (other['x'] + other['width'])) if 0 <= gap <= 0.025]
                            adjacent = abs(oy - _center(first)[1]) <= 0.015 and bool(gaps)
                            distance = min(gaps) if gaps else 0
                        else:
                            overlap = min(last['x'] + last['width'], other['x'] + other['width']) - max(last['x'], other['x'])
                            gap = last['y'] - (other['y'] + other['height'])
                            adjacent = overlap > 0 and oy < ly and -0.01 <= gap <= 0.035
                            distance = ly - oy
                        if adjacent:
                            nearby.append((distance, other))
                    if not nearby:
                        break
                    other = min(nearby, key=lambda pair: pair[0])[1]
                    parts.append(other)
                    available.remove(other)
                    ordered = sorted(parts, key=lambda p: p['x']) if horizontal else parts
                    if len(parts) > len(best) and classify_notice(''.join(p['text'] for p in ordered)) is not None:
                        best = list(ordered)
            if best:
                for part in best:
                    if part is not first:
                        remaining.remove(part)
                left = min(p['x'] for p in best)
                bottom = min(p['y'] for p in best)
                joined.append(dict(text=''.join(p['text'] for p in best), x=left, y=bottom,
                                   width=max(p['x'] + p['width'] for p in best) - left,
                                   height=max(p['y'] + p['height'] for p in best) - bottom,
                                   confidence=min(float(p.get('confidence', 0)) for p in best)))
            else:
                joined.append(first)
    return joined


def parse_ocr_lines(post: SourcePost, image_url: str, lines: list[dict]) -> list[MenuEntry]:
    date_headers: list[tuple[float, date]] = []
    date_header_ys: list[float] = []
    for line in lines:
        match = DATE_RE.search(line["text"])
        x, _ = _center(line)
        # 휴무 안내 그림 안의 `8.17` 같은 큰 숫자를 날짜 헤더로 오인하지 않는다.
        if match and line["y"] > 0.78:
            parsed = _resolve_date(int(match.group(1)), int(match.group(2)), post.start_date)
            if parsed is not None and abs((parsed - post.start_date).days) <= 10:
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
    holiday_texts: dict[date, list[str]] = defaultdict(list)
    meal_exception_texts: dict[tuple[date, str], list[str]] = defaultdict(list)
    excluded = set(MEAL_WORDS) | {k.replace(" ", "") for k in CATEGORIES}
    min_date_x, max_date_x = min(x for x, _ in date_headers), max(x for x, _ in date_headers)

    content_top = min(date_header_ys) - 0.015
    content_bottom = max(0.10, min((y for y, _, _ in labeled_categories), default=0.12) - 0.02)
    content_lines = []
    for line in lines:
        x, y = _center(line)
        if x < max(0.13, min_date_x - 0.12) or x > min(0.99, max_date_x + 0.12) or y < content_bottom or y > content_top:
            continue
        content_lines.append(line)

    event_days = set()
    for line in content_lines:
        if SPECIAL_PATTERNS.search(line['text']) or OPEN_PATTERNS.search(line['text']):
            x, _ = _center(line)
            event_days.add(min(date_headers, key=lambda item: abs(item[0] - x))[1])

    for line in _join_notice_fragments(content_lines, date_headers):
        text = re.sub(r"\s+", " ", line["text"].strip()).strip(" ,")
        if not text or text.replace(" ", "") in excluded:
            continue
        x, y = _center(line)
        if re.search(r"GREEN\s*FOOD|HYUNDAI|그린미네", text, re.I):
            continue
        # 날짜가 붙은 안내는 본문의 날짜를 읽는다. 헤더는 위에서 따로 처리했다.
        date_matches = list(DATE_RE.finditer(text))
        short_range = re.search(DATE_RE.pattern + r"\s*[~∼–-]\s*(\d{1,2})(?![\d./])", text)
        notice_text = text[:short_range.start()] + text[short_range.end():] if short_range else text
        if date_matches:
            notice_text = re.sub(DATE_RE.pattern + r"(?:\s*\([월화수목금토일]\))?", "", notice_text)
        notice = classify_notice(notice_text)
        if notice is not None:
            if date_matches:
                specified = [_resolve_date(int(m[1]), int(m[2]), post.start_date) for m in date_matches]
                if short_range:
                    # 끝 날짜의 월을 생략하면 같은 달로 읽는다. 거꾸로 된 범위는 추정하지 않는다.
                    if int(short_range[3]) < int(short_range[2]):
                        continue
                    specified.append(_resolve_date(int(short_range[1]), int(short_range[3]), post.start_date))
                if any(day is None for day in specified):
                    continue
                is_range = short_range is not None or (len(date_matches) == 2 and re.search(r"[~∼–-]", text[date_matches[0].end():date_matches[1].start()]))
                if len(specified) == 2 and is_range:
                    days = [day for _, day in date_headers if min(specified) <= day <= max(specified)]
                else:
                    days = [day for _, day in date_headers if day in specified]
            else:
                days = [day for header_x, day in date_headers if line['x'] <= header_x <= line['x'] + line['width']]
                if not days:
                    header_x, day = min(date_headers, key=lambda item: abs(item[0] - x))
                    days = [day] if abs(header_x - x) <= 0.13 else []
            for service_day in days:
                if notice.meals:
                    for named_meal in notice.meals:
                        meal_exception_texts[(service_day, named_meal)].append(notice_text)
                elif notice.inferred:
                    holiday_texts[service_day].append(notice_text)
                else:
                    full_day_texts[service_day].append(notice_text + INFERRED_SUFFIX)
            continue
        if date_matches:
            continue
        day_x, service_day = min(date_headers, key=lambda item: abs(item[0] - x))
        if abs(day_x - x) > 0.13:
            continue
        meal = meal_for_y(y)
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
        status = "no_service" if NO_SERVICE_PATTERNS.search(menu_text) and not OPEN_PATTERNS.search(menu_text) else (
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

    # 휴일 이름만 있고 음식 메뉴가 없는 날짜는 글자가 놓인 행과 무관하게
    # 전일 휴무다. 실제 음식이 있으면 이름만으로 운영 여부를 바꾸지 않는다.
    menu_days = {entry.service_date for entry in entries if entry.status != "no_service"}
    for service_day, messages in holiday_texts.items():
        if service_day not in menu_days and service_day not in event_days:
            full_day_texts[service_day].extend(text + INFERRED_SUFFIX for text in messages)

    # 대체휴무/공휴일처럼 명시적인 전일 휴무도 세 끼 전체에 적용한다.
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
