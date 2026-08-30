# Troubleshooting

## Current-week rule
<!-- akela: id=current-week scope=develop,test,operate tier=must -->
사용자 응답은 현재 주 메뉴만 제공하고 과거 데이터는 OCR·parser 학습 검증용으로 분리한다. 이 경계를 오류 수정 과정에서 합치지 않는다.

## Diagnostic scope
<!-- akela: id=diagnostic-scope scope=develop,test,operate tier=should -->
대상 함수와 실패 테스트부터 확인한다. 이미지, SQLite DB, OCR manifest는 데이터 자체가 문제일 때만 최소 범위로 확인한다.

## Secret and generated data
<!-- akela: id=secrets scope=all tier=must -->
`.env`, 내부 URL, 계정, 원본 이미지, OCR 결과, SQLite DB, token, log를 Knowledge·Evidence·응답·Git에 복사하지 않는다.
