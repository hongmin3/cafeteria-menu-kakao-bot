# Workflow

## Safe validation
<!-- akela: id=safe-validation scope=develop,test tier=must -->
정적·로컬 검증은 `.venv/bin/python -m compileall -q src tests`와 `.venv/bin/python -m pytest -q`를 우선한다. 기능 변경에는 관련 테스트를 추가하거나 갱신한다.

## Operational changes
<!-- akela: id=operational-changes scope=operate,deploy tier=must -->
수집, 운영 DB 갱신, 서버·터널 실행은 외부 시스템이나 로컬 데이터를 바꿀 수 있다. 사용자 요청 범위에 포함될 때만 README의 운영 순서를 사용한다.

## Kakao contract
<!-- akela: id=kakao-contract scope=develop,test,deploy tier=must -->
카카오 응답 형식, 웹훅 token 처리, 운영 script와 배포 Workflow는 관련 요구와 회귀 검증 없이 변경하지 않는다.
