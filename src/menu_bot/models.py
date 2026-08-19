from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class SourcePost:
    post_id: str
    title: str
    location: str
    start_date: date
    image_urls: list[str] = field(default_factory=list)


@dataclass
class MenuEntry:
    service_date: date
    location: str
    meal_type: str
    category: str
    menu_text: str
    status: str = "normal"
    source_post_id: str = ""
    source_title: str = ""
    source_image_url: str = ""
    confidence: float = 0.0


