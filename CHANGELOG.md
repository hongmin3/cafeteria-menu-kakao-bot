# Changelog

이 파일은 **무엇이 바뀌었는가**만 담는다. 현재 사양은 `SPEC.md`, 현재 작업 진행 상태는
`progress.md`에 있다. 같은 내용을 두 곳에 쓰지 않는다.

가능하면 각 항목 앞에 Requirement ID를 붙인다.

```text
### Changed

- NFR-OPS-001: 추적성 표의 구현 열이 디렉터리(`scripts/systemd/`)를 가리켜 검사기가
  파일 참조로 인정하지 않던 것을 실제 유닛 파일 경로로 바꿨다.
- REQ-SCRAPE-001 / REQ-OCR-001: 자동화할 수 없는 이유(사내망·플랫폼별 provider)를
  적은 수동 절차 TEST-SCRAPE-001 · TEST-OCR-001을 추가하고 추적성 표를 채웠다.
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

### Fixed

### Removed

## [1.0.0] - 2026-09-19

### Added

- SPEC.md 도입 — 기존 동작을 Requirement로 문서화 (REQ-*/NFR-*)
