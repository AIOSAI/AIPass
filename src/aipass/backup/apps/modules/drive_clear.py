# =================== AIPass ====================
# Name: drive_clear.py
# Description: Drive clear module — clears Drive file tracker (requires --force)
# Version: 1.0.0
# Created: 2026-04-17
# Modified: 2026-06-12
# =============================================

"""Drive Clear Module — clears the Drive file tracker for a project."""

import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.cli.apps.modules import console, error as cli_error

from aipass.backup.apps.handlers.json import json_handler


MODULE_NAME = "drive_clear"
PRIMARY_COMMAND = "drive_clear"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: Phase 4 -- tracker clear")
    console.print("  Handlers: drive/tracker (requires --force)")


def print_help():
    """Display help for this module."""
    print_introspection()
    console.print()
    console.print("Usage: drive_clear <project_root> --force")
    console.print("  --force   Required to confirm tracker deletion")


def run_drive_clear(project_root: str, force: bool = False) -> bool:
    """Clear Drive tracker. Requires force=True.

    Args:
        project_root: Absolute path to the project.
        force: Must be True to proceed.

    Returns:
        True if cleared, False otherwise.
    """
    from aipass.backup.apps.handlers.drive.tracker import clear_all

    if not force:
        console.print("[dim]Use --force to confirm tracker deletion.[/dim]")
        return False

    success = clear_all(project_root)
    if success:
        console.print("[green]Drive tracker cleared.[/green]")
        logger.info(f"[backup] Drive tracker cleared for {project_root}")
    else:
        cli_error("Failed to clear Drive tracker.")

    json_handler.log_operation(
        "drive_clear_complete",
        {"project_root": project_root, "success": success},
    )
    return success


def handle_command(command: str, args: list) -> bool:
    """Handle the drive-clear-tracker command. Returns True if handled."""
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

    project_root = args[0]
    force = "--force" in args
    run_drive_clear(project_root, force=force)
    return True


# =============================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
