from __future__ import annotations

from pathlib import Path
import secrets


env_path = Path(__file__).resolve().parents[1] / ".env"
lines = env_path.read_text(encoding="utf-8").splitlines()
output: list[str] = []
changed = False
for line in lines:
    if line == "KAKAO_WEBHOOK_TOKEN=":
        output.append(f"KAKAO_WEBHOOK_TOKEN={secrets.token_urlsafe(32)}")
        changed = True
    else:
        output.append(line)
if not changed and not any(line.startswith("KAKAO_WEBHOOK_TOKEN=") for line in lines):
    output.append(f"KAKAO_WEBHOOK_TOKEN={secrets.token_urlsafe(32)}")
    changed = True
env_path.write_text("\n".join(output) + "\n", encoding="utf-8")
print("KAKAO_WEBHOOK_TOKEN이 이미 설정되어 있습니다." if not changed else "새 웹훅 토큰을 안전하게 생성했습니다.")
