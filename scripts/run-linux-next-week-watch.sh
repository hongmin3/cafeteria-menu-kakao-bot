#!/usr/bin/env bash
# 다음 주 식단표 게시글이 올라왔는지 확인한다.
# 이미 확인된 주차라면 그룹웨어에 접속하지 않고 바로 종료한다
# (menu_bot.next_week_watch 참고).
# 금요일 저녁과 주말에 실행한다. 놓친 금요일 작업이 평일에 따라오는 경우를 거른다.
set -uo pipefail
. "$(dirname "$0")/linux-common.sh"
cd "$(project_root)"
slot="$(TZ=Asia/Seoul date +%u%H)"
[ "${slot:0:1}" -ge 5 ] || exit 0
# The deadline launcher owns the last Sunday poll and its alert.
[ "$slot" != 722 ] || exit 0
lock_collection next-week-watch
remove_old_logs

MENU_BOT="$(venv_menu_bot)" || exit 1
"$MENU_BOT" check-next-week 2>&1 | while IFS= read -r l; do write_log "$l" next-week-watch; done
