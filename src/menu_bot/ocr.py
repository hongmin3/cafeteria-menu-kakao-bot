from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import logging
import math
import os
from pathlib import Path
import platform

from .atomic import write_bytes
from .config import get_settings
from .ocr_provider import AppleVisionOCRProvider, OCRProvider, PaddleOCRProvider, get_provider


_provider: OCRProvider | None = None
logger = logging.getLogger(__name__)


def _active_provider() -> OCRProvider:
    global _provider
    if _provider is None:
        _provider = get_provider(get_settings().ocr_provider)
    return _provider


def recognize(image_path: Path) -> list[dict]:
    cache = image_path.with_suffix(image_path.suffix + ".ocr.json")
    provider = _active_provider()
    key = _cache_key(image_path, provider)
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if isinstance(saved, dict) and saved.get("key") == key and _valid_lines(saved.get("lines")):
            return saved["lines"]
        if _valid_lines(saved) and cache.stat().st_mtime_ns >= image_path.stat().st_mtime_ns:
            _record_cache(cache, key, saved)
            return saved
    except (OSError, ValueError):
        pass

    result = provider.recognize(image_path)
    if _valid_lines(result):
        _record_cache(cache, key, result)
    return result


def _cache_key(image_path: Path, provider: OCRProvider) -> str:
    signature = [type(provider).__name__]
    if isinstance(provider, PaddleOCRProvider):
        for package in ("paddleocr", "paddlepaddle"):
            try:
                signature.append(version(package))
            except PackageNotFoundError:
                signature.append("")
        signature.extend(os.getenv(key, "") for key in (
            "PADDLE_DET_MODEL", "PADDLE_REC_MODEL", "PADDLE_ENABLE_MKLDNN",
        ))
    elif isinstance(provider, AppleVisionOCRProvider):
        signature.extend((platform.mac_ver()[0], hashlib.sha256(
            Path(__file__).with_name("vision_ocr.swift").read_bytes(),
        ).hexdigest()))
    digest = hashlib.sha256(json.dumps([1, signature]).encode("utf-8"))
    with image_path.open("rb") as image:
        digest.update(hashlib.file_digest(image, "sha256").digest())
    return digest.hexdigest()


def _valid_lines(lines) -> bool:
    return isinstance(lines, list) and bool(lines) and all(
        isinstance(line, dict) and isinstance(line.get("text"), str) and all(
            isinstance(value, (int, float)) and math.isfinite(value)
            for value in (line.get("x"), line.get("y"), line.get("width"), line.get("height"),
                          line.get("confidence", 0.0))
        )
        for line in lines
    )


def _record_cache(path: Path, key: str, lines: list[dict]) -> None:
    try:
        write_bytes(path, json.dumps({"key": key, "lines": lines}, ensure_ascii=False).encode("utf-8"))
    except OSError:
        logger.warning("OCR 결과 캐시를 저장하지 못했습니다. 인식 결과는 계속 처리합니다.")
