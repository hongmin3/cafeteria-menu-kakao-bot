# scripts/run-linux-*.sh, check-linux-env.sh가 공통으로 불러쓰는 helper.
# 비밀번호나 토큰 값은 어떤 함수도 로그에 출력하지 않는다.

project_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

# .env에서 값 하나를 읽는다. 값 자체는 절대 로그로 내보내지 않는다.
env_value() {
  local name="$1" env_path="${2:-$(project_root)/.env}"
  [ -f "$env_path" ] || return 0
  sed -n "s/^[[:space:]]*${name}[[:space:]]*=//p" "$env_path" | head -1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

# 로그는 journald(stdout)와 logs/<이름>-YYYY-MM-DD.log 양쪽에 남긴다.
# 타임스탬프는 서버 로컬 시간(America/New_York)이 아니라 식단 기준 시간대로
# 찍어야 사람이 읽을 수 있으므로 TZ를 명시한다.
write_log() {
  local message="$1" log_name="$2"
  local log_dir="$(project_root)/logs"
  mkdir -p "$log_dir"
  local stamp="$(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M:%S')"
  local line="[$stamp KST] $message"
  printf '%s\n' "$line" >> "$log_dir/${log_name}-$(TZ=Asia/Seoul date '+%Y-%m-%d').log"
  printf '%s\n' "$line"
}

remove_old_logs() {
  local keep_days="${1:-30}"
  local log_dir="$(project_root)/logs"
  [ -d "$log_dir" ] || return 0
  find "$log_dir" -maxdepth 1 -name '*.log' -type f -mtime "+$keep_days" -delete 2>/dev/null || true
}

venv_menu_bot() {
  local exe="$(project_root)/.venv/bin/menu-bot"
  if [ ! -x "$exe" ]; then
    echo "가상환경이 없습니다. scripts/install-linux.sh 를 먼저 실행하세요." >&2
    return 1
  fi
  printf '%s\n' "$exe"
}
