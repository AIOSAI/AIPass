# =================== AIPass ====================
# Name: status.py
# Description: Status module — show backup status for a project
# Version: 1.1.0
# Created: 2026-04-23
# Modified: 2026-08-08
# =============================================

"""Status Module — display backup info and recent history for a project."""

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

from aipass.backup.apps.handlers.json import json_handler
from aipass.backup.apps.handlers.path.builder import backup_root
from aipass.backup.apps.handlers.path.caller import resolve_caller_path
from aipass.backup.apps.handlers.project.config import load_project_config
from aipass.backup.apps.handlers.state.changelog import load_changelog

MODULE_NAME = "status"
PRIMARY_COMMAND = "status"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: Phase 3 — implemented")
    console.print("  Handlers: path, project/config, state/changelog")


def print_help():
    """Display help for this module."""
    print_introspection()


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
        print_introspection()
        return True

    project_root = str(resolve_caller_path(args[0]))
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

    json_handler.log_operation("status_displayed", {"project_root": project_root})
    logger.info(f"[backup] Status shown for {project_root}")
    return True


# =============================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
