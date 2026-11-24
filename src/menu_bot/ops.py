"""Storage checks, bounded cache retention, and verified SQLite backups."""

from argparse import ArgumentParser
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from .atomic import write_bytes
from .db import MenuDB


GIB = 1024**3
CACHE_FILE = re.compile(r"([a-f0-9]{24}\.[A-Za-z0-9]{1,12})(?:\.(?:ocr|advice)\.json)?")


def btrfs_metadata(output: str) -> tuple[int, int, int] | None:
    unallocated = re.search(r"Device unallocated:\s*(\d+)", output)
    profiles = re.findall(r"^Metadata,[^:\n]+:\s+Size:\s*(\d+),\s*Used:\s*(\d+)", output, re.M)
    if unallocated and profiles:
        return sum(int(size) for size, _ in profiles), sum(int(used) for _, used in profiles), int(unallocated[1])
    return None


def storage_level(total: int, free: int, *, inodes=None, metadata=None) -> str:
    inode_margin = inodes[1] / inodes[0] if inodes and inodes[0] else 1
    free_ratio = free / total if total else 0
    metadata_margin = 1
    if metadata:
        allocated, used, unallocated = metadata
        if unallocated < 2 * GIB and allocated:
            metadata_margin = (allocated - used) / allocated
    if free < 2 * GIB or min(free_ratio, inode_margin, metadata_margin) < 0.05:
        return "critical"
    if free < 10 * GIB or min(free_ratio, inode_margin, metadata_margin) < 0.15:
        return "warning"
    return "ok"


def storage_signal(path: Path) -> dict:
    directory = path.absolute().parent
    while not directory.exists() and directory != directory.parent:
        directory = directory.parent
    try:
        disk = shutil.disk_usage(directory)
        stat = os.statvfs(directory) if hasattr(os, "statvfs") else None
        inodes = (stat.f_files, stat.f_favail) if stat else None
    except OSError:
        return {"level": "unknown", "free_gib": None, "metadata_checked": False}
    metadata = None
    if shutil.which("btrfs"):
        try:
            usage = subprocess.run(
                ["btrfs", "filesystem", "usage", "-b", str(directory)],
                capture_output=True, text=True, timeout=1, check=True,
            )
            metadata = btrfs_metadata(usage.stdout)
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "level": storage_level(disk.total, disk.free, inodes=inodes, metadata=metadata),
        "free_gib": round(disk.free / GIB, 1),
        "metadata_checked": metadata is not None,
    }


def prune_image_cache(directory: Path, *, max_age_days: int = 120, max_bytes: int = GIB) -> int:
    if not directory.is_dir():
        return 0
    groups = {}
    for path in directory.iterdir():
        match = CACHE_FILE.fullmatch(path.name)
        if match and path.is_file() and not path.is_symlink():
            groups.setdefault(match[1], []).append((path, path.stat()))
    oldest_first = sorted(groups.values(), key=lambda group: max(stat.st_mtime for _, stat in group))
    total = sum(stat.st_size for group in oldest_first for _, stat in group)
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for group in oldest_first:
        if total <= max_bytes and max(stat.st_mtime for _, stat in group) >= cutoff:
            break
        for path, stat in group:
            path.unlink(missing_ok=True)
            removed += 1
            total -= stat.st_size
    return removed


def verify_backup(path: Path) -> int:
    with closing(MenuDB(path, read_only=True)) as db:
        if db.conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("database failed integrity check")
        latest = db.conn.execute("SELECT MAX(service_date) FROM menu_entries").fetchone()[0]
        sample_day = date.fromisoformat(latest) if latest else date.today()
        db.query(sample_day)
        return db.count_entries()


def backup_database(source: Path, target: Path) -> int:
    """Publish a complete snapshot, while keeping a previous backup on failure."""
    if source.resolve() == target.resolve():
        raise ValueError("backup path must differ from source")
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=".menubot-backup-", suffix=".db")
    os.close(fd)
    staged = Path(name)
    deadline = time.monotonic() + 20

    def check_time(*_):
        if time.monotonic() >= deadline:
            raise TimeoutError("SQLite backup did not finish")

    try:
        with (
            closing(sqlite3.connect(source.absolute().as_uri() + "?mode=ro", uri=True, timeout=2)) as db,
            closing(sqlite3.connect(staged)) as copy,
        ):
            db.backup(copy, pages=64, progress=check_time, sleep=0.05)
            copy.execute("PRAGMA journal_mode=DELETE")
        entries = verify_backup(staged)
        staged.replace(target)
        return entries
    finally:
        staged.unlink(missing_ok=True)


