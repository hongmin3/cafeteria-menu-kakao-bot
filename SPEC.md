# 뷰밥 메뉴 알리미 사양서

<!-- spec-template: v1 -->

| 항목 | 값 |
|---|---|
| Document Version | 0.1.0 |
| Last Updated | 2026-09-21 |
| Status | draft — 기존 계약 일부의 근거 기반 사양화 |

이 문서는 기존 README와 테스트가 명시한 계약을 보존한다. 코드에 맞추어 기존 약속을 바꾸지 않는다. 차이가 발견되면 SPEC / CODE MISMATCH로 기록한다. 제품 전체 요구사항을 빠짐없이 문서화했다고 주장하지 않는다.

## 1. 목적

게시된 식단을 수집해 카카오톡 질문에 날짜와 끼니에 맞는 메뉴로 답한다.

## 2. 프로젝트 범위

이번 기준선에 포함: 조회 입력의 날짜 해석과 다음 주 제한.

이번 기준선의 확정 범위 밖: 실제 그룹웨어 접근, OCR 정확도 전체, 운영 채널 전송. 기존 기능을 제거하거나 변경한다는 뜻이 아니다.

## 5. 기능 요구사항

### REQ-CORE-001 끼니만 입력

기준시각과 아침/점심/저녁 입력을 받아 기준시각 당일의 해당 끼니로 해석한다. 2026-08-19 기준 아침은 2026-08-19 조식이다.

관련 구현: `src/menu_bot/query.py`. 관련 테스트: `tests/test_query.py`의 `test_plain_breakfast_means_today`.

### REQ-CORE-002 주말 요일 해석

토요일이나 일요일에 요일만 지정해도 현재 주의 해당 날짜로 해석한다. 2026-08-22에 월요일 아침은 2026-08-17 조식이고 scope는 current_week다.

관련 구현: `src/menu_bot/query.py`. 관련 테스트: `tests/test_query.py`의 `test_weekend_weekday_still_means_current_week`.

### REQ-CORE-003 다음 주 거부

다음 주를 명시한 질문은 현재 주나 오늘로 바꿔 식단을 제공하지 않는다. 조회 범위 안내를 반환하고 다음 주 데이터를 제공하지 않는다.

관련 구현: `src/menu_bot/query.py`. 관련 테스트: `tests/test_query.py`의 `test_next_week_is_never_served_or_falls_back_to_today`.

## 9. 오류 처리 정책

모호하거나 지원하지 않는 질문은 날짜나 끼니를 임의 선택하지 않고 안내한다. parser가 날짜를 해석할 수 있어도 answer 단계의 조회 제한을 우회해서는 안 된다.

## 11. 테스트 사양

격리된 개발 환경에서 프로젝트 의존성을 준비하고 저장소 루트에서 아래 명령을 실행한다. 현재 작업에서는 테스트 코드를 읽었으며 실제 실행 결과는 아직 확보하지 않았다. 테스트 파일의 설정이 운영 자원을 가리키지 않는지 먼저 확인한다.

```text
python -m pytest tests/test_query.py -q
```

### TEST-CORE-001

REQ-CORE-001 검증: `tests/test_query.py`의 `test_plain_breakfast_means_today` fixture와 assertion을 실행한다. 기대 결과는 해당 Requirement의 입력별 결과이며 assertion 실패는 통과로 처리하지 않는다.

### TEST-CORE-002

REQ-CORE-002 검증: `tests/test_query.py`의 `test_weekend_weekday_still_means_current_week` fixture와 assertion을 실행한다. 기대 결과는 해당 Requirement의 입력별 결과이며 assertion 실패는 통과로 처리하지 않는다.

### TEST-CORE-003

REQ-CORE-003 검증: `tests/test_query.py`의 `test_next_week_is_never_served_or_falls_back_to_today` fixture와 assertion을 실행한다. 기대 결과는 해당 Requirement의 입력별 결과이며 assertion 실패는 통과로 처리하지 않는다.

## 12. 요구사항 추적성

| Requirement | Implementation | Test | Status |
|---|---|---|---|
| REQ-CORE-001 | `src/menu_bot/query.py` | TEST-CORE-001: `tests/test_query.py` | implemented |
| REQ-CORE-002 | `src/menu_bot/query.py` | TEST-CORE-002: `tests/test_query.py` | implemented |
| REQ-CORE-003 | `src/menu_bot/query.py` | TEST-CORE-003: `tests/test_query.py` | implemented |

implemented는 연결된 구현·테스트 소스가 존재한다는 뜻이며 실제 실행 통과를 뜻하지 않는다.

## 13. 미확정 사항

- 수집·OCR·사업장 병합·알림 전체 요구사항과 운영 카카오 채널 검증은 확인 필요다. 현재 사양은 조회 핵심 계약에 한정한다.
- 이 기준선과 기존 전체 문서·기능의 누락 여부를 검토하기 전까지 프로젝트 전체 readiness 완료로 선언하지 않는다.
