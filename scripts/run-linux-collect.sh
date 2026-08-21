#!/usr/bin/env bash
# 운영용 주간 수집: 월요일 아침(KST)에 한 번 실행되도록 systemd timer로 예약한다.
# 차주 식단표는 주말에 게시되지만 운영 DB는 항상 "이번 주"만 저장하므로
# 월요일 아침 실행이 유일하게 안전한 시점이다.
set -uo pipefail
. "$(dirname "$0")/linux-common.sh"
cd "$(project_root)"
remove_old_logs

MENU_BOT="$(venv_menu_bot)" || exit 1
MANIFEST="data/latest_manifest.json"

write_log "주간 수집 시작" collect
if ! "$MENU_BOT" scrape --pages 2 --output "$MANIFEST" 2>&1 | while IFS= read -r l; do write_log "$l" collect; done; then
  write_log "오류: scrape 실패" collect
  exit 1
fi
if ! "$MENU_BOT" ingest "$MANIFEST" 2>&1 | while IFS= read -r l; do write_log "$l" collect; done; then
  write_log "오류: ingest 실패" collect
  exit 1
fi
write_log "주간 수집 완료" collect
