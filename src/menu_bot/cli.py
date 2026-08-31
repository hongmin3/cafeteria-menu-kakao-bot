from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from .config import get_settings
from .corrections import (
    MIN_VOCAB_COUNT,
    SUBSTITUTIONS,
    USER_CORRECTIONS_HEADER,
    USER_CORRECTIONS_PATH,
    apply_substitutions,
    build_vocabulary,
    load_user_corrections,
    reset_substitutions_cache,
)
from .db import MenuDB
from .next_week_watch import (
    check_next_week_deadline,
    check_next_week_posted,
    ensure_week_menu,
)
from .notify import get_mail_settings, send_mail
from .ocr import recognize
from .parser import parse_ocr_lines, post_from_title
from .pipeline import image_path, process_manifest
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
    ensure = sub.add_parser(
        "ensure-menu",
        help="지금 필요한 주차 식단이 DB에 없으면 다시 수집(1시간 간격 재시도용, 있으면 즉시 종료)",
    )
    ensure.add_argument(
        "--now", metavar="ISO8601",
        help="기준 시각을 지정해 재시도 시나리오를 검증. 시스템 시계는 건드리지 않는다.",
    )
    sub.add_parser(
        "notify-test",
        help="알림 메일 설정이 실제로 동작하는지 시험 메일 1통으로 확인(비밀번호는 출력하지 않음)",
    )
    vocab = sub.add_parser(
        "build-vocab",
        help="OCR 오인식 교정에 쓸 메뉴 이름 어휘집을 만든다(실제 메뉴 데이터이므로 저장소에 넣지 않음)",
    )
    vocab.add_argument("manifest", type=Path, help="어휘를 모을 게시물 목록 JSON")
    vocab.add_argument("--image-dir", type=Path, default=Path("data/images"))
    vocab.add_argument("--output", type=Path, default=Path("data/menu_vocab.json"))

    correct = sub.add_parser(
        "correct",
        help="메뉴 표기 교정 목록을 관리한다(코드 수정·배포 없이 그 자리에서)",
    )
    correct_sub = correct.add_subparsers(dest="correct_command", required=True)
    correct_add = correct_sub.add_parser("add", help="교정 규칙 하나를 추가한다")
    correct_add.add_argument("wrong", help="잘못 읽힌 표기 (예: 누륭지)")
    correct_add.add_argument("right", help="올바른 표기 (예: 누룽지)")
    correct_add.add_argument(
        "--apply", action="store_true",
        help="추가한 뒤 이미 저장된 식단에도 곧바로 반영한다",
    )
    correct_sub.add_parser("list", help="지금 적용 중인 교정 목록을 보여준다")
    correct_test = correct_sub.add_parser("test", help="교정 결과를 미리 본다(저장하지 않음)")
    correct_test.add_argument("text", help="확인할 문구 (예: 누륭지닭곰탕)")
    correct_sub.add_parser(
        "apply", help="이미 저장된 식단에 지금 교정 목록을 다시 입힌다(OCR 재실행 없음)",
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
    elif args.command == "ensure-menu":
        result = ensure_week_menu(settings, now=_parse_now(args.now, settings.timezone))
        print(result.message)
        # 아직 게시글이 없는 것은 이상 상황이 아니므로 0으로 끝낸다(한 시간 뒤 다시
        # 시도한다). 접속 실패나 OCR 0건만 systemd가 실패로 잡도록 1로 끝낸다.
        if result.error:
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
    elif args.command == "build-vocab":
        # 어휘집을 만드는 동안에는 어휘집 교정 자체를 끈다. 안 그러면 직전
        # 어휘집을 근거로 값을 고친 뒤 그 결과로 새 어휘집을 만드는 꼴이 된다.
        os.environ["MENU_VOCAB_PATH"] = str(args.output.with_name("__no_vocab__.json"))
        rows = json.loads(args.manifest.read_text(encoding="utf-8"))
        items: list[str] = []
        images = 0
        for row in rows:
            urls = [im["src"] if isinstance(im, dict) else im for im in row.get("images", [])]
            try:
                post = post_from_title(row["id"], row["title"], urls)
            except ValueError:
                continue
            for url in urls:
                path = image_path(url, args.image_dir)
                if not path.exists() or not path.with_suffix(path.suffix + ".ocr.json").exists():
                    continue
                images += 1
                for entry in parse_ocr_lines(post, url, recognize(path)):
                    items.extend(part.strip() for part in entry.menu_text.split(" · ") if part.strip())
        vocabulary = build_vocabulary(items)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(vocabulary, ensure_ascii=False, indent=0), encoding="utf-8")
        frequent = sum(1 for count in vocabulary.values() if count >= MIN_VOCAB_COUNT)
        print(
            f"이미지 {images}장에서 메뉴 이름 {len(vocabulary)}종(총 {sum(vocabulary.values())}회)을 모아 "
            f"{args.output}에 저장했습니다. 교정 후보로 쓰이는 {MIN_VOCAB_COUNT}회 이상 항목은 {frequent}종입니다."
        )
    elif args.command == "correct":
        _run_correct(args, settings)


