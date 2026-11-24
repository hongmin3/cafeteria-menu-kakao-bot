from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from menu_bot import cli
from menu_bot.cli import _learning_db_path


def test_learning_db_path_never_matches_operational_path():
    operational = Path("data/menus.db")
    learning = _learning_db_path(operational)
    assert learning != operational
    assert learning == Path("data/menus.learning.db")


def test_learning_db_path_respects_custom_operational_path():
    operational = Path("C:/somewhere/custom_menus.db")
    learning = _learning_db_path(operational)
    assert learning == Path("C:/somewhere/custom_menus.learning.db")
    assert learning != operational


def test_operational_ingest_without_any_items_exits_nonzero(tmp_path, monkeypatch, capsys):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "menus.db"))
    monkeypatch.setattr(sys, "argv", ["menu-bot", "ingest", str(manifest)])
    with pytest.raises(SystemExit) as outcome:
        cli.main()
    assert outcome.value.code == 1
    assert '"entries": 0' in capsys.readouterr().out


def test_cli_ask_does_not_initialize_missing_database(tmp_path, monkeypatch, capsys):
    database = tmp_path / "menus.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    monkeypatch.setattr(sys, "argv", ["menu-bot", "ask", "오늘 점심"])
    with pytest.raises(SystemExit) as outcome:
        cli.main()
    assert outcome.value.code == 1
    assert not database.exists()
    assert "식단" in capsys.readouterr().err


def test_cli_ensure_exposes_refresh_without_changing_default(monkeypatch):
    refreshed = []

    def ensure(_settings, *, now, refresh):
        refreshed.append(refresh)
        return SimpleNamespace(message="완료", error=None)

    monkeypatch.setattr(cli, "ensure_week_menu", ensure)
    for args in ([], ["--refresh"]):
        monkeypatch.setattr(sys, "argv", ["menu-bot", "ensure-menu", *args])
        cli.main()
    assert refreshed == [False, True]
