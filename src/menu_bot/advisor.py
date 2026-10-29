"""이상해 보이는 식단표를 운영 서버의 Claude CLI에게 보여 주고 판정을 묻는다.

Claude는 자문만 한다. 답 중에서 "이 항목은 음식이 아니다"와 "이 날은 식당을
운영하지 않는다"만 받아들이고, 그것도 이미 읽은 글자와 맞을 때만 반영한다.
Claude가 그림을 잘못 보거나 글자를 지어내도 사용자에게 없는 메뉴가 보이지
않게 하기 위해서다(REQ-ADV-002). 호출이 실패하면 파서 결과를 그대로 쓴다.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from .corrections import apply_substitutions
from .models import MenuEntry, SourcePost
from .parser import find_date_headers
from .service_notices import INFERRED_SUFFIX, classify_notice, compact_notice


PROMPT_VERSION = 1
TIMEOUT_SECONDS = 180
# 메뉴로 남은 글자 중 이 높이(이미지 높이 비율) 이상은 그림 글씨로 의심한다.
# 일반 메뉴 글자는 0.02~0.04다. 칸 전체가 그림 글씨인 날은 파서가 이미 처리한다.
LARGE_TEXT_HEIGHT = 0.05
GENERIC_LABEL = "식단표에 메뉴 없음"
ITEM_SEPARATOR = " · "


ALERT_STATE_PATH = "data/advisor_alert_state.json"
ALERT_INTERVAL_HOURS = 12
RETRY_WAIT_SECONDS = 20

# 실패 종류. 메일 제목과 조치 안내가 종류마다 다르다.
FAILURE_LABELS = {
    "missing": "claude CLI를 찾을 수 없음",
    "auth": "Claude 로그인이 풀렸거나 인증 실패",
    "limit": "Claude 사용 한도 초과",
    "timeout": f"Claude 응답 시간 초과({TIMEOUT_SECONDS}초)",
    "unstable": "Claude 서비스 오류·불안정",
    "bad_answer": "Claude 답을 읽을 수 없음",
}
FAILURE_ACTIONS = {
    "missing": "서버에서 `ls ~/.local/bin/claude`로 설치를 확인하세요. 자문을 끄려면 .env에 MENU_ADVISOR=off.",
    "auth": "서버에 ubuntu 계정으로 접속해 `claude`를 실행하고 /login으로 다시 로그인하세요.",
    "limit": "한도가 풀리면 다음 수집부터 다시 묻습니다. 급하면 /usage로 남은 한도를 확인하세요.",
    "timeout": "일시적인 지연일 수 있습니다. 반복되면 `claude -p ping`으로 응답 속도를 확인하세요.",
    "unstable": "Anthropic 서비스 상태(status.claude.com)를 확인하세요. 한 번 다시 시도한 뒤에도 실패했습니다.",
    "bad_answer": "그림 옆 `.advice.json`이 저장되지 않았습니다. 반복되면 프롬프트 형식을 점검하세요.",
}
# 문구는 2026-10-20 서버 CLI(2.1.299) 실행 파일과 실제 미로그인 출력에서 확인했다.
# `Context limit reached`는 입력이 너무 긴 것이라 한도 초과가 아니다.
_LIMIT_RE = re.compile(
    r"usage limit|(?<!context )limit reached|hit your (?:\w+ )?limit|(?:session|weekly) limit|"
    r"rate.?limit|\b429\b|credit balance|spend.?cap|quota", re.I)
_AUTH_RE = re.compile(r"/login|log ?in|oauth|api key|\b401\b|\b403\b|authenticat|unauthori[sz]ed|expired", re.I)
_UNSTABLE_RE = re.compile(r"overloaded|\b5\d\d\b|api error|connection|network|ECONN|ETIMEDOUT|socket", re.I)


class AdvisorError(RuntimeError):
    def __init__(self, kind: str, detail: str):
        super().__init__(f"{FAILURE_LABELS.get(kind, kind)}: {detail}")
        self.kind = kind
        self.detail = detail


def classify_failure(text: str) -> str:
    """CLI가 낸 오류 문구로 실패 종류를 가린다. 한도를 인증보다 먼저 본다."""
    if _LIMIT_RE.search(text):
        return "limit"
    if _AUTH_RE.search(text):
        return "auth"
    return "unstable"


def classify_status(status) -> str | None:
    """CLI JSON의 `api_error_status`(HTTP 코드)로 가린다. 코드가 없으면 None."""
    if not isinstance(status, int):
        return None
    if status == 429:
        return "limit"
    if status in (401, 403):
        return "auth"
    return "unstable"


def claude_path() -> str | None:
    found = os.getenv("CLAUDE_BIN") or shutil.which("claude")
    if found:
        return found
    # systemd 서비스의 PATH에는 사용자 설치 경로가 빠져 있을 수 있다.
    fallback = Path.home() / ".local" / "bin" / "claude"
    return str(fallback) if fallback.exists() else None


def advisor_mode() -> str:
    """`off`=끔, `on`=반드시 사용(CLI가 없으면 실패로 알림), `auto`=CLI가 있으면 사용."""
    value = os.getenv("MENU_ADVISOR", "auto").strip().lower()
    if value in {"off", "0", "false", "no"}:
        return "off"
    return "on" if value in {"on", "1", "true", "yes"} else "auto"


def run_claude(prompt: str, cwd: Path) -> str:
    """Claude CLI를 한 번 실행하고 최종 답 문자열을 돌려준다. 실패는 AdvisorError."""
    binary = claude_path()
    if not binary:
        raise AdvisorError("missing", "PATH와 ~/.local/bin에 claude가 없습니다")
    try:
        completed = subprocess.run(
            [binary, "-p", prompt, "--allowedTools", "Read", "--output-format", "json"],
            cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdvisorError("timeout", f"{TIMEOUT_SECONDS}초 안에 답이 없었습니다") from exc
    except OSError as exc:
        raise AdvisorError("missing", f"{type(exc).__name__}: {exc}") from exc
    try:
        outer = json.loads(completed.stdout)
    except ValueError:
        outer = None
    if completed.returncode != 0 or not isinstance(outer, dict) or outer.get("is_error"):
        detail = str(outer.get("result") if isinstance(outer, dict) else "") or completed.stderr or completed.stdout
        status = outer.get("api_error_status") if isinstance(outer, dict) else None
        detail = f"종료 코드 {completed.returncode}: {' '.join(detail.split())[:300]}"
        if isinstance(status, int):
            detail += f" (HTTP {status})"
        raise AdvisorError(classify_status(status) or classify_failure(detail), detail)
    return str(outer.get("result", ""))


def ask_with_retry(runner, prompt: str, cwd: Path, sleep=None) -> dict:
    """한 번 묻고, 서비스가 불안정했으면 한 번만 다시 묻는다. 답은 판정 dict."""
    import time
    for attempt in (1, 2):
        try:
            text = runner(prompt, cwd)
        except AdvisorError as exc:
            if exc.kind == "unstable" and attempt == 1:
                (sleep or time.sleep)(RETRY_WAIT_SECONDS)
                continue
            raise
        except Exception as exc:  # 주입된 runner나 예상 못 한 오류도 불안정으로 본다.
            if attempt == 1:
                (sleep or time.sleep)(RETRY_WAIT_SECONDS)
                continue
            raise AdvisorError("unstable", f"{type(exc).__name__}: {exc}") from exc
        try:
            return parse_verdict(text)
        except ValueError as exc:
            raise AdvisorError("bad_answer", f"{exc}: {' '.join(text.split())[:200]}") from exc
    raise AdvisorError("unstable", "재시도 후에도 실패했습니다")


def failure_mail(error: AdvisorError, post: SourcePost, image_name: str, signals: list[dict]) -> tuple[str, str]:
    from datetime import datetime
    from .notify import sender_host
    subject = f"[뷰밥 메뉴 알리미] ⚠️ Claude 자문 실패: {FAILURE_LABELS.get(error.kind, error.kind)}"
    days = "\n".join(
        f"  {s['date']}  {', '.join(s['reasons'])}" + (f"\n      의심 항목: {', '.join(s['suspicious'])}"
                                                     if s['suspicious'] else "")
        for s in signals
    ) or "  (없음)"
    body = f"""식단표에 이상 신호가 있어 Claude에게 물었지만 답을 받지 못했습니다.
