#!/usr/bin/env bash
# 카카오 스킬 FastAPI 서버. systemd(menubot-web.service)가 Restart=always로
# 감시하므로 Windows판처럼 스크립트 안에서 재시작 루프를 돌리지 않는다.
# ngrok 터널이 같은 호스트에서 붙으므로 127.0.0.1만 바인딩한다
# (사내망에 스킬 서버를 직접 노출하지 않는다).
set -euo pipefail
. "$(dirname "$0")/linux-common.sh"
cd "$(project_root)"
PORT="$(env_value MENUBOT_PORT)"
PORT="${PORT:-18080}"
write_log "FastAPI 서버 시작 (127.0.0.1:${PORT})" server
exec ./.venv/bin/uvicorn menu_bot.web:app --host 127.0.0.1 --port "$PORT"
