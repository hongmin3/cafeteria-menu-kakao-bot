#!/usr/bin/env bash
# ngrok 터널. 카카오 스킬 서버 URL은 고정 도메인이어야 하므로 .env의
# NGROK_DOMAIN을 그대로 쓴다. authtoken은 ~/.config/ngrok/ngrok.yml에 있고
# 이 스크립트는 토큰 값을 출력하지 않는다.
# systemd(menubot-tunnel.service)가 Restart=always로 감시한다.
set -euo pipefail
. "$(dirname "$0")/linux-common.sh"
cd "$(project_root)"
PORT="$(env_value MENUBOT_PORT)"
PORT="${PORT:-18080}"
DOMAIN="$(env_value NGROK_DOMAIN)"
NGROK="${NGROK_BIN:-$HOME/.local/bin/ngrok}"
if [ ! -x "$NGROK" ]; then
  write_log "오류: ngrok 실행 파일이 없습니다($NGROK). scripts/install-linux.sh 참고." tunnel
  exit 1
fi
if [ -z "$DOMAIN" ]; then
  write_log "오류: .env의 NGROK_DOMAIN이 비어 있습니다." tunnel
  exit 1
fi
write_log "ngrok 터널 시작 ($DOMAIN -> 127.0.0.1:$PORT)" tunnel
exec "$NGROK" http "$PORT" --domain "$DOMAIN" --log stdout --log-format logfmt --log-level info
