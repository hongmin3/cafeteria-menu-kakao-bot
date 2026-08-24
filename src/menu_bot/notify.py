from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from email.message import EmailMessage
from email.utils import formatdate
import os
import smtplib
import ssl

from dotenv import load_dotenv

from .db import MenuDB


WEEKDAY_KO = "월화수목금토일"
MEAL_ORDER = ("조식", "중식", "석식")

ATTEMPT_LABELS = {
    "not_posted": "게시글이 아직 없음",
    "error": "그룹웨어 접속/스크래핑 실패",
    "ingest_failed": "게시글은 있는데 OCR·파싱 결과가 0건",
    "not_servable": "저장은 됐지만 공통 식단을 고를 수 없음",
    "confirmed": "수집 성공",
}


@dataclass(frozen=True)
class MailSettings:
    """SMTP 설정. 비밀번호는 .env에만 두고 어디에도 출력하지 않는다."""

    host: str
    port: int
    user: str
    password: str
    security: str  # "starttls" | "ssl" | "none"
    sender: str
    recipients: tuple[str, ...]
    timeout: int

    @property
    def missing(self) -> tuple[str, ...]:
        """발송에 반드시 필요한데 비어 있는 항목. 값이 아니라 키 이름만 돌려준다."""
        gaps = []
        if not self.host:
            gaps.append("SMTP_HOST")
        if not self.recipients:
            gaps.append("NOTIFY_EMAIL_TO")
        # 인증이 필요한 서버(Gmail 등)에 계정만 있고 비밀번호가 없으면 반드시
        # 실패한다. 매번 인증 오류를 내는 대신 미설정으로 보고 건너뛴다.
        if self.user and not self.password:
            gaps.append("SMTP_PASSWORD")
        if not self.sender and not self.user:
            gaps.append("NOTIFY_EMAIL_FROM")
        return tuple(gaps)

    @property
    def configured(self) -> bool:
        return not self.missing


def get_mail_settings() -> MailSettings:
    load_dotenv()

    def value(name: str, default: str = "") -> str:
        return (os.getenv(name) or "").strip() or default

    user = value("SMTP_USER")
    security = value("SMTP_SECURITY", "starttls").lower()
    if security not in {"starttls", "ssl", "none"}:
        security = "starttls"
    return MailSettings(
        host=value("SMTP_HOST"),
        port=int(value("SMTP_PORT", "465" if security == "ssl" else "587")),
        user=user,
        password=os.getenv("SMTP_PASSWORD") or "",
        security=security,
        sender=value("NOTIFY_EMAIL_FROM", user),
        recipients=tuple(
            item.strip() for item in value("NOTIFY_EMAIL_TO").split(",") if item.strip()
        ),
        timeout=int(value("SMTP_TIMEOUT", "30")),
    )


def send_mail(subject: str, body: str, mail: MailSettings | None = None, progress=print) -> bool:
    """알림 메일을 보낸다. 성공하면 True.

    이 함수는 예외를 밖으로 내보내지 않는다. 알림이 실패했다고 수집
    파이프라인까지 죽으면 안 되기 때문이다. 대신 사유를 progress로 남기고
    False를 돌려주니, 호출부가 종료 코드에 반영할지 판단한다.
    """
    mail = mail or get_mail_settings()
    if not mail.configured:
        progress(f"알림 메일 설정이 비어 있어 발송을 건너뜁니다(.env의 {', '.join(mail.missing)}).")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = mail.sender or mail.user or "menu-bot@localhost"
    message["To"] = ", ".join(mail.recipients)
    message["Date"] = formatdate(localtime=True)
    message.set_content(body)

    try:
        if mail.security == "ssl":
            server = smtplib.SMTP_SSL(
                mail.host, mail.port, timeout=mail.timeout, context=ssl.create_default_context()
            )
        else:
            server = smtplib.SMTP(mail.host, mail.port, timeout=mail.timeout)
        with server:
            server.ehlo()
            if mail.security == "starttls":
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if mail.user and mail.password:
                server.login(mail.user, mail.password)
            server.send_message(message)
    except Exception as exc:  # noqa: BLE001 - 알림 실패가 수집을 막으면 안 된다
        # 예외 타입과 메시지만 남긴다. 비밀번호 값은 어떤 경로로도 찍지 않는다.
        progress(f"알림 메일 발송 실패: {type(exc).__name__}: {exc}")
        return False
    progress(f"알림 메일을 보냈습니다: {', '.join(mail.recipients)}")
    return True


def _label(day: date) -> str:
    return f"{day:%m월 %d일}({WEEKDAY_KO[day.weekday()]})"


