#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h:h}"
cd "$project_dir"

if [[ ! -x ".venv/bin/uvicorn" ]]; then
  print -u2 "먼저 README의 설치 단계를 실행해 주세요."
  exit 1
fi

exec .venv/bin/uvicorn menu_bot.web:app --host 127.0.0.1 --port 8000
