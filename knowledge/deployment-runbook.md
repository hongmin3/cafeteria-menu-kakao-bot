# 배포 런북

사내 QA 서버(10.13.0.222)에 배포/운영 변경을 할 때 지켜야 하는 절차. 이 서비스는 실제 운영 중인 프로덕션이므로 아래 규칙을 벗어나는 임의 조치를 하지 않는다.

## 서버 정보 (server-info)

- 운영 서버: `10.13.0.222` (Ubuntu 24.04, Python 3.12), `ssh ubuntu@10.13.0.222`.
- 서버 앱 경로: 권한 700, git 저장소 아님(파일 복사로만 배포).
- 스킬 서버는 `127.0.0.1:18080`(`MENUBOT_PORT`)에만 바인딩하고, 외부 노출은 ngrok 고정 도메인이 담당한다. 사내망에 직접 열지 않는다.
- 같은 서버에 다른 팀 서비스가 함께 돈다. 배포 전 `ss -tlnp`로 포트 충돌을 확인해야 한다(`check-linux-env.sh`가 점검).

## .env는 절대 로컬로 덮어쓰지 않는다

- **서버 `.env`를 로컬 `.env`로 덮어쓰지 말 것.** 서버에만 있는 값이 있다(`SMTP_PASSWORD` — 서버에서 직접 입력한 값).
- 과거 사고: 배포 아카이브에 `.env`를 포함해 올렸다가 방금 입력해둔 SMTP 앱 비밀번호가 지워진 적이 있다. 백업이 없어 재입력만이 유일한 복구 수단이었다.
- 배포 시 보낼 것: `src/`, `tests/`, `scripts/`, `README.md`, `.env.example`, (필요하면) `data/menu_vocab.json`. **`.env`는 절대 보내지 않는다.**
- 새 설정 키가 필요하면 `.env`를 통째로 덮어쓰지 말고 없는 키만 추가한다:
  ```bash
  ssh ubuntu@10.13.0.222 'cd ~/cafeteria-menu-kakao-bot && grep -q "^NEW_KEY=" .env || echo "NEW_KEY=값" >> .env'
  ```
- 배포 후에는 반드시 `scripts/check-linux-env.sh`를 돌린다. 8번 항목이 `SMTP_PASSWORD` 누락을 잡아준다.

## systemd 타이머와 시간대(America/New_York) 이슈

- **서버 시스템 시간대는 `America/New_York`이다.** 다른 서비스의 로그 타임스탬프에 영향을 주므로 시스템 시간대 자체는 바꾸지 않는다.
- 대신 모든 `OnCalendar`에 `Asia/Seoul`을 명시한다(systemd 252+ 필요). 조회 로직도 코드에서 항상 명시적으로 `Asia/Seoul`을 사용하므로 시스템 시간대와 무관하게 동작한다.
- 새 타이머를 추가할 때 `OnCalendar=... Asia/Seoul` 표기를 빠뜨리면 실제 실행 시각이 4~5시간 어긋난다.

## 등록된 systemd 유닛

| 유닛 | 트리거(KST) | 동작 |
|---|---|---|
| `menubot-web.service` | 부팅 시 | FastAPI 서버, 죽으면 5초 후 재시작 |
| `menubot-tunnel.service` | 부팅 시 | ngrok 터널, 죽으면 10초 후 재시작 |
| `menubot-collect.timer` | 월 08:00 | 운영 수집(scrape+ingest), 안전망 |
| `menubot-nextweek-friday.timer` | 금 22:00 | 다음 주 게시글 1회 확인 |
| `menubot-nextweek-weekend.timer` | 토·일 00:05부터 2시간 간격 | 다음 주 게시글 반복 확인 |
| `menubot-nextweek-deadline.timer` | 일 22:00 | 마지막 시도 후 미확보면 알림 메일 |
| `menubot-ensure.timer` | 일 23:00~금 23:00 매시 정각 | DB에 없으면 재수집, 있으면 즉시 종료 |

- `menubot-web`과 `menubot-tunnel`은 서로 `BindsTo`로 묶지 않는다. 웹 서버 재시작 중 터널까지 내려가면 터널이 스스로 복구할 근거가 없어 영구히 죽기 때문이다. 각자 `Restart=always`로 독립적으로 살아나게 둔다.
- 수집·주말 폴링류 서비스에는 `MemoryHigh=3G` + `MemoryMax=4G`를 걸어 PaddleOCR·Chromium이 같은 서버의 다른 서비스를 밀어내지 않게 한다.

## 배포 전후 점검 (deploy-checks)

- 배포 전: `pytest`, `python -m compileall -q src tests` 통과 확인, 포트 충돌 확인.
- 배포 후: `scripts/check-linux-env.sh` 실행(venv·PaddleOCR·Chromium·ngrok 설치, `.env` 키 존재, 그룹웨어 접속, systemd 유닛 상태를 읽기 전용으로 점검), `curl http://127.0.0.1:18080/health` 확인.
- 되돌리려면 `sudo ./scripts/unregister-linux-services.sh`로 `menubot-*` 유닛만 제거한다(다른 서비스는 건드리지 않음).
