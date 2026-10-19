"""Validates: REQ-ADV-001, REQ-ADV-002. 실제 Claude는 부르지 않고 응답을 주입한다."""
import json
from datetime import date

import pytest

from menu_bot import advisor
from menu_bot.models import SourcePost
from menu_bot.parser import parse_ocr_lines


def line(text, x, y, width=0.07, height=0.026):
    return dict(text=text, x=x, y=y, width=width, height=height, confidence=0.99)


LABELS = [
    line('일반식', 0.074, 0.772, 0.033, 0.028), line('조식', 0.012, 0.736, 0.033, 0.038),
    line('PLUS코너', 0.064, 0.677, 0.053, 0.026),
    line('일반식', 0.074, 0.534, 0.034, 0.027), line('중식', 0.012, 0.465, 0.031, 0.037),
    line('석식', 0.01, 0.211, 0.034, 0.04), line('일반식', 0.074, 0.231, 0.034, 0.029),
]
HEADERS = [
    line('10/21(수)', 0.532, 0.862, 0.066, 0.04),
    line('10/22(목)', 0.706, 0.868, 0.064, 0.031),
    line('10/23(금)', 0.878, 0.867, 0.065, 0.033),
]


def column(x, *foods):
    return [line(food, x, 0.835 - index * 0.03) for index, food in enumerate(foods)] + [
        line(f'{foods[0]}국', x, 0.582), line('쌀밥', x, 0.552), line('김치', x, 0.522),
        line(f'{foods[0]}덮밥', x, 0.295), line('깍두기', x, 0.265), line('샐러드', x, 0.235),
    ]


WEDNESDAY = column(0.532, '건새우아욱국', '닭살볶음', '쌀밥')
FRIDAY = column(0.878, '얼큰양해장국', '스크램블에그', '쌀밥')
POST = SourcePost(post_id='p', title='[테스트] 2026-10-19 ~ 2026-10-23', location='테스트',
                  start_date=date(2026, 10, 19))
THU = date(2026, 10, 22)


class FakeClaude:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def __call__(self, prompt, cwd):
        self.prompts.append(prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply, ensure_ascii=False)


@pytest.fixture
def image(tmp_path):
    path = tmp_path / 'menu.png'
    path.write_bytes(b'png')
    return path


class MailSpy:
    def __init__(self, ok=True):
        self.sent = []
        self.ok = ok

    def __call__(self, subject, body, progress=print):
        self.sent.append((subject, body))
        return self.ok


def run(lines, image, reply, mail=None):
    entries = parse_ocr_lines(POST, 'url', lines)
    fake = FakeClaude(reply)
    result = advisor.advise(POST, image, lines, entries, runner=fake, enabled=True,
                            send=mail or MailSpy(), sleep=lambda seconds: None,
                            alert_state_path=image.parent / 'alert.json')
    return entries, result, fake


def thursday(entries):
    return {(e.meal_type, e.category, e.status, e.menu_text) for e in entries if e.service_date == THU}


def test_clean_board_never_calls_claude(image):
    thursday_food = column(0.706, '미나리돼지곰탕', '메추리알조림', '쌀밥')
    entries, result, fake = run(LABELS + HEADERS + WEDNESDAY + thursday_food + FRIDAY, image, {'days': []})
    assert fake.prompts == []
    assert result == entries


def test_short_main_cell_asks_and_closes_day(image):
    odd = [line('운동회날', 0.706, 0.582, 0.08, 0.03)]
    reply = {'days': [{'date': '2026-10-22', 'closed': True, 'closed_label': '운동회날', 'not_food': ['운동회날']}]}
    entries, result, fake = run(LABELS + HEADERS + WEDNESDAY + odd + FRIDAY, image, reply)
    assert len(fake.prompts) == 1 and '2026-10-22' in fake.prompts[0] and '운동회날' in fake.prompts[0]
    assert thursday(result) == {(meal, '안내', 'no_service', '운동회날 (식당 미운영)') for meal in ('조식', '중식', '석식')}
    # 다른 날짜는 그대로다.
    assert [e for e in result if e.service_date != THU] == [e for e in entries if e.service_date != THU]
    saved = json.loads((image.parent / 'menu.png.advice.json').read_text(encoding='utf-8'))
    assert saved['changes'] and saved['verdict'] == reply


