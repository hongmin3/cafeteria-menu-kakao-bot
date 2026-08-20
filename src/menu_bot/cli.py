from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from .config import get_settings
from .db import MenuDB
from .next_week_watch import check_next_week_posted
from .pipeline import process_manifest
from .query import answer
from .scraper import GroupwareScraper


def _learning_db_path(database_path: Path) -> Path:
    """--learning 전용 DB 경로. 운영 DB와 절대 같은 파일을 쓰지 않는다."""
    return database_path.with_name(f"{database_path.stem}.learning{database_path.suffix}")


def _use_utf8_console() -> None:
    # Windows 콘솔 기본 코드페이지(cp949 등)는 🍽 같은 이모지를 인코딩하지
    # 못해 print()가 UnicodeEncodeError로 죽는다. reconfigure()가 없는
    # 구버전 Python이나 콘솔이 아닌 스트림에서는 조용히 건너뛴다.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")


def main() -> None:
    _use_utf8_console()
    parser = argparse.ArgumentParser(description="뷰웍스 식단 챗봇 관리 도구")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="JSON 목록의 식단 이미지를 OCR하여 저장")
    ingest.add_argument("manifest", type=Path)
    ingest.add_argument(
        "--learning", action="store_true",
        help="1년치 OCR/파서 검증용으로 모든 날짜를 저장(운영 DB에서는 사용하지 않음)",
    )
    scrape = sub.add_parser("scrape", help="그룹웨어에서 최근 식단 게시물을 수집")
    scrape.add_argument("--pages", type=int, default=2)
    scrape.add_argument("--output", type=Path, default=Path("data/latest_manifest.json"))
    scrape.add_argument("--show-browser", action="store_true")
    ask = sub.add_parser("ask", help="로컬 DB에 식단 질문")
    ask.add_argument("text")
    sub.add_parser(
        "check-next-week",
        help="다음 주 식단표 게시글이 올라왔는지 확인(주말 폴링용, 확인되면 상태 저장 후 종료)",
    )
    args = parser.parse_args()
    settings = get_settings()

    if args.command == "scrape":
        rows = GroupwareScraper(settings, headless=not args.show_browser).collect(args.pages)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{len(rows)}개 게시물을 {args.output}에 저장했습니다.")
    elif args.command == "ingest":
        rows = json.loads(args.manifest.read_text(encoding="utf-8"))
        # --learning은 운영 DB(현재 주만 보관)와 절대 섞이면 안 되므로 항상
        # 별도 파일에 쓴다. 과거 이 구분이 없어 1년치 학습용 데이터가
        # 그대로 운영 DB에 쌓인 적이 있었다(2026-08-20 정리, 백업:
        # data/menus.db.backup-2026-08-20).
        db_path = _learning_db_path(settings.database_path) if args.learning else settings.database_path
        db = MenuDB(db_path)
        try:
            today = datetime.now(ZoneInfo(settings.timezone)).date()
            week_start = None if args.learning else today - timedelta(days=today.weekday())
            stats = process_manifest(rows, db, Path("data/images"), week_start=week_start)
            print(json.dumps(stats, ensure_ascii=False, indent=2))
        finally:
            db.close()
    elif args.command == "ask":
        db = MenuDB(settings.database_path)
        try:
            print(answer(db, args.text, settings.timezone, settings.default_location))
        finally:
            db.close()
    elif args.command == "check-next-week":
        result = check_next_week_posted(settings)
        print(result.message)


if __name__ == "__main__":
    main()

