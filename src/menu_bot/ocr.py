from __future__ import annotations

import json
from pathlib import Path
import subprocess


def _binary_path() -> Path:
    return Path(".cache/vision_ocr")


def ensure_ocr_binary() -> Path:
    binary = _binary_path()
    source = Path(__file__).with_name("vision_ocr.swift")
    binary.parent.mkdir(parents=True, exist_ok=True)
    if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
        subprocess.run(
            ["xcrun", "swiftc", str(source), "-o", str(binary)],
            check=True,
            timeout=180,
        )
    return binary


def recognize(image_path: Path) -> list[dict]:
    cache = image_path.with_suffix(image_path.suffix + ".ocr.json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    completed = subprocess.run(
        [str(ensure_ocr_binary()), str(image_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    result = json.loads(completed.stdout)
    cache.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result