def probe_issue(result: dict) -> str:
    if not isinstance(result, dict) or not isinstance(result.get("storage"), dict):
        return "invalid_response"
    storage = result["storage"].get("level")
    if storage in {"critical", "warning", "unknown"}:
        return f"storage_{storage}"
    if storage != "ok":
        return "invalid_response"
    if result.get("status") == "db_unavailable":
        return "db_unavailable"
    if result.get("ok") is not True:
        return "menu_unavailable"
    status = result.get("status")
    if status == "complete":
        return ""
    if status in {"empty", "partial"}:
        return f"week_{status}"
    return "invalid_response"


def update_monitor_state(state: dict, issue: str) -> tuple[dict, str]:
    active = state.get("active", "")
    count = (state.get("count", 0) + 1) if state.get("candidate") == issue else 1
    event = ""
    if not issue and active:
        active = ""
        event = "recovered"
    elif issue and issue != active and (count >= 2 or issue in {"storage_critical", "storage_drop"}):
        active = issue
        event = issue
    return {**state, "active": active, "candidate": issue, "count": min(count, 2)}, event


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _probe(domain: str, token: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9.-]+", domain) or not token:
        raise ValueError("invalid probe configuration")
    req = Request(
        f"https://{domain}/kakao/probe",
        headers={"Authorization": f"Bearer {token}", "ngrok-skip-browser-warning": "1"},
    )
    try:
        with build_opener(_NoRedirect).open(req, timeout=8) as response:
            return json.loads(response.read(4096))
    except HTTPError as exc:
        with exc:
            if exc.code == 503 and exc.headers.get_content_type() == "application/json":
                result = json.loads(exc.read(4096))
                if isinstance(result, dict) and result.get("status") == "db_unavailable":
                    return result
        raise


def _pull_backup(host: str, directory: Path, day: str) -> int:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@-]+", host):
        raise ValueError("invalid backup host")
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / f"menubot-{day}.db"
    fd, name = tempfile.mkstemp(prefix=".menubot-incoming-", suffix=".db", dir=directory)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", host,
                 "cd cafeteria-menu-kakao-bot && .venv/bin/python -B -m menu_bot.ops export-backup"],
                stdout=output, stderr=subprocess.DEVNULL, timeout=45, check=True,
            )
        entries = verify_backup(staged)
        staged.replace(final)
    finally:
        staged.unlink(missing_ok=True)
    backups = sorted(p for p in directory.glob("menubot-????-??-??.db") if p.is_file() and not p.is_symlink())
    for expired in backups[:-14]:
        expired.unlink()
    return entries


def monitor_once(directory: Path, domain: str, token: str, host: str) -> dict:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    state_path = directory / "state.json"
    try:
        state = json.loads(state_path.read_bytes())
        if not isinstance(state, dict) or type(state.get("count", 0)) is not int:
            state = {}
    except (OSError, ValueError):
        state = {}
    free = None
    try:
        result = _probe(domain, token)
        issue = probe_issue(result)
        if isinstance(result, dict) and isinstance(result.get("storage"), dict):
            free = result["storage"].get("free_gib")
    except (URLError, OSError, ValueError):
        issue = "public_unreachable"
    if not issue and isinstance(free, (int, float)) and isinstance(state.get("free_gib"), (int, float)):
        try:
            elapsed = (now - datetime.fromisoformat(state["checked_at"])).total_seconds()
            if 0 < elapsed <= 3600 and state["free_gib"] - free >= 8:
                issue = "storage_drop"
        except (KeyError, TypeError, ValueError):
            pass
    today = now.date().isoformat()
    if state.get("backup_day") != today and host:
        try:
            state["backup_entries"] = _pull_backup(host, directory / "backups", today)
            state["backup_day"] = today
        except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError):
            issue = issue or "backup_failed"
    state, event = update_monitor_state(state, issue)
    state.update(checked_at=now.isoformat(timespec="seconds"), free_gib=free)
    write_bytes(state_path, (json.dumps(state) + "\n").encode())
    return {"issue": issue, "event": event, "backup_day": state.get("backup_day")}


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("command", choices=("export-backup", "prune-cache", "monitor"))
    parser.add_argument("--monitor-dir", type=Path, default=Path("data/offsite-monitor"))
    parser.add_argument("--domain", default="")
    parser.add_argument("--backup-host", default="")
    args = parser.parse_args()
    if args.command == "prune-cache":
        print(f"pruned cache files: {prune_image_cache(Path('data/images'))}")
        return
    if args.command == "monitor":
        result = monitor_once(
            args.monitor_dir, args.domain, os.getenv("MENUBOT_MONITOR_BEARER", ""), args.backup_host,
        )
        print(json.dumps(result))
        return
    from .config import get_settings

    with tempfile.TemporaryDirectory(prefix="menubot-backup-") as directory:
        path = Path(directory) / "backup.db"
        backup_database(get_settings().database_path, path)
        with path.open("rb") as backup:
            shutil.copyfileobj(backup, sys.stdout.buffer)


if __name__ == "__main__":
    main()
