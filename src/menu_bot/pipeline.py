from __future__ import annotations

import hashlib
from pathlib import Path
import requests

from .db import MenuDB
from .models import MenuEntry
from .ocr import recognize
from .parser import parse_ocr_lines, post_from_title


def _download(url: str, image_dir: Path) -> Path:
    suffix = Path(url.split("fileName=")[-1]).suffix or ".img"
    path = image_dir / (hashlib.sha256(url.encode()).hexdigest()[:24] + suffix)
    if not path.exists():
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
    return path


def process_manifest(rows: list[dict], db: MenuDB, image_dir: Path, progress=print) -> dict:
    stats = {"posts": 0, "images": 0, "entries": 0, "skipped_images": 0, "errors": []}
    for index, row in enumerate(rows, 1):
        try:
            urls = [image["src"] if isinstance(image, dict) else image for image in row.get("images", [])]
            post = post_from_title(row["id"], row["title"], urls)
            all_entries: list[MenuEntry] = []
            for url in urls:
                path = _download(url, image_dir)
                parsed = parse_ocr_lines(post, url, recognize(path))
                stats["images"] += 1
                if parsed:
                    all_entries.extend(parsed)
                else:
                    stats["skipped_images"] += 1
            # 같은 이미지/겹친 레이아웃의 중복은 가장 긴 OCR 결과를 남긴다.
            best: dict[tuple, MenuEntry] = {}
            for entry in all_entries:
                key = (entry.service_date, entry.location, entry.meal_type, entry.category)
                if key not in best or len(entry.menu_text) > len(best[key].menu_text):
                    best[key] = entry
            db.save_post(post)
            db.replace_entries(post.post_id, list(best.values()))
            stats["posts"] += 1
            stats["entries"] += len(best)
            progress(f"[{index}/{len(rows)}] {post.title}: {len(best)}개 메뉴")
        except Exception as exc:
            stats["errors"].append({"title": row.get("title"), "error": str(exc)})
            progress(f"[{index}/{len(rows)}] 오류: {row.get('title')} — {exc}")
    return stats


