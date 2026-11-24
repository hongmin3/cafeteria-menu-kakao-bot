from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

import requests

from .advisor import advise
from .atomic import write_bytes
from .db import MenuDB
from .models import MenuEntry
from .ocr import recognize
from .parser import parse_ocr_lines, post_from_title
from .service_notices import is_inferred_notice


def image_path(url: str, image_dir: Path) -> Path:
    """이미지 URL이 저장되는 경로. 다운로드와 어휘집 생성이 같은 규칙을 써야 한다."""
    parts = urlsplit(url)
    filenames = parse_qs(parts.query).get("fileName")
    suffix = Path(filenames[0] if filenames else parts.path).suffix
    if not re.fullmatch(r"\.[a-zA-Z0-9]{1,8}", suffix):
        suffix = ".img"
    return image_dir / (hashlib.sha256(url.encode()).hexdigest()[:24] + suffix)


def _download(url: str, image_dir: Path) -> Path:
    path = image_path(url, image_dir)
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    content = response.content
    html = content[:128].lstrip().lower().startswith((b"<!doctype html", b"<html"))
    if not content or html or content_type.startswith("text/") or content_type == "application/json":
        raise ValueError("첨부 파일이 이미지가 아닙니다.")
    if not path.exists() or path.read_bytes() != content:
        write_bytes(path, content)
    return path


def filter_entries_to_week(entries: list[MenuEntry], week_start: date) -> tuple[list[MenuEntry], int]:
    week_end = week_start + timedelta(days=6)
    selected = [entry for entry in entries if week_start <= entry.service_date <= week_end]
    return selected, len(entries) - len(selected)


def process_manifest(
    rows: list[dict], db: MenuDB, image_dir: Path, progress=print, week_start: date | None = None,
    use_advisor: bool = True,
) -> dict:
    stats = {
        "posts": 0, "images": 0, "entries": 0, "filtered_entries": 0,
        "skipped_images": 0, "errors": [],
    }
    for index, row in enumerate(rows, 1):
        try:
            if row.get("collection_error"):
                raise ValueError(row["collection_error"])
            urls = [image["src"] if isinstance(image, dict) else image for image in row.get("images", [])]
            post = post_from_title(row["id"], row["title"], urls)
            all_entries: list[MenuEntry] = []
            for url in urls:
                path = image_path(url, image_dir)
                if week_start is not None or not path.exists():
                    path = _download(url, image_dir)
                lines = recognize(path)
                # 이상 신호가 있을 때만 Claude에게 그림을 보여 주고 묻는다(REQ-ADV-001).
                parsed = parse_ocr_lines(post, url, lines)
                if use_advisor:
                    parsed = advise(post, path, lines, parsed, progress=progress)
                stats["images"] += 1
                if parsed:
                    all_entries.extend(parsed)
                else:
                    stats["skipped_images"] += 1
            # 여러 첨부 중 음식이 있는 날짜는 이름만으로 만든 휴무 안내를 제외한다.
            menu_days = {(e.service_date, e.location) for e in all_entries if e.status != 'no_service'}
            all_entries = [e for e in all_entries if
                           (e.service_date, e.location) not in menu_days or not is_inferred_notice(e)]
            # 같은 이미지/겹친 레이아웃의 중복은 가장 긴 OCR 결과를 남긴다.
            best: dict[tuple, MenuEntry] = {}
            for entry in all_entries:
                key = (entry.service_date, entry.location, entry.meal_type, entry.category)
                if key not in best or len(entry.menu_text) > len(best[key].menu_text):
                    best[key] = entry
            selected_entries = list(best.values())
            if week_start is not None:
                selected_entries, filtered = filter_entries_to_week(selected_entries, week_start)
                stats["filtered_entries"] += filtered
            if not selected_entries:
                continue
            db.save_week(post, selected_entries, week_start)
            stats["posts"] += 1
            stats["entries"] += len(selected_entries)
            progress(f"[{index}/{len(rows)}] {post.title}: {len(selected_entries)}개 메뉴")
        except Exception as exc:
            stats["errors"].append({"title": row.get("title"), "error": str(exc)})
            progress(f"[{index}/{len(rows)}] 오류: {row.get('title')} — {exc}")
    return stats
