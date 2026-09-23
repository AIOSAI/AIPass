# =================== AIPass ====================
# Name: restore.py
# Description: Restore module — version discovery and file restoration
# Version: 1.0.0
# Created: 2026-06-12
# Modified: 2026-09-23
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
from aipass.cli.apps.modules import console, error

from aipass.backup.apps.handlers.diff.restore import list_versions, restore_file
from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.path.builder import build_versioned_file_path, build_versioned_store

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
    """Find a file-folder in the versioned store by bare filename or relative path."""
    store = build_versioned_store(project_root)
    if not store.exists():
        return None

    # Ask the builder where this name WOULD be written instead of re-deriving
    # the layout here. A name over 50 characters is stored in a folder called
    # name[:30]_md5[:8], so globbing the full name never matched it and the
    # file could be backed up but never restored.
    direct = build_versioned_file_path(project_root, filename)
    if direct.is_file():
        return direct.parent

    # Bare basename of a nested file: the folder name the builder picks is the
    # same wherever the parent sits, so search for THAT, not the raw argument.
    name = Path(filename).name
    folder_name = build_versioned_file_path(project_root, name).parent.name
    for candidate in store.rglob(folder_name):
        if candidate.is_dir() and (candidate / name).is_file():
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
        error(f"No versioned file found for: {filename}")
        return False

    versions = list_versions(file_folder)
    if not versions:
        # Same channel as the lookup failure above, for the same reason: this
        # is a listing that did not happen. On console.print it landed on
        # stdout beside the "Versions of X:" heading it is denying, and left
        # the process unmarked, so `restore <p> list <f>` exited 0 having
        # listed nothing. The guard above does NOT cover this case -- it fires
        # when the file is absent, and here the file is present but the store
        # holds no version the handler can read (a pruned hashed folder whose
        # current version is no longer the only non-baseline file in it).
        error(f"No versions found for: {filename}")
        return False

    console.print(f"[bold]Versions of {filename}:[/bold]")
    for v in versions:
        marker = "*" if v["type"] == "current" else " "
        # markup=False on THIS line only: the row is pure data (type label,
        # timestamp, stored filename) and carries no tags of its own, so the
        # parser has nothing to do but eat "[diff]" as an unknown style. The
        # heading above is a separate print and keeps its [bold] intact.
        console.print(f"  {marker} [{v['type']}] {v['timestamp']}  {v['path'].name}", markup=False)

    trail.log_operation(
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
        error(f"No versioned file found for: {filename}")
        return False

    out = Path(output_path)
    success = restore_file(file_folder, out)
    if success:
        console.print(f"Restored {filename} to {out}")
    else:
        logger.warning(f"[restore] Failed to restore {filename}")
        error(f"Restore failed for {filename}")

    trail.log_operation(
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

    # A malformed invocation is not a help request. Answering it with the
    # help page told the user nothing about what was wrong AND reported
    # success, so a script could not tell `restore <project> list` (no file
    # named) from `restore --help`. The command IS ours, so the answer is
    # True: error() has marked the process failed and resolve_exit turns
    # that into exit 2. Returning False here made the router append
    # "Unknown command: restore", a false line, and exit 1 (devpulse ruling,
    # 2026-09-22, matching drive_check's refusal).
    if len(args) < 3:
        error(
            "restore needs a project, a verb and a filename",
            suggestion="restore <project> list <file>  |  restore <project> file <file> <out>",
        )
        return True

    project_root = args[0]
    subcommand = args[1]

    if subcommand == "list" and len(args) >= 3:
        run_list_versions(project_root, args[2])
        return True

    if subcommand == "file" and len(args) >= 4:
        run_restore_file(project_root, args[2], args[3])
        return True

    # The 2026-09-22 refusal only reached `list` with no filename; everything
    # else still fell through to print_help() and returned a success nobody
    # could question. `restore <p> file <f>` with no output path and a
    # mistyped verb both got the usage page on STDOUT and exit 0, so a script
    # could not tell a restore that ran from one that never started. Same
    # shape as the cure above and as drive_check's refusal: error() names what
    # was wrong on stderr and marks the process failed, True keeps the command
    # ours so resolve_exit reports 2 instead of the router adding a false
    # "Unknown command: restore" on top of a true line.
    if subcommand == "file":
        error(
            "restore file needs an output path",
            suggestion="restore <project> file <file> <out>",
        )
        return True

    error(
        f"restore has no verb named: {subcommand}",
        suggestion="restore <project> list <file>  |  restore <project> file <file> <out>",
    )
    return True


# =============================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
