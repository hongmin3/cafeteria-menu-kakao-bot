# 에이전트 작업 지침

Follow `akela/PROTOCOL.md` for every task.

## Project Root 탐색 규칙

`src/`, `scripts/`, `tests/` 등 이 프로젝트 하위 어디서 작업하든 먼저 상위로 `akela.json`을 탐색해 가장 가까운 Project Root를 식별하고 그 Root의 `knowledge/`·`akela/PROTOCOL.md`를 사용한다. 하위 디렉터리에 별도 `akela.json`/`knowledge/`를 만들지 않는다. 탐색은 `scripts/find-project-root.ps1`로 자동화되어 있다.

## 운영 주의

이 프로젝트는 사내 QA 서버(10.13.0.222)에서 실제 운영 중인 프로덕션 서비스이므로 배포/운영 관련 변경은 특히 신중히 다룬다.
