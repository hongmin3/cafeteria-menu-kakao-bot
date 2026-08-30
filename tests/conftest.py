"""테스트가 실제 메일을 보내지 못하게 막는다.

알림 함수들은 `send=` 인자로 발송기를 주입받고, 기본값은 **진짜 SMTP 발송**인
`send_mail`이다. 테스트에서 주입을 한 번 빠뜨리면 그대로 Gmail로 나간다.
2026-08-31에 실제로 그런 일이 있었다: `progress`는 no-op으로 주입하고 `send`만
빠뜨린 테스트가 있어, 서버에서 pytest를 돌릴 때마다 "08/24~08/28 식단을 아직
못 받았습니다" 메일이 운영 담당자에게 날아갔다. 로그도 남지 않아(progress가
no-op이라) 출처를 찾는 데 한참 걸렸다.

주입을 잊는 일은 또 생긴다. 그래서 개별 테스트를 고치는 것과 별개로, 여기서
소켓 앞단을 막는다. 아래 두 겹 중 하나만 뚫려도 메일은 나가지 않는다.
"""

import smtplib

import pytest


class _BlockedSMTP:
    def __init__(self, *args, **kwargs):
        raise AssertionError(
            "테스트가 실제 SMTP 연결을 열려고 했습니다. 알림을 검증하려면 "
            "send=MailSpy() 처럼 발송기를 주입하세요."
        )


@pytest.fixture(autouse=True)
def block_outgoing_mail(monkeypatch):
    # 1겹: 설정을 비워 send_mail이 발송 전에 스스로 물러나게 한다.
    for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "NOTIFY_EMAIL_TO", "NOTIFY_EMAIL_FROM"):
        monkeypatch.setenv(name, "")
    # 2겹: 그래도 연결을 시도하면 실패시킨다. send_mail은 예외를 삼키고 False를
    # 돌려주므로 테스트는 "발송 실패"로 흘러가고, 진짜 메일은 나가지 않는다.
    monkeypatch.setattr(smtplib, "SMTP", _BlockedSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _BlockedSMTP)
