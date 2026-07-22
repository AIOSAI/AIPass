# =================== AIPass ====================
# Name: aipass.py
# Description: AIPASS branch entry point — thin command router
# Version: 0.1.0
# Created: 2026-04-16
# Modified: 2026-04-16
# =============================================

"""
AIPASS Branch - Main Orchestrator

Auto-discovery architecture:
- Scans modules/ directory for .py files with handle_command()
- Routes commands to discovered modules automatically
- No manual imports or routing needed
"""

import os
import sys
import importlib
import importlib.metadata
from pathlib import Path
from typing import List, Any

# Windows terminals/pipes default to cp1252, which can't encode the Unicode
# Rich emits (✓/✗, box-drawing, arrows). PYTHONUTF8 only affects child
# interpreters, not this process's already-open stdout/stderr — so we also
# reconfigure the live streams to UTF-8 in place (Python 3.7+). Without this,
# `aipass init` scaffolds correctly but crashes printing its success banner
# with UnicodeEncodeError ('charmap') on Windows. Mirrors drone/cli.py.
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")  # for child subprocesses
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.cli.apps.modules import console, error
from aipass.prax import logger

# =============================================================================
# COMMANDS — public-facing labels and descriptions
# =============================================================================

_PUBLIC_COMMANDS = {
    "adopt": "Turn an existing projects/ directory into a full project",
    "doctor": "System health — structure, registry, hooks, tests",
    "help": "README-backed Q&A — ask about any branch",
    "init": "Guided setup for new users (10 stages, resumable)",
    "install": "One-command bootstrap — clone + setup + init",
    "new": "Create a project inside AIPass",
    "profile": "Show/edit user profile",
    "trust": "Trust registry — enroll/revoke projects",
    "feedback": "Toggle the feedback reminder on/off",
}

# =============================================================================
# MODULE DISCOVERY
# =============================================================================

MODULES_DIR = Path(__file__).parent / "modules"


_import_failures: dict[str, Exception] = {}


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
            module = importlib.import_module(module_name)
            if hasattr(module, "handle_command"):
                modules.append(module)
        except Exception as e:
            logger.error(f"[AIPASS] Failed to load module {module_name}: {e}")
            _import_failures[file_path.stem] = e

    return modules


# =============================================================================
# HELP OUTPUT — house pattern (cli_ux)
# =============================================================================


def print_introspection(modules: List[Any] | None = None) -> None:
    """Bare invocation — title, purpose, public commands, --help pointer."""
    console.print()
    console.print("[bold cyan]AIPASS — Concierge & Setup[/bold cyan]")
    console.print("[dim]The friendly front door for AIPass. Setup, diagnostics, documentation, project creation.[/dim]")
    console.print()

    if modules is None:
        modules = discover_modules()

    commands = []
    for module in modules:
        name = getattr(module, "COMMAND", None)
        if name and name in _PUBLIC_COMMANDS:
            commands.append((name, _PUBLIC_COMMANDS[name]))
    commands.sort()

    if commands:
        console.print("[yellow]Commands:[/yellow]")
        for name, desc in commands:
            console.print(f"  [green]{name:16}[/green] [dim]{desc}[/dim]")
        console.print()

    console.print("[dim]Run 'aipass --help' for usage and examples[/dim]")
    console.print()


def print_help(modules: List[Any] | None = None) -> None:
    """Full help — usage, commands, examples."""
    console.print()
    console.print("[bold cyan]AIPASS — Concierge & Setup[/bold cyan]")
    console.print("[dim]The friendly front door for AIPass. Setup, diagnostics, documentation, project creation.[/dim]")
    console.print()

    console.print("[yellow]Usage:[/yellow]")
    console.print("  [green]aipass[/green] [dim]<command>[/dim] [dim][options][/dim]")
    console.print("  [green]aipass[/green]                       [dim]Show commands[/dim]")
    console.print("  [green]aipass[/green] [dim]<command>[/dim] [dim]--help[/dim]     [dim]Help for a command[/dim]")
    console.print()

    console.print("[yellow]Commands:[/yellow]")
    console.print(
        "  [green]doctor[/green]                       [dim]System health — structure, registry, hooks, tests[/dim]"
    )
    console.print("  [green]doctor --fix[/green]                 [dim]Remediation report with repair commands[/dim]")
    console.print("  [green]doctor --json[/green]                [dim]JSON output for structure scan[/dim]")
    console.print("  [green]doctor --cross-os[/green]            [dim]Cross-OS pre-flight check[/dim]")
    console.print("  [green]help <question>[/green]              [dim]Search branch documentation (Q&A)[/dim]")
    console.print(
        "  [green]init[/green]                         [dim]Guided setup for new users (10 stages, resumable)[/dim]"
    )
    console.print(
        "  [green]install[/green]                      [dim]One-command bootstrap — clone + setup.sh + hooks[/dim]"
    )
    console.print("  [green]new <name>[/green]                   [dim]Create a project inside AIPass[/dim]")
    console.print(
        "  [green]adopt <name>[/green]                 "
        "[dim]Turn an existing projects/ directory into a full project[/dim]"
    )
    console.print("  [green]profile[/green]                      [dim]Show/edit user profile[/dim]")
    console.print(
        "  [green]trust[/green] [dim][path][/dim]                [dim]Trust registry — enroll/revoke projects[/dim]"
    )
    console.print("  [green]--version[/green]                    [dim]Show version[/dim]")
    console.print()

    console.print("[yellow]Examples:[/yellow]")
    console.print("  [green]aipass doctor[/green]                       [dim]Check system health[/dim]")
    console.print("  [green]aipass help what does drone do[/green]      [dim]Search documentation[/dim]")
    console.print("  [green]aipass new myapp --template python[/green]  [dim]Create a Python project[/dim]")
    console.print("  [green]aipass adopt myapp --dry-run[/green]        [dim]Preview adopting projects/myapp[/dim]")
    console.print("  [green]aipass init[/green]                         [dim]Start guided setup[/dim]")
    console.print()


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """Route command to appropriate module.

    Returns True on success. Raises on handler crash so callers can
    distinguish 'not found' (False) from 'found but broken'.
    """
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except Exception as e:
            mod_name = module.__name__.split(".")[-1]
            logger.error(f"[AIPASS] Module {mod_name} crashed: {e}")
            raise
    return False


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main():
    """Main entry point - routes commands or shows help."""
    modules = discover_modules()
    args = sys.argv[1:]

    if len(args) > 0 and args[0] in ["--version", "-V"]:
        try:
            version = importlib.metadata.version("aipass")
        except importlib.metadata.PackageNotFoundError:
            logger.info("[AIPASS] Package metadata not found, version unknown")
            version = "unknown"
        console.print(f"aipass {version}")
        return 0

    if not args:
        print_introspection(modules)
        return 0

    if args[0] in ("--help", "-h"):
        print_help(modules)
        return 0

    command = args[0]
    remaining = args[1:] if len(args) > 1 else []

    # Subcommand --help guard: intercept before dispatch
    if remaining and remaining[0] in ("--help", "-h"):
        for module in modules:
            if module.handle_command(command, ["--help"]):
                return 0
        console.print(f"Unknown command: {command}")
        return 1

    try:
        if route_command(command, remaining, modules):
            return 0
    except Exception as e:
        error(f"'{command}' crashed: {e}")
        logger.error(f"[AIPASS] '{command}' traceback", exc_info=True)
        return 1

    if command.startswith("@"):
        console.print(f"{command} is a drone routing target, not an aipass command.")
        console.print("aipass is your front-door CLI; drone is the agent router — two separate tools.")
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
