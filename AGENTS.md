# 뷰밥 메뉴 알리미 AI 인덱스

Invoke the `task-observer` skill before the first tool call.

Follow `akela/PROTOCOL.md` for every task. 프로젝트 도메인 규칙은 compile된 slice를 기준으로 사용한다.

## 목적과 구조

그룹웨어 주간 식단 이미지를 Playwright로 수집하고 플랫폼별 OCR provider(macOS Apple Vision, Windows·Linux PaddleOCR)로 구조화해 SQLite에 저장한 뒤 FastAPI 카카오 Skill API로 조회한다.

- CLI 진입점: `src/menu_bot/cli.py`
- 수집/OCR/파싱: `scraper.py`, `ocr.py`, `ocr_provider.py`, `vision_ocr.swift`, `parser.py`, `pipeline.py`
- 저장/조회: `db.py`, `query.py`, `models.py`
- API: `web.py`
- 설정: `src/menu_bot/config.py`, 로컬 `.env`
- 테스트: `tests/`
- 운영 스크립트: `scripts/`
- 사람용 설치·사용·보안 설명: `README.md`, `SECURITY.md`

## 작업 시작 순서

1. 이어지는 작업이면 `progress.md`를 확인한다.
2. 요청과 직접 관련된 모듈과 테스트만 찾는다.
3. 실행·운영 질문일 때만 README의 해당 절을 확인한다.
4. 여러 모듈 변경이면 대상, 영향, 검증 명령을 먼저 제시한다.

