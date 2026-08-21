#!/usr/bin/env bash
# 다음 주 식단표 게시글이 올라왔는지 확인한다.
# 이미 확인된 주차라면 그룹웨어에 접속하지 않고 바로 종료한다
# (menu_bot.next_week_watch 참고).
# systemd timer: 금요일 22:00(KST) 1회 + 토·일 00:05부터 2시간 간격.
set -uo pipefail
. "$(dirname "$0")/linux-common.sh"
cd "$(project_root)"
remove_old_logs

MENU_BOT="$(venv_menu_bot)" || exit 1
"$MENU_BOT" check-next-week 2>&1 | while IFS= read -r l; do write_log "$l" next-week-watch; done
