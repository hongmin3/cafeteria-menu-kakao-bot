from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from .config import get_settings
from .db import MenuDB
from .next_week_watch import check_next_week_deadline, check_next_week_posted
from .notify import get_mail_settings, send_mail
from .pipeline import process_manifest
from .query import answer
from .scraper import GroupwareScraper


def _learning_db_path(database_path: Path) -> Path:
    """--learning 전용 DB 경로. 운영 DB와 절대 같은 파일을 쓰지 않는다."""
    return database_path.with_name(f"{database_path.stem}.learning{database_path.suffix}")


def _parse_now(value: str | None, timezone: str) -> datetime | None:
    """--now로 받은 시각을 해석한다.

    주말 시나리오(다음 주 게시글 유무, 마감 미확보)를 실제로 검증하려면 기준
    시각을 옮겨야 하는데, 서버 시스템 시계를 건드리면 같은 장비의 다른 서비스
    로그와 DB 타임스탬프가 전부 어긋난다. 그래서 시계 대신 이 인자로 기준
    시각만 주입한다. 시간대를 생략하면 TIMEZONE 설정값으로 본다.
    """
    if not value:
        return None
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo(timezone))
    return moment


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
    check_next = sub.add_parser(
        "check-next-week",
        help="다음 주 식단표 게시글이 올라왔는지 확인(주말 폴링용, 확인되면 상태 저장 후 종료)",
    )
    check_next.add_argument(
        "--now", metavar="ISO8601",
        help="기준 시각을 지정해 주말 시나리오를 검증(예: 2026-08-22T02:05). 시스템 시계는 건드리지 않는다.",
    )
    deadline = sub.add_parser(
        "next-week-deadline",
        help="주말 폴링 마감(일요일 22시) 시점에 다음 주 식단 확보 여부를 판정하고, 미확보면 알림 메일 발송",
    )
    deadline.add_argument(
        "--now", metavar="ISO8601",
        help="기준 시각을 지정해 마감 시나리오를 검증. 시스템 시계는 건드리지 않는다.",
    )
    sub.add_parser(
        "notify-test",
        help="알림 메일 설정이 실제로 동작하는지 시험 메일 1통으로 확인(비밀번호는 출력하지 않음)",
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
        result = check_next_week_posted(settings, now=_parse_now(args.now, settings.timezone))
        print(result.message)
        # 게시글이 아직 없는 것(not_posted)은 정상이므로 0으로 끝낸다. 접속 실패나
        # OCR 0건은 systemd가 실패로 잡아 journal에 남도록 1로 끝낸다.
        if result.error:
            sys.exit(1)
    elif args.command == "next-week-deadline":
        result = check_next_week_deadline(settings, now=_parse_now(args.now, settings.timezone))
        print(result.message)
        # 미확보 상태로 마감된 것은 사람이 봐야 하는 사건이므로 실패로 표시한다.
        # 이미 알림을 보낸 주차는 조용히 0으로 끝낸다.
        if not result.confirmed and not result.already_alerted:
            sys.exit(1)
    elif args.command == "notify-test":
        mail = get_mail_settings()
        if not mail.configured:
            print(f"알림 메일 설정이 비어 있습니다. .env의 {', '.join(mail.missing)}를 채우세요.")
            print("Gmail 앱 비밀번호는 scripts/set-smtp-password.py 로 안전하게 넣을 수 있습니다.")
            sys.exit(1)
        print(f"발송 시도: {mail.host}:{mail.port} ({mail.security}) → {', '.join(mail.recipients)}")
        now = datetime.now(ZoneInfo(settings.timezone))
        ok = send_mail(
            "[뷰밥 메뉴 알리미] 알림 메일 발송 시험",
            "이 메일이 보이면 알림 경로가 정상입니다.\n\n"
            f"발송 시각 : {now:%Y-%m-%d %H:%M} ({settings.timezone})\n"
            f"보낸 서버 : {mail.host}:{mail.port} ({mail.security})\n\n"
            "앞으로 받게 되는 알림은 두 종류입니다.\n"
            "  1) 주말에 다음 주 식단 수집이 성공하면 — 저장된 식단 구조 전체\n"
            "  2) 일요일 22시까지 못 받았으면 — 시도 요약과 실패 사유\n",
            mail=mail,
        )
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

