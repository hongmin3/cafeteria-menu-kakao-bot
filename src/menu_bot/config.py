from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    groupware_user: str
    groupware_password: str
    groupware_url: str
    post_prefixes: tuple[str, ...]
    default_location: str
    database_path: Path
    timezone: str
    webhook_token: str
    ocr_provider: str
    next_week_state_path: Path
    browser_channel: str = "auto"


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        groupware_user=os.getenv("GROUPWARE_USER", ""),
        groupware_password=os.getenv("GROUPWARE_PASSWORD", ""),
        groupware_url=os.getenv("GROUPWARE_URL", ""),
        post_prefixes=tuple(
            item.strip() for item in os.getenv("POST_PREFIXES", "뷰웍스,안양,화성,평촌").split(",")
            if item.strip()
        ),
        default_location=os.getenv("DEFAULT_LOCATION", "").strip(),
        database_path=Path(os.getenv("DATABASE_PATH", "data/menus.db")),
        timezone=os.getenv("TIMEZONE", "Asia/Seoul"),
        webhook_token=os.getenv("KAKAO_WEBHOOK_TOKEN", "").strip(),
        # "auto"(플랫폼 자동 감지) | "apple_vision" | "paddleocr"
        ocr_provider=os.getenv("OCR_PROVIDER", "auto").strip().lower(),
        next_week_state_path=Path(os.getenv("NEXT_WEEK_STATE_PATH", "data/next_week_watch_state.json")),
        # Playwright가 띄울 브라우저. "auto"는 Google Chrome이 설치된 데스크톱
        # (macOS/Windows)에서는 chrome 채널을, Chrome이 없는 Linux 서버에서는
        # Playwright 번들 Chromium("")을 쓴다. 특정 채널을 강제하려면
        # BROWSER_CHANNEL=chrome|msedge|chromium 처럼 지정한다.
        browser_channel=(os.getenv("BROWSER_CHANNEL") or "").strip().lower() or "auto",
    )