def _corrections_file() -> Path:
    return Path(os.getenv("MENU_CORRECTIONS_PATH") or USER_CORRECTIONS_PATH)


def _reapply(settings) -> int:
    """저장된 식단에 지금 교정 목록을 다시 입히고 바뀐 건수를 알려 준다."""
    reset_substitutions_cache()
    db = MenuDB(settings.database_path)
    try:
        changed = db.reapply_corrections(apply_substitutions)
    finally:
        db.close()
    for before, after in changed[:20]:
        print(f"  {before}\n  → {after}")
    if len(changed) > 20:
        print(f"  … 외 {len(changed) - 20}건")
    print(f"저장된 식단 {len(changed)}건을 고쳤습니다.")
    return len(changed)


def _run_correct(args, settings) -> None:
    path = _corrections_file()
    if args.correct_command == "add":
        wrong, right = args.wrong.strip(), args.right.strip()
        if not wrong or not right:
            sys.exit("잘못된 표기와 올바른 표기를 모두 적어야 합니다.")
        if wrong == right:
            sys.exit("두 표기가 같습니다. 고칠 것이 없습니다.")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(USER_CORRECTIONS_HEADER, encoding="utf-8")
        existing = load_user_corrections(path)
        if existing.get(wrong) == right:
            print(f"이미 있는 규칙입니다: {wrong} = {right}")
        else:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"{wrong} = {right}\n")
            print(f"추가했습니다: {wrong} = {right}  ({path})")
            if wrong in existing:
                print(f"  주의: 같은 표기에 대한 이전 규칙({existing[wrong]})을 덮어씁니다.")
        # 넓게 적용되는 짧은 규칙은 다른 메뉴까지 바꿀 수 있으니 미리 알린다.
        if len(wrong) <= 2:
            print(
                f"  주의: '{wrong}'은(는) 짧아서 다른 메뉴 이름에도 들어갈 수 있습니다. "
                "의도치 않게 바뀌는 것이 있는지 `menu-bot correct apply` 결과를 확인하세요."
            )
        if args.apply:
            _reapply(settings)
        else:
            print("이미 저장된 식단에도 반영하려면: menu-bot correct apply")
    elif args.correct_command == "list":
        user = load_user_corrections(path)
        print(f"코드에 고정된 규칙 {len(SUBSTITUTIONS)}건, 직접 추가한 규칙 {len(user)}건 ({path})")
        for wrong, right in user.items():
            overrides = " (코드 목록을 덮어씀)" if wrong in SUBSTITUTIONS else ""
            print(f"  {wrong} = {right}{overrides}")
        if not user:
            print("  (아직 직접 추가한 규칙이 없습니다)")
    elif args.correct_command == "test":
        reset_substitutions_cache()
        fixed = apply_substitutions(args.text)
        print(f"{args.text}\n→ {fixed}" + ("   (바뀌는 것 없음)" if fixed == args.text else ""))
    elif args.correct_command == "apply":
        _reapply(settings)


if __name__ == "__main__":
    main()

