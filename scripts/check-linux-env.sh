#!/usr/bin/env bash
# 읽기 전용 환경 점검. 어떤 값도 바꾸지 않고, .env의 값 자체는 출력하지 않는다.
set -uo pipefail
. "$(dirname "$0")/linux-common.sh"
cd "$(project_root)"

ok()   { printf '  [OK]   %s\n' "$1"; }
bad()  { printf '  [!!]   %s\n' "$1"; FAIL=1; }
warn() { printf '  [..]   %s\n' "$1"; }
FAIL=0

echo "1) 파이썬 / 가상환경"
if [ -x .venv/bin/python ]; then ok "$(./.venv/bin/python --version 2>&1)"; else bad ".venv 없음 → scripts/install-linux.sh"; fi
for mod in fastapi uvicorn playwright dotenv requests paddleocr; do
  if ./.venv/bin/python -c "import $mod" 2>/dev/null; then ok "$mod"; else bad "$mod 미설치"; fi
done

echo "2) Chromium / ngrok"
if ls -d "$HOME"/.cache/ms-playwright/chromium-* >/dev/null 2>&1; then ok "Playwright Chromium 설치됨"; else bad "Chromium 없음 → .venv/bin/playwright install chromium"; fi
NGROK="${NGROK_BIN:-$HOME/.local/bin/ngrok}"
if [ -x "$NGROK" ]; then ok "ngrok $("$NGROK" version | awk '{print $3}')"; else bad "ngrok 없음"; fi
if [ -f "$HOME/.config/ngrok/ngrok.yml" ]; then
  "$NGROK" config check >/dev/null 2>&1 && ok "ngrok 설정 유효" || bad "ngrok 설정 오류"
else bad "~/.config/ngrok/ngrok.yml 없음"; fi

echo "3) .env 필수 키 (값은 출력하지 않음)"
for key in GROUPWARE_USER GROUPWARE_PASSWORD GROUPWARE_URL KAKAO_WEBHOOK_TOKEN NGROK_DOMAIN MENUBOT_PORT; do
  if [ -n "$(env_value "$key")" ]; then ok "$key 설정됨"; else bad "$key 비어 있음"; fi
done
if [ -f .env ]; then
  perm="$(stat -c '%a' .env)"
  [ "$perm" = "600" ] && ok ".env 권한 600" || warn ".env 권한 $perm (600 권장)"
fi

echo "4) 네트워크"
GW_HOST="$(env_value GROUPWARE_URL | sed -E 's#^https?://([^/]+).*#\1#')"
if [ -n "$GW_HOST" ]; then
  IP="$(getent hosts "$GW_HOST" | awk '{print $1}' | head -1)"
  if [ -z "$IP" ]; then bad "$GW_HOST DNS 해석 실패"
  else
    code="$(curl -so /dev/null -w '%{http_code}' --max-time 15 "https://$GW_HOST/" || true)"
    if [ "$code" = "000" ] || [ -z "$code" ]; then
      bad "$GW_HOST($IP) 접속 불가 — 사내 DNS를 안 쓰는 서버라면 /etc/hosts에 내부 IP 고정 필요"
    else ok "$GW_HOST($IP) 접속 가능 (HTTP $code)"; fi
  fi
fi
code="$(curl -so /dev/null -w '%{http_code}' --max-time 15 https://ngrok.com || true)"
[ "$code" = "000" ] && bad "아웃바운드 443 (ngrok.com) 불가" || ok "아웃바운드 443 가능"

echo "5) 포트 충돌"
PORT="$(env_value MENUBOT_PORT)"; PORT="${PORT:-18080}"
if ss -tlnp 2>/dev/null | grep -qE "[:.]$PORT[[:space:]]"; then
  if systemctl is-active --quiet menubot-web.service; then ok "$PORT — menubot-web.service가 사용 중"
  else bad "$PORT 를 다른 프로세스가 쓰고 있음"; fi
else ok "$PORT 사용 가능"; fi

echo "6) systemd 유닛"
for u in menubot-web.service menubot-tunnel.service menubot-collect.timer menubot-nextweek-friday.timer menubot-nextweek-weekend.timer menubot-nextweek-deadline.timer menubot-ensure.timer; do
  # is-enabled는 미등록 유닛에 "not-found"를 찍고 종료코드도 0이 아니라,
  # 첫 줄만 취해 두 줄로 깨지지 않게 한다.
  state="$(systemctl is-enabled "$u" 2>/dev/null | head -1)"; state="${state:-미등록}"
  active="$(systemctl is-active "$u" 2>/dev/null | head -1)"; active="${active:-inactive}"
  printf '  %-38s enabled=%-10s active=%s\n' "$u" "$state" "$active"
done

echo "7) DB"
if [ -f "$(env_value DATABASE_PATH)" ] || [ -f data/menus.db ]; then
  ./.venv/bin/python -c "
from menu_bot.config import get_settings
from menu_bot.db import MenuDB
s=get_settings(); db=MenuDB(s.database_path)
print('  [OK]   메뉴 항목', db.count_entries(), '개')
db.close()" 2>/dev/null || bad "DB 조회 실패"
else warn "DB 아직 없음 (첫 수집 전)"; fi

echo "8) 알림 메일 (값은 출력하지 않음)"
MAIL_OUT="$(./.venv/bin/python -c "
from menu_bot.notify import get_mail_settings
m = get_mail_settings()
if m.configured:
    print('OK|%s:%s %s -> %s' % (m.host, m.port, m.security, ', '.join(m.recipients)))
else:
    print('MISSING|' + ', '.join(m.missing))
" 2>/dev/null)"
case "$MAIL_OUT" in
  OK\|*) ok "발송 설정 완료 (${MAIL_OUT#OK|})" ;;
  MISSING\|*) bad "알림 메일 미설정 — .env의 ${MAIL_OUT#MISSING|} 를 채워야 성공/미확보 알림이 나갑니다" ;;
  *) bad "알림 메일 설정을 읽을 수 없습니다" ;;
esac
if [ "${MAIL_OUT%%|*}" = "OK" ]; then
  SMTP_HOST_V="$(env_value SMTP_HOST)"; SMTP_PORT_V="$(env_value SMTP_PORT)"
  if timeout 10 bash -c "</dev/tcp/${SMTP_HOST_V}/${SMTP_PORT_V:-587}" 2>/dev/null; then
    ok "SMTP ${SMTP_HOST_V}:${SMTP_PORT_V:-587} 연결 가능"
  else
    bad "SMTP ${SMTP_HOST_V}:${SMTP_PORT_V:-587} 연결 불가(아웃바운드 차단 여부 확인)"
  fi
fi

echo
[ "$FAIL" = "0" ] && echo "점검 결과: 문제 없음" || { echo "점검 결과: 위 [!!] 항목을 해결하세요"; exit 1; }