def test_unverified_label_falls_back_to_generic_notice(image):
    odd = [line('ㅇㅇ행사', 0.706, 0.582, 0.08, 0.03)]
    reply = {'days': [{'date': '2026-10-22', 'closed': True, 'closed_label': '창립기념 체육대회'}]}
    _, result, _ = run(LABELS + HEADERS + WEDNESDAY + odd + FRIDAY, image, reply)
    assert {text for *_, text in thursday(result)} == {'식단표에 메뉴 없음 (식당 미운영)'}


def test_not_food_removes_only_exact_items_and_never_adds(image):
    short = [line('불고기덮밥', 0.706, 0.582), line('뷰웍스로고', 0.706, 0.552)]
    reply = {'days': [{'date': '2026-10-22', 'closed': False,
                       'not_food': ['뷰웍스로고', '없던메뉴'], 'menu': ['제육볶음']}]}
    _, result, _ = run(LABELS + HEADERS + WEDNESDAY + short + FRIDAY, image, reply)
    assert thursday(result) == {('중식', '일반식', 'normal', '불고기덮밥')}


def test_closed_ignored_when_real_food_remains(image):
    short = [line('불고기덮밥', 0.706, 0.582)] + [line('잡채', 0.706, 0.835), line('쌀밥', 0.706, 0.805),
                                               line('김치', 0.706, 0.775)]
    reply = {'days': [{'date': '2026-10-22', 'closed': True, 'closed_label': '한글날'}]}
    entries, result, _ = run(LABELS + HEADERS + WEDNESDAY + short + FRIDAY, image, reply)
    # 조식 일반식(3개)은 이상 신호가 아닌 진짜 음식이라 휴무로 바꾸지 않는다.
    assert thursday(result) == thursday(entries)


def test_empty_day_needs_verified_label(image):
    lines = LABELS + HEADERS + WEDNESDAY + FRIDAY
    _, result, fake = run(lines, image, {'days': [{'date': '2026-10-22', 'closed': True, 'closed_label': '체육대회'}]})
    assert fake.prompts and thursday(result) == set()
    image.with_name('menu.png.advice.json').unlink()
    _, result, _ = run(lines, image, {'days': [{'date': '2026-10-22', 'closed': True, 'closed_label': '개천절'}]})
    assert {text for *_, text in thursday(result)} == {'개천절 (식당 미운영)'}


def test_days_without_signal_are_not_touched(image):
    odd = [line('운동회날', 0.706, 0.582, 0.08, 0.03)]
    reply = {'days': [{'date': '2026-10-23', 'closed': True, 'closed_label': '한글날', 'not_food': ['쌀밥']}]}
    entries, result, _ = run(LABELS + HEADERS + WEDNESDAY + odd + FRIDAY, image, reply)
    assert result == entries


ODD = [line('운동회날', 0.706, 0.582, 0.08, 0.03)]


@pytest.mark.parametrize('reply, kind', [
    (RuntimeError('boom'), 'unstable'), ('not json', 'bad_answer'), ('{"days": "x"}', 'bad_answer'),
    ('[]', 'bad_answer'), ({'days': [{'date': '2026-10-22', 'not_food': 3}]}, 'bad_answer'),
    (advisor.AdvisorError('limit', "You've hit your limit"), 'limit'),
    (advisor.AdvisorError('auth', 'Please run /login'), 'auth'),
    (advisor.AdvisorError('timeout', '180초'), 'timeout'),
    (advisor.AdvisorError('missing', 'no claude'), 'missing'),
])
def test_failures_keep_parser_result_and_mail_operator(image, reply, kind):
    mail = MailSpy()
    entries, result, fake = run(LABELS + HEADERS + WEDNESDAY + ODD + FRIDAY, image, reply, mail)
    assert fake.prompts and result == entries
    assert len(mail.sent) == 1
    subject, body = mail.sent[0]
    assert advisor.FAILURE_LABELS[kind] in subject
    assert '2026-10-22' in body and '운동회날' in body and POST.title in body
    assert not (image.parent / 'menu.png.advice.json').exists()


