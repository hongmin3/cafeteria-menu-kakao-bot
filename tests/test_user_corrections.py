"""운영자가 직접 관리하는 교정 목록.

코드에 고정된 `SUBSTITUTIONS`는 1년치 대조로 근거를 확인한 것이라 개발자가
손대는 자리다. 하지만 새 오인식은 매주 나오고, 그때마다 코드를 고쳐 배포할
수는 없다. 그래서 파일 한 줄로 규칙을 더할 수 있게 했고, 여기서 확인하는 것은
**개발자가 아닌 사람이 편집해도 안전한가**이다 — 오타 한 줄이 나머지 교정을
무너뜨리지 않는가, 파일이 없어도 조용히 동작하는가.
"""

from pathlib import Path

from menu_bot.corrections import (
    SUBSTITUTIONS,
    apply_substitutions,
    correct_item,
    load_user_corrections,
    parse_user_corrections,
)


def test_reads_one_rule_per_line():
    rules = parse_user_corrections("누륭지 = 누룽지\n가마보끄 = 가마보꼬\n")

    assert rules == {"누륭지": "누룽지", "가마보끄": "가마보꼬"}


def test_ignores_comments_and_blank_lines():
    """헤더 주석이 그대로 들어 있어도 규칙만 읽는다."""
    rules = parse_user_corrections(
        "# 메뉴 표기 교정 목록\n"
        "#\n"
        "# 누륭지 = 누룽지  ← 이건 예시라 적용되면 안 된다\n"
        "\n"
        "롯두부 = 톳두부\n"
    )

    assert rules == {"롯두부": "톳두부"}


def test_a_broken_line_does_not_take_the_others_down():
    """오타 한 줄 때문에 나머지 교정까지 사라지면 안 된다.

    파일을 편집하는 사람이 개발자가 아니다. 한 줄이 이상하면 그 줄만 버린다.
    """
    rules = parse_user_corrections(
        "누륭지 = 누룽지\n"
        "이건등호가없는줄\n"
        " = 오른쪽만있음\n"
        "왼쪽만있음 = \n"
        "같음 = 같음\n"
        "롯두부 = 톳두부\n"
    )

    assert rules == {"누륭지": "누룽지", "롯두부": "톳두부"}


def test_missing_file_is_not_an_error(tmp_path: Path):
    """파일이 없으면 코드에 고정된 목록만으로 조용히 돌아간다."""
    assert load_user_corrections(tmp_path / "없는파일.txt") == {}


def test_unreadable_file_is_not_an_error(tmp_path: Path):
    """디렉터리를 가리키는 등 읽을 수 없어도 수집을 멈추지 않는다."""
    assert load_user_corrections(tmp_path) == {}


def test_user_rules_win_over_the_built_in_list(monkeypatch, tmp_path: Path):
    """같은 표기를 두 곳에서 다르게 고치라 하면 방금 적은 쪽을 따른다."""
    path = tmp_path / "menu_corrections.txt"
    path.write_text("숭능 = 숭늉물\n", encoding="utf-8")
    monkeypatch.setenv("MENU_CORRECTIONS_PATH", str(path))
    monkeypatch.setattr("menu_bot.corrections._cached_substitutions", None)

    assert SUBSTITUTIONS["숭능"] == "숭늉"  # 코드 목록은 그대로 두고
    assert apply_substitutions("숭능") == "숭늉물"  # 파일이 이긴다


def test_substitutions_do_not_drop_text(monkeypatch, tmp_path: Path):
    """재적용은 표기만 바꾼다 — 노이즈 판정으로 문구를 지우지 않는다.

    이미 저장된 값은 한 번 걸러진 결과다. 그 위에 노이즈 규칙을 다시 돌리면
    `대체 휴무` 같은 안내가 사라질 수 있다.
    """
    monkeypatch.setattr("menu_bot.corrections._cached_substitutions", None)

    assert apply_substitutions("대체 휴무") == "대체 휴무"
    assert apply_substitutions("oo") == "oo"  # 노이즈지만 여기서는 손대지 않는다
    assert correct_item("oo") is None  # 수집 경로에서는 여전히 버린다


# ── 2026-08-31 사용자 확인분 ─────────────────────────────────────────────


def test_reported_misreadings_are_fixed():
    """실제로 잘못 나온 네 가지가 고쳐진다."""
    assert correct_item("누륭지닭곰탕") == "누룽지닭곰탕"
    assert correct_item("돈육나초샐러드") == "돈육나쵸샐러드"
    assert correct_item("롯두부무침") == "톳두부무침"
    assert correct_item("가마보끄조림") == "가마보꼬조림"


def test_narrow_rules_do_not_touch_other_menus():
    """앞 글자를 함께 고정한 규칙이 엉뚱한 메뉴를 건드리지 않는다."""
    # `나초`만 잡았다면 아래가 `나쵸`로 바뀌었을 것이다.
    assert correct_item("나초칩") == "나초칩"
    # `롯`만 잡았다면 회사 이름이 깨졌을 것이다.
    assert correct_item("롯데햄구이") == "롯데햄구이"
