# Architecture

## Data flow
<!-- akela: id=data-flow scope=develop,test,operate tier=must -->
Playwright로 주간 식단 이미지를 수집하고 플랫폼별 OCR provider와 parser로 구조화한 뒤 SQLite에 저장한다. FastAPI의 카카오 Skill API는 저장된 현재 주 데이터를 조회해 응답한다.

## Module boundaries
<!-- akela: id=module-boundaries scope=develop,test tier=should -->
CLI는 `src/menu_bot/cli.py`, 수집·OCR·파싱은 `scraper.py`, `ocr.py`, `ocr_provider.py`, `vision_ocr.swift`, `parser.py`, `pipeline.py`, 저장·조회는 `db.py`, `query.py`, API는 `web.py`가 담당한다. 요청과 직접 관련된 경계만 변경한다.

## Platform constraint
<!-- akela: id=ocr-provider scope=develop,operate tier=must -->
`OCR_PROVIDER=auto`는 macOS에서 Apple Vision, Windows·Linux에서 PaddleOCR을 선택한다. 두 provider는 parser가 기대하는 좌측 하단 원점의 동일 정규화 좌표 contract를 반환해야 하며, provider 변경은 해당 플랫폼 fixture와 실제 이미지 비교 근거를 필요로 한다.