def test_unstable_service_is_retried_once():
    calls = []

    def flaky(prompt, cwd):
        calls.append(1)
        if len(calls) == 1:
            raise advisor.AdvisorError('unstable', 'API Error: 529 Overloaded')
        return '{"days": []}'

    waits = []
    assert advisor.ask_with_retry(flaky, 'p', None, sleep=waits.append) == {'days': []}
    assert len(calls) == 2 and waits == [advisor.RETRY_WAIT_SECONDS]


@pytest.mark.parametrize('kind', ['limit', 'auth', 'timeout', 'missing'])
def test_limit_auth_timeout_are_not_retried(kind):
    calls = []

    def failing(prompt, cwd):
        calls.append(1)
        raise advisor.AdvisorError(kind, 'x')

    with pytest.raises(advisor.AdvisorError) as caught:
        advisor.ask_with_retry(failing, 'p', None, sleep=lambda s: None)
    assert caught.value.kind == kind and len(calls) == 1


def test_same_failure_mailed_once_per_interval(image):
    error = advisor.AdvisorError('limit', 'limit reached')
    mail, state = MailSpy(), image.parent / 'alert.json'
    report = lambda err, now: advisor.report_failure(err, POST, 'menu.png', [], send=mail, state_path=state, now=now)
    assert report(error, 1000.0)
    assert not report(error, 1000.0 + 3600)
    assert report(advisor.AdvisorError('auth', 'x'), 1000.0 + 3600)
    assert report(error, 1000.0 + advisor.ALERT_INTERVAL_HOURS * 3600)
    assert len(mail.sent) == 3


def test_failed_mail_is_retried_next_time(image):
    error, state = advisor.AdvisorError('limit', 'x'), image.parent / 'alert.json'
    assert not advisor.report_failure(error, POST, 'm', [], send=MailSpy(ok=False), state_path=state, now=1.0)
    retry = MailSpy()
    assert advisor.report_failure(error, POST, 'm', [], send=retry, state_path=state, now=2.0)
    assert len(retry.sent) == 1


@pytest.mark.parametrize('text, kind', [
    ("Claude AI usage limit reached|1761000000", 'limit'),
    ("You've hit your limit · resets 3pm", 'limit'),
    ('API Error: 429 rate_limit_error', 'limit'),
    ('Credit balance is too low', 'limit'),
    ('Invalid API key · Please run /login', 'auth'),
    ('OAuth token has expired. Please obtain a new token', 'auth'),
    ('API Error: 529 {"type":"overloaded_error"}', 'unstable'),
    ('API Error: 500 Internal server error', 'unstable'),
    ('Connection error.', 'unstable'),
    ('종료 코드 1: ', 'unstable'),
    # 2026-10-20 서버 CLI(2.1.299)에서 관찰·추출한 실제 문구.
    ('Not logged in · Please run /login', 'auth'),
    ('You have hit your session limit · resets 3pm', 'limit'),
    ('weekly limit reached', 'limit'),
    ('Budget limit reached ($5.00 spent of the $5 maximum)', 'limit'),
    ('Context limit reached', 'unstable'),
])
def test_classify_failure(text, kind):
    assert advisor.classify_failure(text) == kind


