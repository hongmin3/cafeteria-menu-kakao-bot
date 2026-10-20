# Changelog

이 파일은 **무엇이 바뀌었는가**만 담는다. 현재 사양은 `SPEC.md`, 현재 작업 진행 상태는
`progress.md`에 있다. 같은 내용을 두 곳에 쓰지 않는다.

가능하면 각 항목 앞에 Requirement ID를 붙인다.

```text
### Changed
- REQ-EXPORT-002: HTML 파일명에 실행 시간을 포함하도록 변경

### Fixed
- REQ-QUERY-001: 인증 만료 시 잘못된 성공 상태를 반환하던 문제 수정
```

Semantic Versioning은 강제하지 않는다. 프로젝트에 Versioning 정책이 있으면 그것을 따른다.

## [Unreleased]

### Added

- REQ-PARSE-002: 셀 상태 분류 자동 테스트(TEST-PARSE-002, `tests/test_parse_status.py`).
  전일 휴무는 세 끼 모두, `조식 미제공`은 그 끼니만, 특식은 미운영이 아닌 특식으로
  분류되는지 본다. 14절이 적어 둔 "파서 쪽부터 고정"을 실행한 것이다.
- NFR-SEC-001 / NFR-OPS-001 / NFR-PORT-001: 운영·보안·이식성 계약 검사(TEST-OPS-001,
  `tests/test_operational_contracts.py`). 추적 파일 위생과 git 실제 무시 동작, 웹훅
  토큰 불일치 404, 상시 유닛의 Restart·분리·메모리 상한, 타이머-서비스 짝, 시간대
  설정 사용을 고정한다.

### Changed

- SPEC 1절에 전체 흐름을 한 장으로 보여 주는 `한눈에 보기` 흐름도를 넣었다(공통 키트 workflow v8).
- REQ-SCRAPE-001 / REQ-OCR-001 / REQ-PARSE-002: 요구사항 카드의 관련 테스트와 11절 테스트 사양을 서로 맞췄다. TEST-SCRAPE-001은 실제 CLI인 `scrape` 다음 `ingest` 순서로 고쳤다.
- SPEC 문장을 처음 보는 사람도 읽을 수 있게 다시 썼다. 긴 문단은 나누고, 차례는 번호 목록, 예외는 `> **예외**` 상자, 이유는 `이유:` 줄로 옮겼다. 1절에 용어 표(`이 문서에서 쓰는 말`)를 더했다. 사양 내용(규칙·숫자·날짜·코드 이름·요구사항 ID·추적성 표)은 바꾸지 않았다(공통 SPEC workflow v5·렌더러 v5).
- 문서: 공통 SPEC workflow v4(AGENTS.md) — SPEC·CHANGELOG 작성 규칙(제목 이름, 기능 그룹 표, CHANGELOG ID, 예시 블록 금지, flow 흐름도, 로컬 이미지, HTML 재생성)을 한 절로 모았다. `docs/SPEC.html` 렌더러 v4: 왼쪽 목차에 지금 읽는 절·요구사항 표시.
- 준비 검사: CHANGELOG 형식 예시 블록에 실제 항목이 들어가면 `CHANGELOG_EXAMPLE_MODIFIED`로 경고한다(키트 관리 사본 `.project-check/project-readiness.js`, 기준 `.project-check/changelog-template.md`).
- NFR-OPS-001: 추적성 표의 구현 열이 디렉터리(`scripts/systemd/`)를 가리켜 검사기가
  파일 참조로 인정하지 않던 것을 실제 유닛 파일 경로로 바꿨다.
- REQ-SCRAPE-001 / REQ-OCR-001: 자동화할 수 없는 이유(사내망·플랫폼별 provider)를
  적은 수동 절차 TEST-SCRAPE-001 · TEST-OCR-001을 추가하고 추적성 표를 채웠다.
- 문서: CHANGELOG 머리의 형식 예시 블록 안에 들어가 있던 위 두 항목을 이 절로 옮겼다 — 예시 블록은
  이력으로 읽히지 않아 `docs/SPEC.html`의 요구사항별 변경 이력에서 빠져 있었다.
- 문서: `docs/SPEC.html`을 렌더러 v3로 다시 만들었다 — 이력이 없는 요구사항에 "기록된 변경 없음" 표시.
- 문서: `SPEC.md`의 REQ·NFR 제목 줄 15개에 기능 이름을 붙이고 5절에 기능 그룹 표를 추가했다.
  사양 내용은 바꾸지 않았다. 사람이 읽는 `docs/SPEC.html`(기능 목록·요구사항 카드·요구사항별
  변경 이력)과 렌더러 `.project-check/render-spec-html.js`를 추가하고 공통 SPEC workflow를 v3로
  갱신했다 — `SPEC.md`나 `CHANGELOG.md`를 고치면 HTML을 다시 만든다.
- 2026-09-25: 워크스페이스가 프로젝트를 `projects/` 아래로 모으면서 README의 `cd` 경로를 배치와 무관한 형태로 고쳤다. 준비 검사와 자체 테스트 통과.
- 2026-09-25: 공통 키트 이름이 Botyard로 바뀌어 `.project-check/`의 SPEC HTML 렌더러와 `docs/SPEC.html`의 생성기 표시를 갱신했다(형식·내용 변경 없음). 준비 검사와 자체 테스트 통과.
- 2026-09-26: 공통 키트 자동 반영용 검증 명령 파일 `botyard.json` 추가(키트 관리 파일만 바뀌면 이 명령과 준비 검사를 통과한 뒤 자동으로 커밋·push된다).
- 2026-09-26: 공통 키트(Botyard 59e195f) 갱신 반영 — .project-check/agents-spec-section.md, .project-check/manifest.json, .project-check/project-readiness.js, .project-check/render-spec-html.js, AGENTS.md, docs/SPEC.html. 준비 검사와 자체 테스트 통과.
- 2026-09-28: 공통 키트(Botyard a71bac0) 갱신 반영 — .project-check/manifest.json, .project-check/render-spec-html.js. 준비 검사와 자체 테스트 통과.
- 2026-10-17: 공통 키트(Botyard aa65a66) 갱신 반영 — .project-check/agents-spec-section.md, .project-check/manifest.json, .project-check/project-readiness.js, AGENTS.md. 준비 검사와 자체 테스트 통과.

