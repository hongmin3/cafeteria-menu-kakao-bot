# 뷰밥 메뉴 알리미 AI 인덱스

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