## 자주 쓰는 명령

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src tests
.venv/bin/menu-bot ask "금요일 아침"
```

수집·DB 갱신·서버/터널 실행은 외부 시스템과 로컬 데이터를 바꿀 수 있으므로 사용자의 작업 범위에 포함될 때만 README의 명령을 사용한다.

## 변경 금지 및 주의

- `.env`, 내부 URL, 계정, 원본 이미지, OCR 결과, SQLite DB를 출력하거나 커밋하지 않는다.
- 현재 주만 제공하는 사용자 규칙과 학습용 과거 데이터 분리를 임의로 바꾸지 않는다.
- 카카오 응답 형식, 웹훅 토큰, 운영 스크립트, 배포 Workflow는 관련 요청 없이 변경하지 않는다.
- `OCR_PROVIDER=auto`의 플랫폼 선택과 두 provider의 정규화 좌표 contract를 근거 없이 바꾸지 않는다. provider별 모델·환경 제약은 README의 해당 플랫폼 절을 확인한다.
- 기능 변경에는 관련 `tests/`를 추가하거나 갱신한다.

## 컨텍스트 효율

- 제외: `.git/`, `.venv/`, `.cache/`, `.pytest_cache/`, `__pycache__/`, `data/`, `assets/`, `*.log`, `.env`.
- 이미지·DB·manifest는 해당 데이터 자체가 요청 대상일 때만 확인한다.
- 대형 파서는 대상 함수부터 검색하고 필요한 줄 범위만 읽는다.
- READ-ONCE를 적용하고 수정 후 `git diff --stat`, 대상 diff, 관련 테스트 결과만 확인한다.
- 성공 테스트는 최종 통과 수만, 실패는 원인 주변만 출력한다.

## 상세 정보

- 전체 실행 및 운영: `README.md`
- 공개 저장소 보안 기준: `SECURITY.md`
- Windows 이전 요청: `WINDOWS_CODEX_MIGRATION_REQUEST.md` (이전 작업일 때만 읽는다)

## 읽기 범위

요청에 연결된 소스와 문서만 추가로 확인한다.

이 절은 이전에 `CLAUDE.md`에만 있어 Codex가 볼 수 없던 규칙이다. AI 지침의 원본은 이 파일 하나다. 같은 디렉터리의 `CLAUDE.md`는 이 파일을 `@` import 하는 두 줄짜리 파일이며 `scripts/sync-agent-docs.sh`가 관리한다. Claude 전용 지침도 여기에 적는다.

<!-- readme-guidance: start -->
## README 작성 기준

- 처음 보는 사람이 **무엇을 해주는 프로젝트인지, 왜 필요한지, 어떻게 시작하는지** 이해할 수 있게 쓴다.
- 첫 부분은 쉬운 한두 문장과 실제 사용 예로 설명한다. 전문 용어는 필요한 곳에서 풀어 쓴다.
- 준비 사항 → 설치 → 첫 실행 → 기대 결과 순서의 **빠른 시작**을 앞에 둔다. 확인한 명령만 적는다.
- 자세한 운영 규칙, 내부 구조, 검증 기록은 `docs/` 등 별도 문서에 두고 README에서 연결한다.
- README는 현재 기능과 사용법을 설명한다. 세션별 작업 경과나 수정 내역을 길게 나열하지 않는다.
- 구현과 README가 어긋나지 않게 함께 갱신한다. 미검증 기능·플랫폼·제한사항은 분명히 구분한다.
- 기존 프로젝트의 기능·설정·민감정보·고유 문서 체계를 보존한다. 문서 정리를 이유로 실행 동작을 바꾸지 않는다.
<!-- readme-guidance: end -->

<!-- project-readiness-command: start -->
## 프로젝트 완료 검사

하위 폴더에서 작업을 시작했더라도 완료 전에는 이 프로젝트 루트로 이동하여 다음 명령을 실행한다.
```text
node .project-check/project-readiness.js .
```
검사 실패를 해결하거나 미완료로 보고한다. 이 검사는 문서와 경로 연결을 확인하며 프로젝트 자체 테스트와 실제 동작 검증을 대신하지 않는다.
<!-- project-readiness-command: end -->

<!-- project-spec-guidance: start -->
## 사양 기반 개발 (SPEC)

<!-- spec-workflow: v4 -->

`SPEC.md`가 이 프로젝트가 **어떻게 동작해야 하는가**의 기준이다. 코드의 현재 동작은 사양이
아니다. 아래는 상위 기준이고, 실제 절차(계획·테스트·검증)는 기존 Skill을 그대로 쓴다.

**작업 시작 전** — 기능 추가·변경·버그 수정이면 먼저 `SPEC.md`에서 ① 관련 Requirement,
② 그 Requirement의 구현, ③ 관련 테스트, ④ 변경 영향 범위를 확인한다. 해당 Requirement가
없는 신규 기능은 **구현 전에** SPEC에 추가한다. typo, 주석, 문서만 바꾸는 작업은 예외다.

**구현** — 사양에 없는 기능을 임의로 추가하지 않는다. 요구사항이 불충분하거나 모순되면
추측으로 확정하지 말고 SPEC의 "13. 미확정 사항"에 `(TBD)` 또는 `확인 필요`로 남기고
사용자에게 알린다.

**변경 요청 판별** — 요청을 받으면 먼저 현재 SPEC · 요청 · 기존 구현 · 변경 의도를 대조해
둘 중 무엇인지 정한다.

- **사양 변경**: `SPEC.md` 수정 → 테스트 수정·추가 → 구현 → 검증 → `CHANGELOG.md`
- **기존 사양 미충족(버그)**: SPEC 유지 → 재현 테스트 → 코드 수정 → regression 확인 → `CHANGELOG.md`

버그를 고치려고 올바른 기존 사양을 바꾸지 않는다.

**완료 전** — `Requirement → 구현 → 테스트 → 실제 실행 결과`를 모두 확인한다. 테스트 PASS는
실제 동작 검증을 대체하지 않는다. 실행 가능한 프로젝트는 대표 실행 경로를 실제로 돌리고
출력을 읽는다.

**완료 시** — 검증을 통과하면 관련 문서(`CHANGELOG.md`, `progress.md`, 필요하면 `README.md`와
`SPEC.md`)를 갱신하고 저장소를 커밋·푸시한다. 사용자 요청을 기다리지 않으며 하위 프로젝트
세션에도 동일하게 적용한다. 게이트·CI·라이브 세션 충돌 회피는 설치된 키트의 공통 `AGENTS.md`
push 규칙을 따른다.

**사람이 읽는 SPEC (`docs/SPEC.html`)** — 번호만 보고도 무슨 기능인지 알 수 있게 SPEC과 CHANGELOG를
다음처럼 쓴다. 페이지(기능 목록, 요구사항 카드의 상태·구현·테스트·참조됨·변경 이력, 목차·검색,
지금 읽는 절 표시)는 여기서 자동으로 만들어지므로 SPEC에 같은 내용을 다시 적지 않는다.

- REQ·NFR 제목 줄에 기능 이름을 쓴다: `### REQ-EXPORT-001 CSV 저장`. TEST 절차는 제외.
- 5절 첫 REQ 앞에 `| 카테고리 | 이름 |` 기능 그룹 표를 둔다. NFR 카테고리도 넣는다.
- 구현·테스트·상태는 12절 추적성 표에만 쓴다. 카드와 기능 목록이 거기서 읽는다.
- CHANGELOG 항목 앞에 ID를 붙인다(`- REQ-EXPORT-001: …`). 머리의 형식 예시 블록 안에는 쓰지 않는다 —
  예시 블록은 이력으로 읽히지 않는다. 예전 항목에 ID를 추측으로 소급하지 않는다.
