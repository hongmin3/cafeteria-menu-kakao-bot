from __future__ import annotations

import json
from pathlib import Path

from .config import get_settings
from .ocr_provider import OCRProvider, get_provider


_provider: OCRProvider | None = None


def _active_provider() -> OCRProvider:
    global _provider
    if _provider is None:
        _provider = get_provider(get_settings().ocr_provider)
    return _provider


def recognize(image_path: Path) -> list[dict]:
    cache = image_path.with_suffix(image_path.suffix + ".ocr.json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    result = _active_provider().recognize(image_path)
    cache.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result
