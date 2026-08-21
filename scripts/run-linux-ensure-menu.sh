#!/usr/bin/env bash
# 1시간 간격 재시도. 일요일 22시 마감까지 식단표를 못 받았을 때 손을 놓지
# 않으려고 둔 안전망이다.
#
# 지금 필요한 주차 식단이 DB에 이미 있으면 그룹웨어에 접속하지 않고 즉시
# 끝난다(menu_bot.next_week_watch.ensure_week_menu 참고). 그래서 평소에는
# 한 시간마다 깨어나도 사실상 아무 일도 하지 않는다.
set -uo pipefail
. "$(dirname "$0")/linux-common.sh"
cd "$(project_root)"
remove_old_logs

MENU_BOT="$(venv_menu_bot)" || exit 1
"$MENU_BOT" ensure-menu 2>&1 | while IFS= read -r l; do write_log "$l" ensure-menu; done
exit "${PIPESTATUS[0]}"
