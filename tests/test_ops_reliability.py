from contextlib import closing
from datetime import date
import sqlite3

import pytest
from menu_bot.db import MenuDB
from menu_bot.models import MenuEntry
from menu_bot.ops import (
    backup_database,
    btrfs_metadata,
    prune_image_cache,
    probe_issue,
    update_monitor_state,
    storage_level,
    verify_backup,
)


def test_online_backup_includes_committed_wal_data(tmp_path):
    source = tmp_path / "live.db"
    target = tmp_path / "copy.db"
    with closing(MenuDB(source)) as db:
        db.replace_entries("fixture", [MenuEntry(date(2026, 11, 24), "branch", "meal", "corner", "item")])
        backup_database(source, target)
        assert verify_backup(target) == 1


def test_backup_must_support_actual_menu_query(tmp_path):
    bad_copy = tmp_path / "bad.db"
    with closing(sqlite3.connect(bad_copy)) as conn:
        conn.execute("CREATE TABLE menu_entries (service_date TEXT)")
    with pytest.raises(sqlite3.OperationalError):
        verify_backup(bad_copy)


def test_retention_limits_owned_cache_files_and_preserves_unrelated_files(tmp_path):
    image = tmp_path / ("a" * 24 + ".png")
    sidecar = tmp_path / (image.name + ".ocr.json")
    unrelated = tmp_path / ("x" * 24 + ".txt")
    temporary = tmp_path / ".menubot-active.tmp"
    for path in (image, sidecar, unrelated, temporary):
        path.write_bytes(b"data")
    assert prune_image_cache(tmp_path, max_age_days=120, max_bytes=3) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([unrelated.name, temporary.name])


def test_storage_level_accounts_for_disk_inodes_and_metadata():
    gib = 1024**3
    assert storage_level(100 * gib, 20 * gib) == "ok"
    assert storage_level(100 * gib, 12 * gib) == "warning"
    assert storage_level(100 * gib, 4 * gib) == "critical"
    assert storage_level(100 * gib, 20 * gib, inodes=(100, 3)) == "critical"
    assert storage_level(100 * gib, 20 * gib, metadata=(100, 96, 20)) == "critical"
    assert storage_level(100 * gib, 20 * gib, metadata=(100, 96, 20 * gib)) == "ok"


def test_btrfs_metadata_reads_unallocated_bytes_and_profile_usage():
    output = """Overall:
    Device unallocated:       12345
Metadata,DUP: Size:2147483648, Used:1073741824 (50.00%)
"""
    assert btrfs_metadata(output) == (2147483648, 1073741824, 12345)
    assert btrfs_metadata("not btrfs") is None


def test_probe_checks_menu_result_and_disk_in_body():
    healthy = {"ok": True, "status": "complete", "storage": {"level": "ok", "free_gib": 80.0}}
    assert probe_issue(healthy) == ""
    assert probe_issue({**healthy, "ok": False}) == "menu_unavailable"
    assert probe_issue({**healthy, "storage": {"level": "critical"}}) == "storage_critical"
    assert probe_issue({**healthy, "status": "partial"}) == "week_partial"
    assert probe_issue({"ok": True}) == "invalid_response"


def test_monitor_emits_one_outage_and_one_recovery_after_two_failures():
    state, event = update_monitor_state({}, "menu_unavailable")
    assert event == ""
    state, event = update_monitor_state(state, "menu_unavailable")
    assert event == "menu_unavailable"
    state, event = update_monitor_state(state, "menu_unavailable")
    assert event == ""
    state, event = update_monitor_state(state, "")
    assert event == "recovered"
    assert update_monitor_state(state, "")[1] == ""
