#!/usr/bin/env bash
# Linux(사내 서버, Ubuntu 24.04) 설치 스크립트.
# sudo가 필요한 작업은 하지 않는다. systemd 등록만 register-linux-services.sh가
# 따로 sudo를 쓴다.
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"

echo "== 1/4 가상환경 =="
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip -q install --upgrade pip setuptools wheel
./.venv/bin/pip -q install -e '.[dev]'

echo "== 2/4 PaddleOCR (온디바이스 한국어 OCR, CPU) =="
# paddlepaddle은 pyproject의 필수 의존성에 넣지 않는다. macOS는 Apple Vision을
# 쓰고, 이쪽만 수백 MB를 내려받기 때문이다.
./.venv/bin/pip -q install "paddlepaddle==3.2.0" "paddleocr>=3.2,<4"

echo "== 3/4 Playwright Chromium =="
# 서버에는 Google Chrome이 없으므로 Playwright 번들 Chromium을 쓴다
# (menu_bot.scraper._launch 참고).
./.venv/bin/playwright install chromium

echo "== 4/4 ngrok =="
if [ ! -x "$HOME/.local/bin/ngrok" ]; then
  mkdir -p "$HOME/.local/bin"
  curl -sSL --max-time 300 -o /tmp/ngrok.tgz \
    https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
  tar -xzf /tmp/ngrok.tgz -C "$HOME/.local/bin" ngrok
  chmod +x "$HOME/.local/bin/ngrok"
  rm -f /tmp/ngrok.tgz
fi
"$HOME/.local/bin/ngrok" version

cat <<'NEXT'

설치 완료. 남은 일:
  1. cp .env.example .env 후 그룹웨어 계정 / 카카오 토큰 / NGROK_DOMAIN 입력
     (chmod 600 .env)
  2. ~/.config/ngrok/ngrok.yml 에 authtoken 설정 (chmod 600)
  3. 그룹웨어가 사내 DNS로만 해석되는 망이면 /etc/hosts 에 내부 IP 고정
     (scripts/check-linux-env.sh 가 점검해 줍니다)
  4. scripts/check-linux-env.sh 로 점검
  5. sudo scripts/register-linux-services.sh 로 systemd 등록
NEXT