class Completed:
    def __init__(self, stdout='', stderr='', returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


@pytest.mark.parametrize('completed, kind', [
    (Completed(json.dumps({'is_error': True, 'result': 'Claude AI usage limit reached|1761'}), returncode=1), 'limit'),
    (Completed(json.dumps({'is_error': True, 'result': 'Invalid API key · Please run /login'})), 'auth'),
    (Completed('', 'API Error: 529 Overloaded', 1), 'unstable'),
    (Completed('<html>gateway</html>', '', 0), 'unstable'),
    # 실제 미로그인 출력(서버에서 빈 설정 폴더로 관찰): 상태 코드 없이 문구만 온다.
    (Completed(json.dumps({'is_error': True, 'api_error_status': None,
                           'result': 'Not logged in · Please run /login'}), returncode=1), 'auth'),
    # 상태 코드가 있으면 문구보다 코드를 먼저 본다.
    (Completed(json.dumps({'is_error': True, 'api_error_status': 429, 'result': 'API Error'}), returncode=1), 'limit'),
    (Completed(json.dumps({'is_error': True, 'api_error_status': 401, 'result': 'API Error'}), returncode=1), 'auth'),
    (Completed(json.dumps({'is_error': True, 'api_error_status': 529, 'result': 'rate limit'}), returncode=1), 'unstable'),
])
def test_run_claude_classifies_cli_errors(monkeypatch, tmp_path, completed, kind):
    monkeypatch.setattr(advisor, 'claude_path', lambda: 'claude')
    monkeypatch.setattr(advisor.subprocess, 'run', lambda *a, **k: completed)
    with pytest.raises(advisor.AdvisorError) as caught:
        advisor.run_claude('p', tmp_path)
    assert caught.value.kind == kind


def test_run_claude_timeout_and_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(advisor, 'claude_path', lambda: 'claude')

    def slow(*args, **kwargs):
        raise advisor.subprocess.TimeoutExpired('claude', advisor.TIMEOUT_SECONDS)

    monkeypatch.setattr(advisor.subprocess, 'run', slow)
    with pytest.raises(advisor.AdvisorError) as caught:
        advisor.run_claude('p', tmp_path)
    assert caught.value.kind == 'timeout'
    monkeypatch.setattr(advisor, 'claude_path', lambda: None)
    with pytest.raises(advisor.AdvisorError) as caught:
        advisor.run_claude('p', tmp_path)
    assert caught.value.kind == 'missing'


def test_run_claude_returns_result(monkeypatch, tmp_path):
    monkeypatch.setattr(advisor, 'claude_path', lambda: 'claude')
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(args=args, cwd=kwargs['cwd'], timeout=kwargs['timeout'])
        return Completed(json.dumps({'is_error': False, 'result': '{"days": []}'}))

    monkeypatch.setattr(advisor.subprocess, 'run', fake_run)
    assert advisor.run_claude('p', tmp_path) == '{"days": []}'
    assert seen['args'][:2] == ['claude', '-p'] and '--allowedTools' in seen['args']
    assert seen['cwd'] == tmp_path and seen['timeout'] == advisor.TIMEOUT_SECONDS


def test_mode_on_without_cli_reports_missing(image, monkeypatch):
    monkeypatch.setenv('MENU_ADVISOR', 'on')
    monkeypatch.setattr(advisor, 'claude_path', lambda: None)
    lines = LABELS + HEADERS + WEDNESDAY + ODD + FRIDAY
    entries = parse_ocr_lines(POST, 'url', lines)
    mail = MailSpy()
    result = advisor.advise(POST, image, lines, entries, send=mail, alert_state_path=image.parent / 'a.json')
    assert result == entries
    assert advisor.FAILURE_LABELS['missing'] in mail.sent[0][0]


def test_answer_is_cached_per_image_and_signals(image):
    lines = LABELS + HEADERS + WEDNESDAY + [line('운동회날', 0.706, 0.582, 0.08, 0.03)] + FRIDAY
    entries = parse_ocr_lines(POST, 'url', lines)
    fake = FakeClaude({'days': [{'date': '2026-10-22', 'closed': True, 'closed_label': '운동회날'}]})
    first = advisor.advise(POST, image, lines, entries, runner=fake, enabled=True)
    second = advisor.advise(POST, image, lines, entries, runner=fake, enabled=True)
    assert len(fake.prompts) == 1 and first == second


def test_large_text_left_as_menu_is_a_signal(image):
    lines = LABELS + HEADERS + WEDNESDAY + FRIDAY + column(0.706, '미나리돼지곰탕', '메추리알조림', '쌀밥') + [
        line('가을맞이', 0.706, 0.70, 0.08, 0.07)]
    entries = parse_ocr_lines(POST, 'url', lines)
    signals = advisor.find_signals(POST, lines, entries)
    assert [s['date'] for s in signals] == ['2026-10-22']
    assert '가을맞이' in signals[0]['suspicious']


def test_disabled_or_missing_cli_never_calls(image, monkeypatch):
    lines = LABELS + HEADERS + WEDNESDAY + [line('운동회날', 0.706, 0.582, 0.08, 0.03)] + FRIDAY
    entries = parse_ocr_lines(POST, 'url', lines)
    fake = FakeClaude({'days': []})
    assert advisor.advise(POST, image, lines, entries, runner=fake) == entries  # conftest가 off로 둔다
    monkeypatch.setenv('MENU_ADVISOR', 'auto')
    monkeypatch.setattr(advisor, 'claude_path', lambda: None)
    assert advisor.advise(POST, image, lines, entries, runner=fake) == entries
    assert fake.prompts == []