- 흐름도는 `flow` 코드 블록으로 쓴다(`수집 -> 해석 -> 저장`, `저장 -(실패)-> 알림`). 외부 스크립트
  (Mermaid 등)를 쓰지 않는다. 그림은 프로젝트 안 파일만 넣는다(`![설명](docs/images/x.png)`).
- `SPEC.md`나 `CHANGELOG.md`를 고쳤으면 `node .project-check/render-spec-html.js .`로 HTML을 다시
  만들어 같은 커밋에 넣는다. HTML은 두 문서의 사본이므로 직접 고치지 않는다. 준비 검사가 낡은 HTML을
  실패로, 이름 없는 제목과 예시 블록 속 항목을 경고로 잡는다.

**SPEC / CODE 불일치** — 조용히 맞추지 말고 다음 형식으로 보고한다.

```text
SPEC / CODE MISMATCH

Requirement:
Specification:
Current Implementation:
Difference:
Action: SPEC 수정 / CODE 수정 / 사용자 확인 필요
```

코드의 현재 상태를 정당화하려고 SPEC을 고치지 않는다.

**ID 규칙** — `REQ-<CATEGORY>-NNN`, `NFR-<CATEGORY>-NNN`, `TEST-<CATEGORY>-NNN`.
CATEGORY는 대문자·숫자, NNN은 세 자리. 한 번 부여한 ID는 재사용하거나 의미를 바꾸지 않고,
삭제한 ID를 다른 기능에 돌려쓰지 않는다. 추적은 테스트 쪽에 남긴다(예: 테스트 위에
`Validates: REQ-QUERY-001`). 검색용 주석을 모든 함수에 강제로 달지 않는다.

**문서 경계** — 같은 내용을 두 곳에 두지 않는다.

| 파일 | 담는 것 |
|---|---|
| `SPEC.md` | 현재 시스템이 어떻게 동작해야 하는가 |
| `CHANGELOG.md` | 무엇이 변경되었는가 |
| `progress.md` | 현재 작업이 어디까지 진행됐는가 |
| `knowledge/` | AI가 작업할 때 필요한 판단 규칙·맥락 |
| `README.md` | 사람이 설치하고 사용하는 방법 |
| `AGENTS.md` | AI가 따라야 하는 작업 규칙 |

SPEC 내용을 `knowledge/`에 복제하지 않는다. knowledge는 Requirement ID를 **참조**만 한다
(예: "REQ-EXPORT-001을 고칠 때 한글 파일명 encoding 회귀를 항상 확인한다").
<!-- project-spec-guidance: end -->
