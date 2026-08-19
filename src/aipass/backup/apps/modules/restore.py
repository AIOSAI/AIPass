# =================== AIPass ====================
# Name: restore.py
# Description: Restore module — version discovery and file restoration
# Version: 1.0.0
# Created: 2026-06-12
# Modified: 2026-06-12
# =============================================

"""Restore Module — list versions and restore files from versioned store."""

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
from aipass.cli.apps.modules import console

from aipass.backup.apps.handlers.diff.restore import list_versions, restore_file
from aipass.backup.apps.handlers.json import json_handler
from aipass.backup.apps.handlers.path.builder import build_versioned_store

MODULE_NAME = "restore"
PRIMARY_COMMAND = "restore"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: Phase 3 — version discovery + restore")
    console.print("  Handlers: diff/restore, path/builder")


def print_help():
    """Display help for this module."""
    print_introspection()
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print("  restore <project> list <file>       — list versions of a file")
    console.print("  restore <project> file <file> <out> — restore current version to output path")


def _find_file_folder(project_root: str, filename: str) -> Path | None:
    """Find a file-folder in the versioned store by filename."""
    store = build_versioned_store(project_root)
    if not store.exists():
        return None

    for candidate in store.rglob(filename):
        if candidate.is_dir() and (candidate / filename).is_file():
            return candidate

    return None


def run_list_versions(project_root: str, filename: str) -> bool:
    """List all versions of a file in the versioned store.

    Args:
        project_root: Project root path.
        filename: Name of the file to look up.

    Returns:
        True if versions were found and listed.
    """
    file_folder = _find_file_folder(project_root, filename)
    if not file_folder:
        console.print(f"No versioned file found for: {filename}")
        return False

    versions = list_versions(file_folder)
    if not versions:
        console.print(f"No versions found for: {filename}")
        return False

    console.print(f"[bold]Versions of {filename}:[/bold]")
    for v in versions:
        marker = "*" if v["type"] == "current" else " "
        console.print(f"  {marker} [{v['type']}] {v['timestamp']}  {v['path'].name}")

    json_handler.log_operation(
        "restore_list",
        {"file": filename, "versions": len(versions)},
    )
    return True


def run_restore_file(project_root: str, filename: str, output_path: str) -> bool:
    """Restore the current version of a file to an output path.

    Args:
        project_root: Project root path.
        filename: Name of the file to restore.
        output_path: Where to write the restored file.

    Returns:
        True if restore succeeded.
    """
    file_folder = _find_file_folder(project_root, filename)
    if not file_folder:
        console.print(f"No versioned file found for: {filename}")
        return False

    out = Path(output_path)
    success = restore_file(file_folder, out)
    if success:
        console.print(f"Restored {filename} to {out}")
    else:
        logger.warning(f"[restore] Failed to restore {filename}")
        console.print(f"Restore failed for {filename}")

    json_handler.log_operation(
        "restore_complete",
        {"file": filename, "output": output_path, "success": success},
    )
    return success


def handle_command(command: str, args: list) -> bool:
    """Handle the restore command. Returns True if handled."""
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

    if len(args) < 3:
        print_help()
        return True

    project_root = args[0]
    subcommand = args[1]

    if subcommand == "list" and len(args) >= 3:
        run_list_versions(project_root, args[2])
        return True

    if subcommand == "file" and len(args) >= 4:
        run_restore_file(project_root, args[2], args[3])
        return True

    print_help()
    return True


# =============================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
