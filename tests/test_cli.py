from pathlib import Path

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
