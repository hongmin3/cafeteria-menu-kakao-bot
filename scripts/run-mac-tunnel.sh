#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h:h}"
cd "$project_dir"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

if ! command -v ngrok >/dev/null 2>&1; then
  print -u2 "ngrok이 없습니다. 'brew install ngrok/ngrok/ngrok'으로 설치해 주세요."
  exit 1
fi

if [[ -z "${NGROK_DOMAIN:-}" ]]; then
  print -u2 ".env의 NGROK_DOMAIN에 ngrok 무료 고정 개발 도메인을 넣어 주세요."
  exit 1
fi

exec ngrok http 8000 --url "https://${NGROK_DOMAIN}"
