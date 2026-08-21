"""알림 메일용 SMTP 비밀번호(Gmail 앱 비밀번호)를 .env에 안전하게 써넣는다.

`sed -i "s|...|$PASSWORD|"` 같은 방식은 비밀번호가 셸 히스토리와 프로세스
목록(ps)에 그대로 남는다. 이 스크립트는 getpass로 화면에 찍지 않고 받아
.env에만 쓰고, 값을 어디에도 출력하지 않는다.

    python3 scripts/set-smtp-password.py

Gmail은 2단계 인증 계정의 "앱 비밀번호"가 필요하다(일반 계정 비밀번호로는
SMTP 로그인이 거부된다). https://myaccount.google.com/apppasswords 에서 발급.
"""
from __future__ import annotations

from getpass import getpass
from pathlib import Path
import os
import sys


KEY = "SMTP_PASSWORD"
env_path = Path(__file__).resolve().parents[1] / ".env"

if not env_path.exists():
    sys.exit(f"{env_path} 가 없습니다. .env.example을 복사해 먼저 만드세요.")

password = getpass(f"{KEY} (입력은 화면에 표시되지 않습니다, 공백 제거됨): ").strip()
if not password:
    sys.exit("입력이 비어 있어 아무것도 바꾸지 않았습니다.")
if "\n" in password or "\r" in password:
    sys.exit("줄바꿈이 포함된 값은 .env에 넣을 수 없습니다.")

lines = env_path.read_text(encoding="utf-8").splitlines()
replaced = False
for index, line in enumerate(lines):
    if line.startswith(f"{KEY}="):
        lines[index] = f"{KEY}={password}"
        replaced = True
        break
if not replaced:
    lines.append(f"{KEY}={password}")

env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
os.chmod(env_path, 0o600)
print(f"{KEY}를 {'교체' if replaced else '추가'}했습니다({len(password)}자). .env 권한은 600입니다.")
print("확인: ./scripts/check-linux-env.sh")
print("실제 발송 시험: ./.venv/bin/menu-bot notify-test")
