from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import get_settings
from .db import MenuDB
from .pipeline import process_manifest
from .query import answer
from .scraper import GroupwareScraper


def main() -> None:
    parser = argparse.ArgumentParser(description="뷰웍스 식단 챗봇 관리 도구")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="JSON 목록의 식단 이미지를 OCR하여 저장")
    ingest.add_argument("manifest", type=Path)
    scrape = sub.add_parser("scrape", help="그룹웨어에서 최근 식단 게시물을 수집")
    scrape.add_argument("--pages", type=int, default=2)
    scrape.add_argument("--output", type=Path, default=Path("data/latest_manifest.json"))
    scrape.add_argument("--show-browser", action="store_true")
    ask = sub.add_parser("ask", help="로컬 DB에 식단 질문")
    ask.add_argument("text")
    args = parser.parse_args()
    settings = get_settings()

    if args.command == "scrape":
        rows = GroupwareScraper(settings, headless=not args.show_browser).collect(args.pages)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{len(rows)}개 게시물을 {args.output}에 저장했습니다.")
    elif args.command == "ingest":
        rows = json.loads(args.manifest.read_text(encoding="utf-8"))
        db = MenuDB(settings.database_path)
        try:
            stats = process_manifest(rows, db, Path("data/images"))
            print(json.dumps(stats, ensure_ascii=False, indent=2))
        finally:
            db.close()
    elif args.command == "ask":
        db = MenuDB(settings.database_path)
        try:
            print(answer(db, args.text, settings.timezone, settings.default_location))
        finally:
            db.close()


if __name__ == "__main__":
    main()


