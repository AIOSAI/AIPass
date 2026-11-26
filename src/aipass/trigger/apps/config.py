# =================== AIPass ====================
# Name: config.py
# Description: Trigger package paths and atomic JSON writes
# Version: 1.12.0
# Created: 2026-03-09
# Modified: 2026-11-26
# =============================================

"""
Trigger package path configuration.
"""

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from aipass.prax import branch_state_root, logger

TRIGGER_ROOT = Path(__file__).resolve().parents[1]

AIPASS_PKG_ROOT = TRIGGER_ROOT.parent

# Prax's state root: the branch folder on a checkout, the home folder on an install, never inside a wheel.
TRIGGER_STATE_ROOT = branch_state_root("trigger")

# json_handler creates any absent `<module>_<config|data|log>.json` here; a misshaped one raises, never overwritten.
TRIGGER_JSON_DIR = TRIGGER_STATE_ROOT / "trigger_json"

TRIGGER_LOGS_DIR = TRIGGER_STATE_ROOT / "logs"

ARCHIVE_DIR_NAME = ".archive"


def atomic_write_json(path: Path, data, indent: int = 2, ensure_ascii: bool = True, encoding: str = "utf-8") -> None:
    """Write JSON data to a file atomically using write-to-tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
        os.replace(tmp_path, str(path))
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


@contextmanager
def json_file_lock(path: Path):
    """Acquire exclusive lock for a JSON file's read-modify-write cycle."""
    # Pair with atomic_write_json: atomic stops a torn file, this stops a lost update.
    lock_path = path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def _archive_legacy_file(path: Path) -> bool:
    """Move a retired state file into a sibling .archive/ directory."""
    archive_dir = path.parent / ARCHIVE_DIR_NAME
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / path.name
    try:
        if target.exists():
            stamp = int(path.stat().st_mtime)
            target = archive_dir / f"{path.stem}.{stamp}{path.suffix}"
        os.replace(str(path), str(target))
        return True
    except OSError as exc:
        logger.warning(f"archive of {path.name} failed: {exc}")
        return False


def migrate_json_file(legacy_path: Path, new_path: Path) -> bool:
    """Move live JSON state from a legacy path to its new home, losslessly; an unreadable legacy file raises."""
    # New present is a no-op: the legacy name is json_handler's again. Unreadable is left in place for a human.
    # Locks the LEGACY path: callers already hold the new file's lock, and a second flock would deadlock.
    if new_path.exists() or not legacy_path.exists():
        return False
    with json_file_lock(legacy_path):
        if new_path.exists() or not legacy_path.exists():  # another process won the race
            return False
        try:
            data = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            raise RuntimeError(f"migration refused: {legacy_path.name} unreadable: {exc}") from exc
        atomic_write_json(new_path, data)
        return _archive_legacy_file(legacy_path)


def read_text_file(path: Path, encoding: str = "utf-8") -> str:
    """Read a text file safely with encoding specification."""
    with open(path, "r", encoding=encoding) as f:
        return f.read()


def write_text_file(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write text content to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding=encoding) as f:
        f.write(content)


def print_introspection():
    """Display module introspection info."""
    from aipass.cli import console

    console.print()
    console.print("[bold cyan]config Module[/bold cyan]")
    console.print("[dim]Path constants — TRIGGER_ROOT and AIPASS_PKG_ROOT used by all trigger modules[/dim]")
    console.print()
    console.print("[dim]Run config.py --help for usage.[/dim]")


def print_help():
    """Display usage for the config module."""
    from aipass.cli import console

    console.print()
    console.print("[bold cyan]config — trigger paths and atomic JSON writes[/bold cyan]")
    console.print()
    console.print("[dim]No drone command; trigger modules import it.[/dim]")
    console.print()
    console.print("[bold]Usage (Python):[/bold]")
    console.print("  from aipass.trigger.apps.config import TRIGGER_ROOT, atomic_write_json")
    console.print()
    console.print("[bold]Examples:[/bold]")
    console.print("  atomic_write_json(TRIGGER_JSON_DIR / 'state.json', data)")
    console.print("  with json_file_lock(path): ...")
    console.print("  migrate_json_file(legacy_path, new_path)")
    console.print()


if __name__ == "__main__":
    import sys

    from aipass.cli import console, header_version

    args = sys.argv[1:]
    if len(args) == 0:
        print_introspection()
    elif "--help" in args or "-h" in args:
        print_help()
    elif args[0] in ("--version", "-V"):
        console.print(f"config v{header_version(__file__)}", highlight=False)
    else:
        print_introspection()
