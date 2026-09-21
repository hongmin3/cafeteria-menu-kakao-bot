"""운영·보안·이식성 계약 회귀 검사.

Validates: NFR-SEC-001, NFR-OPS-001, NFR-PORT-001

세 요구사항의 '측정' 중 기계가 답할 수 있는 부분만 여기서 고정한다. 나머지(상시 유닛 강제
종료 후 자동 복구, 두 OCR provider의 실제 이미지 비교)는 외부 환경이 필요하므로 SPEC의
수동 절차로 남는다 — 이 파일이 그 둘을 대신한다고 읽으면 안 된다.

자격 증명도 network도 쓰지 않는다.
"""

import configparser
import pathlib
import re
import subprocess

import pytest

PROJECT = pathlib.Path(__file__).resolve().parents[1]
SYSTEMD = PROJECT / "scripts" / "systemd"


def tracked():
    out = subprocess.run(["git", "-C", str(PROJECT), "-c", "core.quotepath=false",
                          "ls-files"], capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


# ── NFR-SEC-001 ────────────────────────────────────────────────────────────
def test_env_and_data_are_not_tracked():
    """비밀값·원본 이미지·DB·어휘집이 공개 저장소에 들어가면 안 된다."""
    forbidden = re.compile(r"(^|/)\.env$|(^|/)(data|assets)/|\.sqlite3?$|\.db$"
                           r"|\.ocr\.json$|(^|/)vocabulary\.json$")
    offenders = [p for p in tracked() if forbidden.search(p)]
    assert offenders == [], f"추적하면 안 되는 파일: {offenders}"


def test_git_ignores_the_secret_and_data_paths():
    """선언(.gitignore)과 git의 실제 동작을 따로 확인한다."""
    probes = [".env", "data/menu.sqlite3", "assets/menu.png"]
    result = subprocess.run(["git", "-C", str(PROJECT), "-c", "core.quotepath=false",
                             "check-ignore", "--no-index", *probes],
                            capture_output=True, text=True)
    ignored = {line for line in result.stdout.splitlines() if line}
    missing = [p for p in probes if p not in ignored]
    assert missing == [], f"git이 무시하지 않는 경로: {missing}"


def test_webhook_rejects_a_wrong_token_with_404():
    """토큰이 설정되면 일치하지 않는 요청은 404다.

    403이 아니라 404인 것이 사양이다 — 경로의 존재 자체를 알려주지 않는다.
    """
    # starlette은 httpx가 없으면 testclient를 **import 하는 순간** RuntimeError를 던진다
    # (ModuleNotFoundError가 아니라서 importorskip이 잡지 못한다).
    try:
        from fastapi.testclient import TestClient
    except (ImportError, RuntimeError) as exc:
        pytest.skip(f"TestClient를 쓸 수 없어 실제 요청으로는 확인하지 못했다: {exc}")
    from menu_bot import web
    from menu_bot.config import get_settings

    settings = get_settings()
    if not getattr(settings, "webhook_token", ""):
        pytest.skip("webhook_token이 설정돼 있지 않아 이 실행에서는 토큰 분기를 관찰하지 못했다")
    client = TestClient(web.app)
    wrong = client.post("/kakao/skill/definitely-not-the-token", json={})
    assert wrong.status_code == 404, wrong.status_code


def test_webhook_handler_uses_404_for_token_mismatch_in_source():
    """TestClient나 설정이 없는 환경에서도 이 계약이 검사 없이 지나가지 않게 소스로 고정한다.

    위 검사는 설정이 없으면 skip된다. skip만 남으면 '검사했다'와 '검사하지 못했다'가
    같은 초록으로 보이므로, 소스 수준의 단언을 함께 둔다.
    """
    source = (PROJECT / "src" / "menu_bot" / "web.py").read_text(encoding="utf-8")
    handler = re.search(r"async def kakao_skill\(.*?\n(?:.*\n)*?.*?raise HTTPException\((.*?)\)",
                        source)
    assert handler, "kakao_skill의 토큰 분기를 찾지 못했다"
    assert "404" in handler.group(1), handler.group(1)


# ── NFR-OPS-001 ────────────────────────────────────────────────────────────
def unit(name):
    parser = configparser.ConfigParser(strict=False)
    parser.optionxform = str
    parser.read(SYSTEMD / name, encoding="utf-8")
    return parser


@pytest.mark.parametrize("name", ["menubot-web.service", "menubot-tunnel.service"])
def test_always_on_units_restart_themselves(name):
    """웹 서버와 터널은 각각 독립적으로 자동 재시작한다."""
    assert (SYSTEMD / name).exists(), f"{name}이 없다"
    assert unit(name)["Service"].get("Restart") == "always", name


def test_web_and_tunnel_are_separate_units():
    """둘을 한 유닛으로 묶으면 한쪽이 재시작할 때 다른 쪽이 되살아날 근거를 잃는다."""
    web, tunnel = SYSTEMD / "menubot-web.service", SYSTEMD / "menubot-tunnel.service"
    assert web.exists() and tunnel.exists()
    assert web.read_text(encoding="utf-8") != tunnel.read_text(encoding="utf-8")


def test_collection_units_cap_memory():
    """수집·OCR은 같은 장비의 다른 서비스를 밀어내지 않아야 한다."""
    capped = [p.name for p in SYSTEMD.glob("*.service")
              if "MemoryMax=" in p.read_text(encoding="utf-8")]
    assert capped, "MemoryMax를 건 유닛이 하나도 없다"
    for name in ("menubot-collect.service", "menubot-nextweek.service"):
        assert name in capped, f"{name}에 메모리 상한이 없다"


def test_every_timer_has_its_service():
    """타이머만 있고 서비스가 없으면 그 일정은 조용히 아무 일도 하지 않는다."""
    orphans = [t.name for t in SYSTEMD.glob("*.timer")
               if not (SYSTEMD / (t.stem.split(".")[0] + ".service")).exists()
               and not (SYSTEMD / (re.sub(r"-(friday|weekend)$", "", t.stem) + ".service")).exists()]
    assert orphans == [], f"짝 없는 타이머: {orphans}"


# ── NFR-PORT-001 ───────────────────────────────────────────────────────────
def test_timezone_comes_from_configuration_not_the_system():
    """운영 서버의 시스템 시간대가 달라도 조회 결과가 달라지면 안 된다."""
    from menu_bot.config import get_settings
    assert get_settings().timezone, "TIMEZONE 설정값이 비어 있다"


def test_query_module_never_uses_a_naive_local_now():
    """`datetime.now()`를 시간대 없이 부르면 시스템 시간대가 결과에 새어 든다."""
    for name in ("query.py", "parser.py"):
        source = (PROJECT / "src" / "menu_bot" / name).read_text(encoding="utf-8")
        bare = re.findall(r"datetime\.now\(\s*\)", source)
        assert bare == [], f"{name}에 시간대 없는 datetime.now()가 {len(bare)}건 있다"
