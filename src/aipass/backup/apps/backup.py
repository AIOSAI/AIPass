# =================== AIPass ====================
# Name: backup.py
# Description: BACKUP Branch — main orchestrator with auto-discovery
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-23
# =============================================

"""BACKUP Branch - Main Orchestrator

Auto-discovery architecture:
- Scans modules/ directory for .py files with handle_command()
- Routes commands to discovered modules automatically
- Accepts project paths or registered project names
"""

import importlib
import os
import sys
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("AIPASS_BRANCH_NAME", "backup")

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, header

VERSION = "1.0.0"
MODULE_NAME = "backup"
MODULES_DIR = Path(__file__).parent / "modules"


def print_introspection(modules: list[Any]) -> None:
    """Display discovered modules — the bare self-map (run with no args)."""
    console.print()
    console.print(f"[bold cyan]BACKUP[/bold cyan] v{VERSION} — project backup & drive sync")
    console.print()
    console.print(f"[bold dim]Discovered Modules:[/bold dim] {len(modules)}")
    console.print()
    for module in modules:
        name = module.__name__.split(".")[-1]
        doc = (module.__doc__ or "").strip().split("\n")[0]
        console.print(f"  [cyan]-[/cyan] {name:20} [dim]{doc or 'No description'}[/dim]")
    console.print()
    console.print("[dim]Run 'drone @backup --help' for usage and commands[/dim]")
    console.print()


def print_help() -> None:
    """Display the curated Rich-formatted command reference."""
    console.print()
    header("BACKUP — project backup & drive sync")
    console.print()
    console.print("[dim]Snapshot, version, and sync project backups to a local store or remote drive.[/dim]")
    console.print()
    console.print("-" * 70)
    console.print()
    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @backup <command> <project_path|@name>[/dim]")
    console.print("  [dim]drone @backup --help[/dim]")
    console.print()
    console.print("-" * 70)
    console.print()
    console.print("[bold cyan]COMMANDS:[/bold cyan]")
    console.print()
    console.print("  [green]snapshot[/green]     Full mirror backup of a project")
    console.print("  [green]versioned[/green]    Incremental timestamped backup")
    console.print("  [green]all[/green]          Run snapshot then versioned in sequence")
    console.print("  [green]register[/green]     Register a project + scaffold its .backup/")
    console.print("  [green]status[/green]       Show backup info and recent history")
    console.print("  [green]settings[/green]     [dim]Not implemented — settings UI deferred[/dim]")
    console.print("  [green]drive_sync[/green]   Sync backups to the remote drive")
    console.print("  [green]drive_check[/green]  Test the remote drive connection")
    console.print("  [green]drive_stats[/green]  Drive usage statistics")
    console.print("  [green]share[/green]        Upload a single file to Drive + get a shareable link")
    console.print("  [green]drive_clear[/green]  Clear the local Drive tracker (remote files untouched)")
    console.print()
    console.print("-" * 70)
    console.print()
    console.print("[bold cyan]EXAMPLES:[/bold cyan]")
    console.print()
    console.print("  [bold dim]Register & back up:[/bold dim]")
    console.print("    [dim]drone @backup register /path/to/project --name myapp[/dim]")
    console.print("    [dim]drone @backup snapshot @myapp[/dim]")
    console.print("    [dim]drone @backup versioned @myapp[/dim]")
    console.print("    [dim]drone @backup all @myapp[/dim]")
    console.print()
    console.print("  [bold dim]Status & restore:[/bold dim]")
    console.print("    [dim]drone @backup status @myapp[/dim]")
    console.print("    [dim]drone @backup restore @myapp list src/main.py[/dim]")
    console.print("    [dim]drone @backup restore @myapp file src/main.py ./restored.py[/dim]")
    console.print()
    console.print("  [bold dim]Drive sync:[/bold dim]")
    console.print("    [dim]drone @backup drive_check @myapp[/dim]")
    console.print("    [dim]drone @backup drive_sync @myapp[/dim]")
    console.print("    [dim]drone @backup share report.pdf --public[/dim]")
    console.print()


def discover_modules() -> list[Any]:
    """Auto-discover modules in modules/ directory."""
    modules = []

    if not MODULES_DIR.exists():
        return modules

    for file_path in MODULES_DIR.glob("*.py"):
        if file_path.name.startswith("_"):
            continue

        module_name = f"aipass.backup.apps.modules.{file_path.stem}"

        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "handle_command"):
                modules.append(module)
        except Exception as e:
            logger.error(f"[BACKUP] Failed to load module {module_name}: {e}")

    return modules


def route_command(command: str, args: list[str], modules: list[Any]) -> tuple[bool, str | None]:
    """Route command to appropriate module.

    Every module is asked in turn, so one module raising must not deny the
    command to a module further down the list -- that is why the exception is
    caught rather than propagated.

    But a caught exception is NOT the same answer as "nobody claimed this",
    and folding the two together is what made a corrupt ``.backup/config.json``
    print ``Unknown command: snapshot`` (measured live, 2026-09-03): the
    command was known, it failed, and the operator was sent hunting for a typo.

    Args:
        command: The verb to route.
        args: Remaining CLI arguments.
        modules: Discovered modules exposing handle_command.

    Returns:
        (handled, failure). ``failure`` is the first module error seen, as
        text for the operator, and is only meaningful when handled is False.
    """
    failure: str | None = None
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True, None
        except Exception as e:
            logger.error(f"[BACKUP] Module {module.__name__} error: {e}")
            if failure is None:
                failure = f"{module.__name__}: {e}"
    return False, failure


def main():
    """Main entry point - routes commands or shows help."""
    args = sys.argv[1:]

    if args and args[0] in ("--version", "-V"):
        console.print(f"backup {VERSION}")
        return 0

    modules = discover_modules()

    if len(args) == 0:
        print_introspection(modules)
        return 0

    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return 0

    command = args[0]
    remaining = args[1:]

    # A help flag ANYWHERE after the command is a help request, never a run.
    # Checking only remaining[0] let 'snapshot <project> --help' fall through
    # and execute a real backup.
    if any(arg in ("--help", "-h") for arg in remaining):
        for module in modules:
            if module.handle_command(command, ["--help"]):
                return 0
        print_help()
        return 0

    if command == "backup" and len(args) > 1:
        from aipass.backup.apps.modules.register import resolve_project

        target = args[1]
        project_root = resolve_project(target)
        if project_root is None:
            error(f"Cannot resolve project: {target}")
            return 1
        remaining = [project_root] + args[2:]
        mode = "snapshot"
        if "--versioned" in args:
            mode = "versioned"
            remaining = [r for r in remaining if r != "--versioned"]
        elif "--all" in args:
            mode = "all"
            remaining = [r for r in remaining if r != "--all"]

        handled, failure = route_command(mode, remaining, modules)
        if handled:
            return 0
        if failure:
            error(f"{mode} failed -- {failure}")
            return 1
        error(f"Unknown mode: {mode}")
        return 1

    remaining = args[1:] if len(args) > 1 else []

    if remaining and remaining[0].startswith("@"):
        from aipass.backup.apps.modules.register import resolve_project

        resolved = resolve_project(remaining[0])
        if resolved is None:
            error(f"Cannot resolve project: {remaining[0]}")
            return 1
        remaining = [resolved] + remaining[1:]

    handled, failure = route_command(command, remaining, modules)
    if handled:
        return 0

    if failure:
        error(f"{command} failed -- {failure}")
        return 1

    error(f"Unknown command: {command}")
    return 1


# =============================================

if __name__ == "__main__":
    sys.exit(main())
