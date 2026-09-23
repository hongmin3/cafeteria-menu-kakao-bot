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

### Fixed

### Removed

## [1.0.0] - 2026-09-19

### Added

- SPEC.md 도입 — 기존 동작을 Requirement로 문서화 (REQ-*/NFR-*)
