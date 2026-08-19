# =================== AIPass ====================
# Name: register.py
# Description: Register module — adds a project to backup and creates .backup/
# Version: 1.1.0
# Created: 2026-04-17
# Modified: 2026-08-08
# =============================================

"""Register Module — register a project for backup and scaffold its .backup/."""

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

from aipass.backup.apps.handlers.json import json_handler
from aipass.backup.apps.handlers.path.caller import resolve_caller_path
from aipass.backup.apps.handlers.project.registry import lookup_project as _lookup_project
from aipass.backup.apps.handlers.project.registry import register_project
from aipass.backup.apps.handlers.project.setup import create_backup_dir


def resolve_project(target: str) -> str | None:
    """Resolve a target to an absolute project path.

    Accepts absolute/relative paths, @Name, or registered names.
    """
    if target.startswith("@"):
        name = target[1:]
        path = _lookup_project(name)
        if path:
            return path
        logger.warning(f"[BACKUP] Project '@{name}' not found in registry")
        return None

    candidate = resolve_caller_path(target)
    if candidate.is_dir():
        return str(candidate)

    path = _lookup_project(target)
    if path:
        return path

    return None


MODULE_NAME = "register"
PRIMARY_COMMAND = "register"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: Phase 3 — implemented")
    console.print("  Handlers: project/setup, project/registry")


def print_help():
    """Display help for this module."""
    print_introspection()


def handle_command(command: str, args: list) -> bool:
    """Handle the register command. Returns True if handled."""
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

    project_path = str(resolve_caller_path(args[0]))

    name = Path(project_path).name
    if "--name" in args:
        idx = args.index("--name")
        if idx + 1 < len(args):
            name = args[idx + 1]

    if not Path(project_path).is_dir():
        error(f"{project_path} is not a directory")
        return True

    backup_dir = create_backup_dir(project_path)
    if backup_dir is None:
        error(f"Failed to create .backup/ in {project_path}")
        return True

    register_project(name, project_path)

    json_handler.log_operation("register_complete", {"name": name, "path": project_path})
    logger.info(f"[backup] Registered project '{name}' at {project_path}")
    console.print(f"[green]Registered:[/green] {name}")
    console.print(f"  Path: {project_path}")
    console.print(f"  Backup dir: {backup_dir}")
    console.print(f"  Ignore file: {project_path}/.backupignore")
    return True


# =============================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