def format_week_structure(db: MenuDB, week_start: date, days: int = 5) -> str:
    """한 주치 식단을 날짜 → 끼니 → 코너 순서로 펼쳐 사람이 읽게 만든다.

    카카오 응답과 달리 말풍선 길이 제한이 없으니 생략 없이 전부 보여준다.
    알림을 받은 사람이 OCR이 제대로 읽었는지 눈으로 확인하는 용도다.
    """
    lines: list[str] = []
    total = 0
    for offset in range(days):
        day = week_start + timedelta(days=offset)
        rows = db.query(day)
        lines.append("")
        lines.append(f"────────── {_label(day)} ──────────")
        if not rows:
            lines.append("  (저장된 항목 없음)")
            continue
        total += len(rows)
        grouped: dict[str, list] = {}
        for row in rows:
            grouped.setdefault(row["meal_type"], []).append(row)
        for meal in MEAL_ORDER:
            meal_rows = grouped.get(meal)
            if not meal_rows:
                continue
            lines.append(f"  [{meal}]")
            # 일반식을 먼저 보여주고 PLUS·간편식·건강식을 뒤에 붙인다(카카오 응답과 같은 순서).
            for row in sorted(meal_rows, key=lambda r: r["category"] != "일반식"):
                category = "공통 PLUS" if row["category"] == "PLUS 코너" else row["category"]
                mark = {"special": " ✨특식", "no_service": " ⛔미운영"}.get(row["status"], "")
                lines.append(f"    · {category}{mark}")
                for item in (part.strip() for part in row["menu_text"].split(" · ")):
                    if item:
                        lines.append(f"        - {item}")
        # 여러 사업장 게시물이 같은 날에 섞여 들어온 경우를 알림에서 알아볼 수 있게 한다.
        locations = sorted({row["location"] for row in rows})
        if len(locations) > 1:
            lines.append(f"    (사업장: {', '.join(locations)})")
    return f"저장된 항목 {total}개\n" + "\n".join(lines)


def success_mail(
    week_start: date,
    checked_at: str,
    stats: dict | None,
    structure: str,
    locations: list[str] | None = None,
    split_by_site: bool = False,
) -> tuple[str, str]:
    week_end = week_start + timedelta(days=4)
    subject = f"[뷰밥 메뉴 알리미] {week_start:%m/%d}~{week_end:%m/%d} 식단 수집 완료"
    if stats:
        counts = (
            f"게시물 {stats.get('posts', 0)}건 / 이미지 {stats.get('images', 0)}장 / "
            f"메뉴 항목 {stats.get('entries', 0)}개"
        )
        if stats.get("skipped_images"):
            counts += f" / 식단표가 아닌 이미지 {stats['skipped_images']}장 제외"
        if stats.get("errors"):
            counts += f"\n            처리 중 오류 {len(stats['errors'])}건: {stats['errors']}"
    else:
        counts = "(통계 없음)"
    body = f"""다음 주 식단표 게시글을 찾아 수집·OCR·저장까지 끝냈습니다.

확인 시각 : {checked_at}
대상 주차 : {_label(week_start)} ~ {_label(week_end)}
수집 결과 : {counts}
출처 사업장 : {", ".join(locations or []) or "확인 불가"}
{"" if not split_by_site else chr(10) + "이번 주는 사업장별로 나뉘어 올라왔습니다. 식당은 두 사업장 메뉴가 같을 때" + chr(10) + "통합으로 올리므로, 나뉘어 올라온 주는 운영 예외(끼니 미운영 등)가 있다는" + chr(10) + "뜻입니다. 챗봇은 같은 끼니는 하나로 합쳐 보여주고, 사업장마다 다른 끼니만" + chr(10) + "사업장을 밝혀 나란히 보여줍니다." + chr(10)}

{week_start:%m월 %d일}(월) 00시가 지나면 카카오 챗봇에서 바로 조회됩니다.
운영 DB는 항상 '이번 주'만 노출하므로, 주말에 미리 저장돼 있어도 월요일
전에는 사용자에게 보이지 않습니다.

아래가 저장된 식단 구조입니다. OCR이 이상하게 읽은 항목이 보이면
`sudo systemctl start menubot-collect.service`로 다시 수집할 수 있습니다.

{structure}
"""
    return subject, body


def deadline_alert_mail(week_start: date, checked_at: str, state: dict) -> tuple[str, str]:
    week_end = week_start + timedelta(days=4)
    subject = (
        f"[뷰밥 메뉴 알리미] ⚠ 다음 주({week_start:%m/%d}~{week_end:%m/%d}) 식단을 아직 못 받았습니다"
    )
    attempts = state.get("attempts") or []
    counts: dict[str, int] = {}
    for attempt in attempts:
        key = attempt.get("result", "unknown")
        counts[key] = counts.get(key, 0) + 1
    summary = "\n".join(
        f"  - {ATTEMPT_LABELS.get(key, key)}: {count}회" for key, count in sorted(counts.items())
    ) or "  - (시도 기록 없음)"
    recent_lines = []
    for attempt in attempts[-8:]:
        result = attempt.get("result")
        recent_lines.append(f"  {attempt.get('at', '?')}  {ATTEMPT_LABELS.get(result, result)}")
        if attempt.get("error"):
            recent_lines.append(f"      → {attempt['error']}")
    recent = "\n".join(recent_lines) or "  (없음)"
    body = f"""주말 폴링이 끝나는 시점(일요일 22시)까지 다음 주 식단을 확보하지 못했습니다.

확인 시각 : {checked_at}
대상 주차 : {_label(week_start)} ~ {_label(week_end)}
상태      : 미확보

시도 요약 :
{summary}

최근 시도 :
{recent}

이대로 두면 월요일 아침 08시 정기 수집(menubot-collect.timer)이 다시 시도합니다.
그때까지 게시글이 올라오지 않으면 챗봇은 "식단표가 아직 업로드되지 않았습니다"로
답합니다(사용자에게 틀린 식단을 보여주지는 않습니다).

지금 직접 확인하려면:
  sudo systemctl start menubot-nextweek.service   # 다음 주 게시글 재확인
  journalctl -u menubot-nextweek -n 50            # 로그
  ./scripts/check-linux-env.sh                    # 그룹웨어 접속·환경 점검
"""
    return subject, body
