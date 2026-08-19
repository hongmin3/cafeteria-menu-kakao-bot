from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import platform
import subprocess


class OCRProvider(ABC):
    """OCR 결과를 parser.py가 기대하는 좌표계로 정규화해 반환한다.

    각 라인은 {"text", "confidence", "x", "y", "width", "height"} 딕셔너리다.
    x, y, width, height는 0~1로 정규화되며 원점은 이미지 좌측 하단, y축은 위로
    증가한다(Apple Vision과 동일한 규약). 즉 line["y"]는 글자 박스 아랫변의
    위치이고 line["y"] + line["height"]가 윗변이다.
    """

    @abstractmethod
    def recognize(self, image_path: Path) -> list[dict]:
        raise NotImplementedError


class AppleVisionOCRProvider(OCRProvider):
    """macOS 전용: Apple Vision을 사용하는 Swift 바이너리를 통해 OCR."""

    def _binary_path(self) -> Path:
        return Path(".cache/vision_ocr")

    def _ensure_binary(self) -> Path:
        binary = self._binary_path()
        source = Path(__file__).with_name("vision_ocr.swift")
        binary.parent.mkdir(parents=True, exist_ok=True)
        if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
            subprocess.run(
                ["xcrun", "swiftc", str(source), "-o", str(binary)],
                check=True,
                timeout=180,
            )
        return binary

    def recognize(self, image_path: Path) -> list[dict]:
        import json

        completed = subprocess.run(
            [str(self._ensure_binary()), str(image_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return json.loads(completed.stdout)


class PaddleOCRProvider(OCRProvider):
    """Windows 전용: 로컬 CPU에서 실행되는 PaddleOCR 한국어 모델로 OCR.

    PaddleOCR은 이미지 좌측 상단을 원점으로 픽셀 좌표를 반환하므로, Apple
    Vision과 동일한 좌측 하단 원점 정규화 좌표로 변환한다.
    """

    def __init__(self) -> None:
        self._engine = None

    def _ensure_engine(self):
        if self._engine is None:
            from paddleocr import PaddleOCR

            # 감지/인식 모델명을 둘 다 명시해야 한다. 하나만 지정하면 lang=
            # 파라미터가 무시되어 한글을 지원하지 않는 기본 인식 모델로
            # 조용히 전환된다(한글이 전부 빈 문자열로 인식됨). PP-OCRv5
            # server 감지 모델은 이 CPU의 oneDNN 실행 경로에서
            # `ConvertPirAttribute2RuntimeAttribute` 오류로 죽어 mobile
            # 감지 모델과 enable_mkldnn=False로 우회한다.
            self._engine = PaddleOCR(
                text_detection_model_name="PP-OCRv5_mobile_det",
                text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                enable_mkldnn=False,
            )
        return self._engine

    def recognize(self, image_path: Path) -> list[dict]:
        from PIL import Image

        engine = self._ensure_engine()
        with Image.open(image_path) as img:
            img_width, img_height = img.size

        results = engine.predict(str(image_path))
        lines: list[dict] = []
        for result in results:
            texts = result.get("rec_texts") or []
            scores = result.get("rec_scores") or []
            boxes = result.get("rec_boxes")
            if boxes is None:
                boxes = result.get("dt_polys") or result.get("rec_polys") or []
            for index, text in enumerate(texts):
                if not text.strip():
                    continue
                box = boxes[index]
                x_min, y_min, x_max, y_max = _box_to_rect(box)
                width_px = x_max - x_min
                height_px = y_max - y_min
                x_norm = x_min / img_width
                y_top_norm = y_min / img_height
                w_norm = width_px / img_width
                h_norm = height_px / img_height
                lines.append({
                    "text": text,
                    "confidence": float(scores[index]) if index < len(scores) else 0.0,
                    "x": x_norm,
                    "y": 1 - y_top_norm - h_norm,
                    "width": w_norm,
                    "height": h_norm,
                })
        return lines


def _box_to_rect(box) -> tuple[float, float, float, float]:
    """rec_boxes([x1,y1,x2,y2], numpy 스칼라 포함) 또는 dt_polys(4점 폴리곤) 모두
    받아 axis-aligned rect로 변환한다."""
    items = list(box)
    if len(items) == 4 and not any(hasattr(v, "__len__") for v in items):
        x1, y1, x2, y2 = (float(v) for v in items)
        return x1, y1, x2, y2
    xs = [float(point[0]) for point in items]
    ys = [float(point[1]) for point in items]
    return min(xs), min(ys), max(xs), max(ys)


def get_provider(name: str = "auto") -> OCRProvider:
    resolved = name if name != "auto" else ("apple_vision" if platform.system() == "Darwin" else "paddleocr")
    if resolved == "apple_vision":
        return AppleVisionOCRProvider()
    if resolved == "paddleocr":
        return PaddleOCRProvider()
    raise ValueError(f"알 수 없는 OCR_PROVIDER 값: {name}")
