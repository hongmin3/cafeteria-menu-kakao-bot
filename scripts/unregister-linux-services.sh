#!/usr/bin/env bash
# 되돌리기: menubot-* 유닛만 정지·비활성화·삭제한다.
# 이 서버에서 함께 돌고 있는 다른 서비스와 /etc/hosts, 시간대 설정에는
# 손대지 않는다.
set -uo pipefail
if [ "$(id -u)" != "0" ]; then
  echo "sudo로 실행하세요: sudo scripts/unregister-linux-services.sh" >&2
  exit 1
fi
UNITS=(
  menubot-nextweek-deadline.timer
  menubot-nextweek-weekend.timer
  menubot-nextweek-friday.timer
  menubot-collect.timer
  menubot-tunnel.service
  menubot-web.service
  menubot-nextweek.service
  menubot-nextweek-deadline.service
  menubot-collect.service
)
for u in "${UNITS[@]}"; do
  systemctl disable --now "$u" 2>/dev/null || true
  rm -f "/etc/systemd/system/$u"
  echo "  제거: $u"
done
systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true
echo "완료. /etc/hosts의 menu-bot 항목은 남아 있으니 필요하면 직접 지우세요."
