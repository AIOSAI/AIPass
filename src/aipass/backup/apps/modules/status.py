# =================== AIPass ====================
# Name: status.py
# Description: Status module — show backup status for a project, as a page or one JSON object
# Version: 1.2.1
# Created: 2026-04-23
# Modified: 2026-10-16
# =============================================

"""Status Module — display backup info and recent history for a project.

``status <root> --json [--sizes]`` answers the backup door's contract
(src/aipass/devpulse/docs.local/backup_door_contract.md, "@backup: status
--json"): one JSON object on stdout and nothing else there.
"""

import json
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.cli.apps.modules import console, error

from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.drive.tracker import load_tracker
from aipass.backup.apps.handlers.json.json_handler import InvalidDocument
from aipass.backup.apps.handlers.path.builder import (
    backup_root,
    build_config_path,
    build_snapshot_path,
    build_versioned_store,
)
from aipass.backup.apps.handlers.path.caller import resolve_caller_path
from aipass.backup.apps.handlers.project.config import load_project_config
from aipass.backup.apps.handlers.state.changelog import load_changelog

MODULE_NAME = "status"
PRIMARY_COMMAND = "status"

#: The lanes the contract reports, in its order. Each one's last run is read
#: from the project's changelog by its ``mode``; drive_sync writes its entry
#: after a run whose uploads all succeeded.
LANES = ("snapshot", "versioned", "drive_sync")
FLAGS = ("--json", "--sizes")


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: Phase 3 — implemented")
    console.print("  Handlers: path, project/config, state/changelog, drive/tracker")


def print_help():
    """Display help for this module."""
    print_introspection()
    console.print()
    console.print("Usage: status <project_root|@name> [--json [--sizes]]")
    console.print("  --json   one JSON object on stdout, nothing else (the backup door)")
    console.print("  --sizes  with --json: add both store sizes (walks the store)")


def _raise_walk_error(err: OSError) -> None:
    """Raise on a store directory the walk cannot list: a short count would be a wrong answer."""
    raise err


def _tree_bytes(path: Path) -> int:
    """Total size in bytes of every file under ``path``; 0 when it does not exist."""
    if not path.exists():
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path, onerror=_raise_walk_error, followlinks=False):
        for filename in filenames:
            total += os.lstat(os.path.join(dirpath, filename)).st_size
    return total


def _last_runs(changelog: list[dict]) -> dict:
    """Each lane's last changelog entry as ``{"last", "files"}``, null when that lane never ran."""
    lanes = {lane: {"last": None, "files": None} for lane in LANES}
    for entry in changelog:
        mode = entry.get("mode")
        if mode in lanes:
            lanes[mode] = {"last": entry.get("timestamp"), "files": entry.get("files_copied")}
    return lanes


def build_status(project_root: str, sizes: bool = False) -> dict:
    """Build the contract's status object for one project root.

    Args:
        project_root: Absolute path to an existing project directory.
        sizes: Walk both stores and add the ``store`` key.

    Returns:
        The status object, keys in the contract's order.

    Raises:
        InvalidDocument: The config, changelog or Drive tracker is unreadable.
        OSError: A store directory could not be listed while measuring sizes.
    """
    config = load_project_config(project_root)
    changelog = load_changelog(project_root)
    tracker = load_tracker(project_root)
    status: dict = {
        "project": config.get("project_name") or Path(project_root).name,
        "root": project_root,
        "registered": build_config_path(project_root).exists(),
        "mode": config.get("backup_mode", "snapshot"),
        "drive_sync": config.get("drive_sync", False),
        "runs": len(changelog),
        "lanes": _last_runs(changelog),
    }
    if sizes:
        status["store"] = {
            "snapshots_bytes": _tree_bytes(build_snapshot_path(project_root)),
            "versioned_bytes": _tree_bytes(build_versioned_store(project_root)),
        }
    # load_tracker leaves the tracker's lane stamp out: every key it answers is a file.
    status["drive"] = {"tracked_files": len(tracker)}
    return status


def print_status_json(project_root: str, sizes: bool) -> None:
    """Print the status object as one JSON line on stdout, or one error line on stderr."""
    if not Path(project_root).is_dir():
        error(f"Project path is not a directory: {project_root}")
        return
    try:
        status = build_status(project_root, sizes=sizes)
    except (InvalidDocument, OSError) as exc:
        logger.error(f"[backup] status --json failed for {project_root}: {exc}")
        error(f"Status unreadable: {exc}")
        return
    console.print(json.dumps(status), markup=False, highlight=False, soft_wrap=True)
    trail.log_operation("status_json", {"project_root": project_root, "sizes": sizes})


def handle_command(command: str, args: list) -> bool:
    """Handle the status command. Returns True if handled."""
    if command != PRIMARY_COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    # Screen the WHOLE sequence, not just args[0]. This module has a
    # standalone __main__ entry that never reaches the router's help
    # normalisation, so a trailing flag used to fall through and run the
    # verb for real. Bare "help" stays first-position-only: later
    # positions are user values (filenames), not flags.
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True

    positional = [arg for arg in args if not arg.startswith("--")]
    unknown = [arg for arg in args if arg.startswith("--") and arg not in FLAGS]
    if unknown or len(positional) != 1:
        error(
            f"status takes one project and the flags {', '.join(FLAGS)}: got {' '.join(args)}",
            suggestion="status <project_root|@name> [--json [--sizes]]",
        )
        return True
    if "--sizes" in args and "--json" not in args:
        error("--sizes is a --json option", suggestion="status <project_root|@name> --json --sizes")
        return True

    project_root = str(resolve_caller_path(positional[0]))
    if "--json" in args:
        print_status_json(project_root, sizes="--sizes" in args)
        return True

    bs_dir = backup_root(project_root)

    if not bs_dir.exists():
        logger.warning(f"No backups found for {project_root}")
        console.print(f"Run: backup register {project_root}")
        return True

    config = load_project_config(project_root)
    changelog = load_changelog(project_root)

    console.print(f"[bold]Backup Status:[/bold] {config.get('project_name', Path(project_root).name)}")
    console.print(f"  Path:         {project_root}")
    console.print(f"  Mode:         {config.get('backup_mode', 'snapshot')}")
    console.print(f"  Max versions: {config.get('max_versions', 10)}")
    console.print(f"  Drive sync:   {config.get('drive_sync', False)}")
    console.print(f"  Total runs:   {len(changelog)}")

    if changelog:
        console.print("\n  [bold]Recent backups:[/bold]")
        for entry in changelog[-3:]:
            ts = entry.get("timestamp", "?")
            mode = entry.get("mode", "?")
            files = entry.get("files_copied", 0)
            console.print(f"    {ts} | {mode} | {files} files")

    trail.log_operation("status_displayed", {"project_root": project_root})
    logger.info(f"[backup] Status shown for {project_root}")
    return True


# =============================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
