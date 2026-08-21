#!/usr/bin/env bash
# systemd 유닛 등록. sudo로 실행해야 한다.
#
# 이 서버에는 다른 팀 서비스가 이미 여러 개 돌고 있어,
# 이 스크립트는 menubot-* 이름의 유닛만 건드린다. 다른 유닛이나 시스템 설정
# (시간대, DNS, /etc/hosts 등)은 손대지 않는다.
set -euo pipefail

if [ "$(id -u)" != "0" ]; then
  echo "sudo로 실행하세요: sudo scripts/register-linux-services.sh" >&2
  exit 1
fi

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="${MENUBOT_USER:-$(stat -c '%U' "$APP_DIR")}"
UNIT_SRC="$APP_DIR/scripts/systemd"
UNIT_DST=/etc/systemd/system

echo "앱 경로 : $APP_DIR"
echo "실행 계정: $RUN_USER"

UNITS=(
  menubot-web.service
  menubot-tunnel.service
  menubot-collect.service
  menubot-collect.timer
  menubot-nextweek.service
  menubot-nextweek-friday.timer
  menubot-nextweek-weekend.timer
  menubot-nextweek-deadline.service
  menubot-nextweek-deadline.timer
  menubot-ensure.service
  menubot-ensure.timer
)

for u in "${UNITS[@]}"; do
  sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|^User=ubuntu$|User=$RUN_USER|" -e "s|^Group=ubuntu$|Group=$RUN_USER|" \
    "$UNIT_SRC/$u" > "$UNIT_DST/$u"
  chmod 644 "$UNIT_DST/$u"
  echo "  설치: $UNIT_DST/$u"
done

systemctl daemon-reload

# 상시 서비스와 타이머만 enable한다. menubot-collect.service /
# menubot-nextweek.service는 타이머가 부르는 oneshot이라 enable하지 않는다.
systemctl enable --now menubot-web.service
systemctl enable --now menubot-tunnel.service
systemctl enable --now menubot-collect.timer
systemctl enable --now menubot-nextweek-friday.timer
systemctl enable --now menubot-nextweek-weekend.timer
systemctl enable --now menubot-nextweek-deadline.timer
systemctl enable --now menubot-ensure.timer

echo
echo "== 상태 =="
systemctl --no-pager --output=short status menubot-web.service menubot-tunnel.service 2>&1 | grep -E "^●|Active:|Main PID:" || true
echo
echo "== 예약 (한국시간 기준으로 계산됨) =="
systemctl list-timers 'menubot-*' --no-pager
