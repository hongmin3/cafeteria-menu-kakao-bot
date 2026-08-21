#!/usr/bin/env bash
# 주말 폴링 마감 점검. 일요일 22:00(KST) 타이머가 부른다.
#
# 마감 시점에 "마지막 시도"를 한 번 더 하고 나서 판정한다. 단순히 상태 파일만
# 보고 알리면, 2시간 간격 폴링의 마지막 회차(일 22:05)가 5분 뒤에 성공하는
# 경우 헛경보를 먼저 보내게 된다. 여기서 직접 시도한 뒤 그래도 못 받았을 때만
# 알리므로 알림이 항상 사실과 맞는다.
#
# check-next-week는 게시글이 없으면 0, 접속 실패나 OCR 0건이면 1로 끝난다.
# 어느 쪽이든 이 스크립트는 계속 진행해야 하므로 종료 코드를 삼킨다. 최종
# 종료 코드는 next-week-deadline이 정한다(미확보면 1 → systemd가 실패로 표시).
set -uo pipefail
. "$(dirname "$0")/linux-common.sh"
cd "$(project_root)"
remove_old_logs

MENU_BOT="$(venv_menu_bot)" || exit 1

write_log "마감 전 마지막 시도" next-week-deadline
"$MENU_BOT" check-next-week 2>&1 | while IFS= read -r l; do write_log "$l" next-week-deadline; done || true

write_log "마감 판정" next-week-deadline
"$MENU_BOT" next-week-deadline 2>&1 | while IFS= read -r l; do write_log "$l" next-week-deadline; done
exit "${PIPESTATUS[0]}"
