from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

from .models import MenuEntry, SourcePost


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS source_posts (
  post_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  location TEXT NOT NULL,
  start_date TEXT NOT NULL,
  image_urls_json TEXT NOT NULL,
  processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS menu_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service_date TEXT NOT NULL,
  location TEXT NOT NULL,
  meal_type TEXT NOT NULL,
  category TEXT NOT NULL,
  menu_text TEXT NOT NULL,
  status TEXT NOT NULL,
  source_post_id TEXT NOT NULL,
  source_title TEXT NOT NULL,
  source_image_url TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  UNIQUE(service_date, location, meal_type, category, source_post_id)
);
CREATE INDEX IF NOT EXISTS idx_menu_lookup
ON menu_entries(service_date, location, meal_type);
"""


class MenuDB:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def save_post(self, post: SourcePost) -> None:
        import json

        self.conn.execute(
            """INSERT INTO source_posts(post_id,title,location,start_date,image_urls_json)
               VALUES(?,?,?,?,?)
               ON CONFLICT(post_id) DO UPDATE SET
                 title=excluded.title, location=excluded.location,
                 start_date=excluded.start_date,
                 image_urls_json=excluded.image_urls_json,
                 processed_at=CURRENT_TIMESTAMP""",
            (
                post.post_id,
                post.title,
                post.location,
                post.start_date.isoformat(),
                json.dumps(post.image_urls, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def replace_entries(self, post_id: str, entries: list[MenuEntry]) -> None:
        self.conn.execute("DELETE FROM menu_entries WHERE source_post_id=?", (post_id,))
        self.conn.executemany(
            """INSERT INTO menu_entries(
                 service_date,location,meal_type,category,menu_text,status,
                 source_post_id,source_title,source_image_url,confidence
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    e.service_date.isoformat(), e.location, e.meal_type, e.category,
                    e.menu_text, e.status, e.source_post_id, e.source_title,
                    e.source_image_url, e.confidence,
                )
                for e in entries
            ],
        )
        self.conn.commit()

    def query(self, day: date, meal_type: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM menu_entries WHERE service_date=?"
        params: list[str] = [day.isoformat()]
        if meal_type:
            sql += " AND meal_type=?"
            params.append(meal_type)
        sql += " ORDER BY location, CASE meal_type WHEN '조식' THEN 1 WHEN '중식' THEN 2 ELSE 3 END, id"
        return list(self.conn.execute(sql, params))

    def count_entries(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM menu_entries").fetchone()[0])