### Fixed

### Removed

## 2026-10-20

- REQ-PARSE-003, REQ-PARSE-004, REQ-PARSE-005, REQ-PARSE-006: `main`과 합치면서 브랜치에서 `REQ-OCR-001`~`004`로 부르던 요구사항의 ID를 바꿨다. `REQ-OCR-001`은 `main`에서 먼저 정한 'OCR 결과의 공통 좌표 규칙'이다. 브랜치의 `REQ-CORE-001`~`003`(끼니만 입력, 주말 요일, 다음 주 거부)은 REQ-QUERY-001·REQ-QUERY-002에 이미 있어 따로 두지 않는다.
- REQ-PARSE-001: 날짜 줄로 받는 범위를 주 시작일에서 10일에서 14일로 넓혔다(REQ-PARSE-006).

- REQ-ADV-003: Claude CLI 출력의 HTTP 상태 코드(`api_error_status`)로 실패 종류를 먼저 가린다. 실제 미로그인 문구 `Not logged in · Please run /login`과 `hit your session limit` 같은 한도 문구를 확인해 반영했다. `Context limit reached`를 한도 초과로 잘못 분류하던 문제를 고쳤다.

- REQ-ADV-001: 식단표 읽은 결과에 이상 신호(메뉴 0건인 날짜, 일반식 1~2개, 메뉴로 남은 큰 글씨)가 있으면 운영 서버의 Claude CLI에게 그림을 보여 주고 판정을 묻는다. 같은 그림의 답은 저장해 두고 다시 묻지 않는다.
- REQ-ADV-002: Claude 답 중 "음식이 아닌 항목"과 "식당 미운영"만 반영한다. 이미 읽은 글자와 맞을 때만 반영하고 메뉴를 새로 만들지 않는다.
- REQ-ADV-003: Claude 자문이 사용 한도 초과, 로그인 만료, 시간 초과, 서비스 오류, 답 형식 오류, CLI 없음으로 실패하면 읽은 결과를 그대로 저장하고 알림 메일을 보낸다. 같은 종류는 12시간에 한 번 보낸다. `menu-bot advisor-check` 명령을 추가했다.

- REQ-PARSE-005: 날짜 칸에 메뉴 대신 행사 그림만 있으면 세 끼 모두 식당 미운영으로 안내한다. 10/22 체육대회 그림의 글자가 `뷰웍스`(조식 PLUS), `체육대황`(중식 일반식) 메뉴로 표시되던 문제를 고쳤다.
- REQ-PARSE-005: 그림 글자 `체육대황`을 `체육대회`로 고치는 표기 교정을 추가했다.
- REQ-PARSE-006: 이번 주 식단표가 지난주 게시글에 붙어 올라온 경우 10/23(금) 메뉴가 통째로 빠지던 문제를 고쳤다. 게시글 시작일에서 14일 안의 날짜 줄을 받는다.

## 2026-10-06

- REQ-PARSE-004: 설 명절·한가위 연휴·임시 공휴일·대체 휴일과 식당 휴무 문구를 처리한다. 장식 기호·요일·휴무 안내 어미도 구분한다.
- REQ-PARSE-004: 같은 날짜에서 가까이 붙은 OCR 조각을 안내 문구로 합친다. 날짜·기간이 붙거나 여러 날짜에 걸친 안내를 해당 날짜별로 처리한다. 잘못된 날짜는 다른 메뉴 수집을 중단하지 않는다.
- REQ-PARSE-004: 공휴일 특식을 휴무로 오인하거나 끼니별 미운영을 전일 휴무로 확대하는 문제를 고쳤다. 한 게시물의 다른 이미지에 음식이 있으면 이름만으로 만든 휴무 안내를 제외한다.
- REQ-PARSE-004: 회귀 테스트를 71개로 확장했다. 운영 서버의 과거 OCR 캐시 57장에서 정상 메뉴 변경이 없고 현재 운영 항목 154개도 동일함을 확인했다.
- REQ-PARSE-003: 식단표에 공휴일 이름만 있는 날짜를 세 끼 모두 식당 미운영으로 안내한다. 한글날을 중식 일반식 메뉴로 표시하던 문제를 고쳤다.
- REQ-PARSE-003: 공휴일 이름의 띄어쓰기·괄호를 처리한다. 음식이 함께 있는 날짜, 공휴일 특식과 끼니별 미운영 안내는 유지한다.
- REQ-PARSE-003: 휴무 이름 20종·표기, 특식 4종, 음식이 있는 날짜와 끼니별 휴무를 확인하는 회귀 테스트를 추가했다.

## 2026-09-21

- 기존 구현과 테스트에서 확인한 핵심 계약 3개를 SPEC.md의 첫 기준선으로 문서화했다.
- 테스트 경로와 구현 경로를 연결하고 범위 밖·미확정 사항을 구분했다.
- 기능, 인증, 배포, 예약 실행 및 기존 사용자 파일은 변경하지 않았다.
- 실제 테스트 실행·운영 검증 완료를 이 변경으로 주장하지 않는다.

## [1.0.0] - 2026-09-19

### Added

- SPEC.md 도입 — 기존 동작을 Requirement로 문서화 (REQ-*/NFR-*)
