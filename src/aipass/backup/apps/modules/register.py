# =================== AIPass ====================
# Name: register.py
# Description: Register module — adds a project to backup and creates .backup/
# Version: 1.3.2
# Created: 2026-04-17
# Modified: 2026-11-26
# =============================================

"""Register Module — register a project for backup and scaffold its .backup/."""

import sys
from pathlib import Path

from aipass.prax import logger
from aipass.cli import console, error, escape

from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.path.caller import resolve_caller_path
from aipass.backup.apps.handlers.project.registry import lookup_project as _lookup_project
from aipass.backup.apps.handlers.project.registry import register_project, unregister_project
from aipass.backup.apps.handlers.project.setup import create_backup_dir
from aipass.backup.apps.handlers.schedule.jobs import ScheduleError, remove_job


def resolve_project(target: str) -> str | None:
    """Resolve a target to an absolute project path.

    Accepts absolute/relative paths, @Name, or registered names.
    """
    if target.startswith("@"):
        name = target[1:]
        path = _lookup_project(name)
        if path:
            return path
        logger.warning(f"[backup] Project '@{name}' not found in registry")
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
USAGE = "register <project_path> [--name <name>] | register --remove <name>"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print("  [dim]Add a project to backup and scaffold its .backup/, or remove it[/dim]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Handlers: project/setup, project/registry")
    console.print("  [dim]Run[/dim] [green]drone @backup register --help[/green] [dim]for usage[/dim]")


def print_help():
    """Display help for this module."""
    print_introspection()
    console.print()
    console.print(f"[yellow]Usage:[/yellow] {escape(USAGE)}")
    console.print("  [cyan]--name[/cyan]    register under a short name, so @name resolves")
    console.print("  [cyan]--remove[/cyan]  drop a project from the registry and its scheduled job; its .backup/ stays")
    console.print()
    console.print("[yellow]Examples:[/yellow]")
    console.print("  [green]drone @backup register /path/to/project --name myapp[/green]")
    console.print("  [green]drone @backup register --remove myapp[/green]")


def remove_project(name: str) -> None:
    """Unregister ``name``, its scheduled backup job first; any refusal is an error on stderr."""
    if _lookup_project(name) is None:
        error(f"No registered project named '{name}'")
        return
    # The job goes first: a job left for an unregistered project would fail every night.
    try:
        job_removed = remove_job(name)
    except ScheduleError as exc:
        error(f"Not removed: the scheduled backup job could not be removed: {exc}")
        return
    if not unregister_project(name):
        error(f"Failed to write the project registry removing '{name}'")
        return
    logger.info(f"[backup] Removed project '{name}' from the registry")
    job_line = "; its scheduled backup job removed" if job_removed else ""
    console.print(f"[green]Removed:[/green] {name} (its .backup/ store is left in place{job_line})")


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
        print_help()
        return True

    if args[0] == "--remove":
        remove_project(args[1] if len(args) > 1 else "")
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

    if not register_project(name, project_path):
        error(f"Failed to write the project registry for '{name}'")
        return True

    trail.log_operation("register_complete", {"name": name, "path": project_path})
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