이번 수집은 OCR로 읽은 결과를 그대로 저장했습니다. 아래 날짜의 답변이 틀릴 수 있습니다.

확인 시각 : {datetime.now():%Y-%m-%d %H:%M}
발신 호스트 : {sender_host()}
실패 종류 : {FAILURE_LABELS.get(error.kind, error.kind)}
오류 내용 : {error.detail}
게시글 : {post.title}
그림 : data/images/{image_name}

확인이 필요한 날짜 :
{days}

조치 : {FAILURE_ACTIONS.get(error.kind, '')}
잘못 읽은 메뉴 이름은 `menu-bot correct`로 바로 고칠 수 있습니다.
같은 종류의 실패는 {ALERT_INTERVAL_HOURS}시간에 한 번만 알립니다.
"""
    return subject, body


def _should_alert(kind: str, now: float, path: Path) -> bool:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    last = state.get(kind)
    return not isinstance(last, (int, float)) or now - last >= ALERT_INTERVAL_HOURS * 3600


def _mark_alerted(kind: str, now: float, path: Path) -> None:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    state[kind] = now
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def report_failure(error: AdvisorError, post: SourcePost, image_name: str, signals: list[dict],
                   send=None, progress=print, state_path: Path | None = None, now: float | None = None) -> bool:
    """실패를 알리는 메일을 보낸다. 같은 종류는 정해진 시간 안에 한 번만 보낸다."""
    import time
    from .notify import send_mail
    path = Path(state_path or os.getenv("ADVISOR_ALERT_STATE_PATH") or ALERT_STATE_PATH)
    now = time.time() if now is None else now
    if not _should_alert(error.kind, now, path):
        progress(f"  같은 종류의 Claude 자문 실패 메일을 최근 {ALERT_INTERVAL_HOURS}시간 안에 보내 생략합니다.")
        return False
    subject, body = failure_mail(error, post, image_name, signals)
    sent = (send or send_mail)(subject, body, progress=progress)
    if sent:
        _mark_alerted(error.kind, now, path)
    return sent


def _items(entry: MenuEntry) -> list[str]:
    return [item for item in entry.menu_text.split(ITEM_SEPARATOR) if item]


def _center_x(line: dict) -> float:
    return line["x"] + line["width"] / 2


def _column_lines(lines: list[dict], headers: list[tuple[float, date]]) -> dict[date, list[dict]]:
    columns: dict[date, list[dict]] = {}
    top = 0.85
    for line in lines:
        x = _center_x(line)
        if x < 0.16 or line["y"] > top:
            continue
        header_x, day = min(headers, key=lambda item: abs(item[0] - x))
        if abs(header_x - x) <= 0.13:
            columns.setdefault(day, []).append(line)
    return columns


def find_signals(post: SourcePost, lines: list[dict], entries: list[MenuEntry]) -> list[dict]:
    """자문이 필요한 날짜와 그 이유, 의심 항목을 찾는다. 없으면 빈 목록."""
    headers, _ = find_date_headers(post, lines)
    if not headers:
        return []
    columns = _column_lines(lines, headers)
    signals = []
    for _, day in headers:
        day_entries = [e for e in entries if e.service_date == day]
        reasons: list[str] = []
        suspicious: list[str] = []
        if not day_entries:
            reasons.append("날짜 줄에는 있는데 메뉴가 하나도 없음")
        for entry in day_entries:
            if entry.status == "no_service":
                continue
            if entry.category == "일반식" and len(_items(entry)) <= 2:
                reasons.append(f"{entry.meal_type} 일반식 항목이 {len(_items(entry))}개뿐임")
                suspicious.extend(_items(entry))
        for line in columns.get(day, []):
            if line["height"] < LARGE_TEXT_HEIGHT:
                continue
            text = apply_substitutions(line["text"].strip())
            for entry in day_entries:
                if entry.status != "no_service" and text in _items(entry):
                    reasons.append(f"메뉴로 남은 큰 그림 글씨: {text}")
                    suspicious.append(text)
        if reasons:
            signals.append({
                "date": day.isoformat(),
                "reasons": list(dict.fromkeys(reasons)),
                "suspicious": list(dict.fromkeys(suspicious)),
                "menus": [
                    {"meal": e.meal_type, "category": e.category, "items": _items(e), "status": e.status}
                    for e in day_entries
                ],
                "column_text": [line["text"] for line in columns.get(day, [])],
            })
    return signals


def build_prompt(image_name: str, signals: list[dict]) -> str:
    days = json.dumps(
        [{k: s[k] for k in ("date", "reasons", "menus")} for s in signals], ensure_ascii=False, indent=1
    )
    return (
        f"사내 식당 주간 식단표 그림 `{image_name}`을 Read 도구로 열어 보고 아래 날짜만 판정해라.\n"
        "OCR 프로그램이 그림을 읽은 결과가 이상해 보이는 날짜들이다.\n"
        f"{days}\n\n"
        "날짜마다 다음을 판정한다.\n"
        "- not_food: 위 items 중 음식 이름이 아닌 것(행사·로고·장식 그림의 글자 등). items에 적힌 글자 그대로 쓴다.\n"
        "- closed: 그 날짜 칸에 메뉴 대신 휴일·행사·휴무 그림이나 문구만 있어 식당을 운영하지 않는 것으로 보이면 true.\n"
        "  칸이 그냥 비어 있거나 판단할 근거가 없으면 false.\n"
        "- closed_label: closed가 true면 그림에 적힌 휴일·행사 이름(예: 개천절, 뷰웍스 체육대회). 없으면 null.\n"
        "메뉴를 새로 적거나 고치지 마라. 설명 없이 JSON 한 개만 출력한다:\n"
        '{"days":[{"date":"YYYY-MM-DD","closed":false,"closed_label":null,"not_food":[]}]}'
    )


def parse_verdict(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("답에 JSON이 없습니다")
    verdict = json.loads(match.group(0))
    if not isinstance(verdict, dict) or not isinstance(verdict.get("days"), list):
        raise ValueError("답의 형식이 다릅니다")
    return verdict


def _label_is_verified(label: str, column_text: list[str]) -> bool:
    notice = classify_notice(label)
    if notice is not None and notice.inferred:
        return True
    compact = compact_notice(label)
    joined = compact_notice(apply_substitutions("".join(column_text)))
    return len(compact) >= 2 and compact in joined


def apply_verdict(entries: list[MenuEntry], signals: list[dict], verdict: dict) -> tuple[list[MenuEntry], list[str]]:
    by_date = {s["date"]: s for s in signals}
    result = list(entries)
    changes: list[str] = []
    for day_verdict in verdict["days"]:
        if not isinstance(day_verdict, dict):
            continue
        signal = by_date.get(str(day_verdict.get("date")))
        if signal is None:
            continue  # 묻지 않은 날짜에 대한 답은 반영하지 않는다.
        day = date.fromisoformat(signal["date"])
        not_food = {str(item) for item in day_verdict.get("not_food") or [] if isinstance(item, str)}
        updated: list[MenuEntry] = []
        for entry in result:
            if entry.service_date != day or entry.status == "no_service" or not not_food:
                updated.append(entry)
                continue
            kept = [item for item in _items(entry) if item not in not_food]
            removed = [item for item in _items(entry) if item in not_food]
            if removed:
                changes.append(f"{day} {entry.meal_type} {entry.category}: 음식 아님으로 제외 {removed}")
            if kept:
                updated.append(replace(entry, menu_text=ITEM_SEPARATOR.join(kept)) if removed else entry)
        result = updated

        if day_verdict.get("closed") is not True:
            continue
        suspicious = set(signal["suspicious"])
        remaining = [e for e in result if e.service_date == day and e.status != "no_service"]
        if any(item not in suspicious for e in remaining for item in _items(e)):
            changes.append(f"{day}: 미운영 판정을 받았지만 진짜 메뉴가 남아 있어 반영하지 않음")
            continue
        label = str(day_verdict.get("closed_label") or "").strip()
        if label and _label_is_verified(label, signal["column_text"]):
            message = label + INFERRED_SUFFIX
        elif not signal["menus"]:
            changes.append(f"{day}: 메뉴 없는 날의 미운영 이름 `{label}`을 확인할 수 없어 반영하지 않음")
            continue
        else:
            message = GENERIC_LABEL + INFERRED_SUFFIX
        template = next((e for e in entries if e.service_date == day), None) or entries[0]
        result = [e for e in result if e.service_date != day]
        for meal in ("조식", "중식", "석식"):
            result.append(replace(template, service_date=day, meal_type=meal, category="안내",
                                  menu_text=message, status="no_service", confidence=1.0))
        changes.append(f"{day}: 세 끼 미운영으로 변경 `{message}`")
    return result, changes


def advise(post: SourcePost, image_path: Path, lines: list[dict], entries: list[MenuEntry],
           runner=None, enabled: bool | None = None, progress=print, send=None, sleep=None,
           alert_state_path: Path | None = None) -> list[MenuEntry]:
    """이상 신호가 있으면 Claude에게 묻고, 받아들일 수 있는 판정만 반영한다.

    어떤 실패든 파서 결과를 그대로 돌려주고 운영자에게 메일로 알린다.
    """
    if enabled is None:
        mode = advisor_mode()
        # auto는 CLI가 있는 기계에서만 쓴다. on은 CLI가 없어도 묻다가 실패로 알린다.
        enabled = mode == "on" or (mode == "auto" and claude_path() is not None)
    if not entries or not enabled:
        return entries
    signals = find_signals(post, lines, entries)
    if not signals:
        return entries
    cache = image_path.with_name(image_path.name + ".advice.json")
    key = hashlib.sha256(json.dumps([PROMPT_VERSION, signals], ensure_ascii=False, sort_keys=True)
                         .encode()).hexdigest()
    verdict = None
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if saved.get("key") == key:
            verdict = saved["verdict"]
    except (OSError, ValueError, KeyError):
        pass
    asked = verdict is None
    if asked:
        try:
            verdict = ask_with_retry(runner or run_claude, build_prompt(image_path.name, signals),
                                     image_path.parent, sleep=sleep)
        except AdvisorError as exc:  # 자문 실패가 수집을 멈추면 안 된다.
            progress(f"  Claude 자문 실패, 읽은 결과 그대로 사용: {exc}")
            report_failure(exc, post, image_path.name, signals, send=send, progress=progress,
                           state_path=alert_state_path)
            return entries
    try:
        result, changes = apply_verdict(entries, signals, verdict)
    except Exception as exc:  # 형식이 조금 다른 답이 반영 단계에서 터져도 수집은 계속한다.
        error = AdvisorError("bad_answer", f"{type(exc).__name__}: {exc}")
        progress(f"  Claude 자문 반영 실패, 읽은 결과 그대로 사용: {error}")
        report_failure(error, post, image_path.name, signals, send=send, progress=progress,
                       state_path=alert_state_path)
        return entries
    if asked:
        cache.write_text(json.dumps({"key": key, "signals": signals, "verdict": verdict, "changes": changes},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
        progress(f"  Claude 자문: {len(signals)}개 날짜 확인, 변경 {len(changes)}건")
        for change in changes:
            progress(f"    {change}")
    return result
