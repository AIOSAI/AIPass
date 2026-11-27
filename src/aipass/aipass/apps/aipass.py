# =================== AIPass ====================
# Name: aipass.py
# Description: aipass branch entry point — thin command router
# Version: 2.8.41
# Created: 2026-04-16
# Modified: 2026-11-26
# =============================================

"""
aipass Branch - Main Orchestrator
"""

import re
import sys
import importlib
from pathlib import Path
from typing import List, Any

from aipass.cli import console, error, header_version, resolve_exit, warning
from aipass.prax import logger

MODULES_DIR = Path(__file__).parent / "modules"


_import_failures: dict[str, Exception] = {}


def _import_module(name: str) -> Any:
    """``importlib.import_module(name)``, unchanged.

    A seam: every real module has handle_command, so the test reaches the skip branch here.
    """
    return importlib.import_module(name)


def discover_modules() -> List[Any]:
    """Auto-discover modules in modules/ directory."""
    modules = []
    _import_failures.clear()

    if not MODULES_DIR.exists():
        return modules

    for file_path in MODULES_DIR.glob("*.py"):
        if file_path.name.startswith("_"):
            continue

        module_name = f"aipass.aipass.apps.modules.{file_path.stem}"

        try:
            module = _import_module(module_name)
            if hasattr(module, "handle_command"):
                modules.append(module)
        except Exception as e:
            logger.error(f"[aipass] Failed to load module {module_name}: {e}")
            _import_failures[file_path.stem] = e

    return modules


def _description(module: Any) -> str:
    """The module docstring's first paragraph, minus its leading 'aipass <command> —' or ':'."""
    paragraph = " ".join((module.__doc__ or "").strip().split("\n\n")[0].split())
    return re.sub(r"^aipass [\w /]+?(?: —|:)\s*", "", paragraph)


def _print_commands(modules: List[Any]) -> None:
    """The command table: every discovered module with a COMMAND, in its own words."""
    commands = sorted((m.COMMAND, _description(m)) for m in modules if getattr(m, "COMMAND", None))
    if commands:
        console.print("[yellow]Commands:[/yellow]")
        console.print("[dim]Each command below is a module of this CLI.[/dim]")
        for name, desc in commands:
            console.print(f"  [green]{name:16}[/green] [dim]{desc}[/dim]")
        console.print()


def print_introspection(modules: List[Any] | None = None) -> None:
    """Bare invocation — title, purpose, public commands, --help pointer."""
    console.print()
    console.print("[bold cyan]aipass — machine concierge[/bold cyan]")
    console.print("[dim]Host and OS diagnosis, doctor, installer, fleet health.[/dim]")
    console.print()

    if modules is None:
        modules = discover_modules()

    _print_commands(modules)
    console.print("[dim]Run 'aipass --help' for usage and examples[/dim]")
    console.print()


def print_help(modules: List[Any] | None = None) -> None:
    """Full help — usage, commands, examples."""
    console.print()
    console.print("[bold cyan]aipass — machine concierge[/bold cyan]")
    console.print("[dim]Host and OS diagnosis, doctor, installer, fleet health.[/dim]")
    console.print()

    console.print("[yellow]Usage:[/yellow]")
    console.print("  [green]aipass[/green] [dim]<command>[/dim] [dim]\\[options][/dim]")
    console.print("  [green]aipass[/green]                       [dim]Show commands[/dim]")
    console.print("  [green]aipass[/green] [dim]<command>[/dim] [dim]--help[/dim]     [dim]Help for a command[/dim]")
    console.print("  [green]aipass --version[/green]             [dim]Show version[/dim]")
    console.print()

    _print_commands(discover_modules() if modules is None else modules)

    console.print("[yellow]Examples:[/yellow]")
    console.print("  [green]aipass doctor[/green]                       [dim]Check system health[/dim]")
    console.print("  [green]aipass new myapp --template python[/green]  [dim]Create a Python project[/dim]")
    console.print("  [green]aipass adopt myapp --dry-run[/green]        [dim]Preview adopting projects/myapp[/dim]")
    console.print()


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """Route command to appropriate module.

    Raises on a crash (False means not found); main() logs it, a log call here could mask it.
    """
    for module in modules:
        if module.handle_command(command, args):
            return True
    return False


def _log_crash(message: str) -> None:
    """Log the crash being handled, with its traceback; never raise from the log itself.

    A handler that raises from its own logging (an unwritable log home) hides the user's error.
    """
    try:
        logger.error(message, exc_info=True)
    except OSError as exc:
        warning(f"(this crash could not be written to the log: {exc})")


def main():
    """Main entry point - routes commands or shows help.

    Exit codes: 0 clean; 2 a module reported through error(); 1 unknown command, crash
    or load failure. No success path returns 1.
    """
    modules = discover_modules()
    args = sys.argv[1:]

    if len(args) > 0 and args[0] in ["--version", "-V"]:
        console.print(f"aipass v{header_version(__file__)}", highlight=False)
        return 0

    if not args:
        print_introspection(modules)
        return 0

    if args[0] in ("--help", "-h"):
        print_help(modules)
        return 0

    command = args[0]
    remaining = args[1:] if len(args) > 1 else []

    # --help in ANY position answers before dispatch: a help probe must never run the
    # verb (`aipass trust <dir> --help` would enroll the dir).
    if any(a in ("--help", "-h") for a in remaining):
        for module in modules:
            if module.handle_command(command, ["--help"]):
                return 0
        console.print(f"Unknown command: {command}")
        return 1

    # A module that reports through error() and returns True failed: resolve_exit makes it 2.
    try:
        if route_command(command, remaining, modules):
            return resolve_exit(True)
    except Exception as e:
        error(f"'{command}' crashed: {e}")
        _log_crash(f"[aipass] '{command}' traceback")
        return 1

    if command.startswith("@"):
        console.print(f"{command} is a drone routing target, not an aipass command.")
        console.print("aipass is the machine concierge CLI; drone is the agent router — two separate tools.")
        console.print()
        console.print(f"  Reach an agent:   drone {command} ...   ·  drone systems")
        console.print("  aipass commands:  aipass --help")
        return 1

    for stem, err in _import_failures.items():
        if command in (stem, stem.replace("_", "")):
            error(f"'{command}' failed to load: {err}")
            return 1

    console.print(f"Unknown command: {command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
