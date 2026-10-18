# =================== AIPass ====================
# Name: prune.py
# Description: Prune module — lists, and with --apply removes, stored copies the ignore spec now matches
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-17
# =============================================

"""Prune Module — stored copies of paths the ignore spec now matches.

Reference: docs/store_cleanup.md
"""

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
from aipass.backup.apps.handlers.cleanup.prune import apply_prune, find_prunable
from aipass.backup.apps.handlers.path.builder import backup_root
from aipass.backup.apps.handlers.path.caller import resolve_caller_path
from aipass.backup.apps.handlers.report.formatter import _human_bytes

MODULE_NAME = "prune"
PRIMARY_COMMAND = "prune"
USAGE = "prune <project_root|@name> [--apply]"

#: What one candidate is called in each store.
UNITS = {"snapshots": "files", "versioned": "file-folders"}


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: implemented 2026-10-16")
    console.print("  Handlers: cleanup/prune, ignore/patterns, ignore/whitelist")


def print_help():
    """Display help for this module."""
    print_introspection()
    console.print()
    console.print(f"Usage: {USAGE}")
    console.print("  Lists, per top-level directory, the snapshots/ files and versioned/")
    console.print("  file-folders whose project path the ignore spec now matches.")
    console.print("  Without --apply nothing is deleted. --apply deletes them,")
    console.print("  one trail row each.")


def show_listing(project_root: str, found: dict, applying: bool) -> None:
    """Print the per-store, per-top-level-directory counts and the grand total.

    Paths are printed with markup off: a directory named ``[x]`` is a name, not a style.
    """
    console.print(f"Prune: {project_root}{'' if applying else '  (dry run)'}", markup=False)
    for lane, unit in UNITS.items():
        groups = found["groups"][lane]
        lane_bytes = sum(group["bytes"] for group in groups.values())
        console.print(f"  {lane}/  {len(found[lane]):,} {unit}, {_human_bytes(lane_bytes)}")
        for top, group in groups.items():
            line = f"    {top:<32} {group['count']:>10,} {unit:<12} {_human_bytes(group['bytes']):>10}"
            console.print(line, markup=False, highlight=False)
    console.print(f"  Total: {found['count']:,} stored paths, {_human_bytes(found['bytes'])}")


def run_prune(project_root: str, apply: bool = False) -> bool:
    """List the stored copies the ignore spec now matches, and delete them when ``apply``."""
    if not Path(project_root).is_dir():
        error(f"Project path is not a directory: {project_root}")
        return False
    if not backup_root(project_root).is_dir():
        console.print(f"No store at {backup_root(project_root)} -- nothing to prune.", markup=False)
        return True

    try:
        found = find_prunable(project_root)
    except OSError as exc:
        logger.error(f"[backup] prune could not read the store for {project_root}: {exc}")
        error(f"Prune could not read the store: {exc}")
        return False

    show_listing(project_root, found, applying=apply)
    if not apply:
        trail.log_operation("prune_dry_run", {"project_root": project_root, "count": found["count"]})
        console.print(
            f"Dry run -- nothing deleted. {found['count']:,} stored paths ({_human_bytes(found['bytes'])}) "
            "would go with --apply."
        )
        return True

    outcome = apply_prune(project_root, found)
    for line in outcome["errors"]:
        error(f"Not removed: {line}")
    console.print(f"Removed {outcome['removed']:,} stored paths, {_human_bytes(outcome['bytes'])} freed.")
    return not outcome["errors"]


def handle_command(command: str, args: list) -> bool:
    """Handle the prune command. Returns True if handled."""
    if command != PRIMARY_COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    # Screen the WHOLE sequence, not just args[0], as every verb here does: a
    # trailing --help must never reach a run that can delete.
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True

    positional = [arg for arg in args if not arg.startswith("--")]
    unknown = [arg for arg in args if arg.startswith("--") and arg != "--apply"]
    if unknown or len(positional) != 1:
        error(f"prune takes one project and --apply: got {' '.join(args)}", suggestion=USAGE)
        return True

    run_prune(str(resolve_caller_path(positional[0])), apply="--apply" in args)
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
