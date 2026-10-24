# =================== AIPass ====================
# Name: prax.py
# Description: Entry point CLI for drone @prax — logging, monitoring, dashboard
# Version: 1.1.0
# Created: 2026-03-05
# Modified: 2026-10-24
# =============================================

"""PRAX Branch - Main Orchestrator"""

import os
import sys
from pathlib import Path

import argparse
import importlib
from typing import Callable, List

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.cli.apps.modules import console, error, warning, reset_command_state, resolve_exit

from aipass.prax.apps.modules import (
    UnknownArgument,
    did_you_mean,
    refuse,
    unknown_option,
)

TOP_LEVEL_OPTIONS = ("--help", "-h", "--version", "-V")


def discover_command_modules() -> List[Callable]:
    """Auto-discover handle_command(command, args) -> bool from each module in modules/."""
    command_handlers = []
    modules_dir = Path(__file__).parent / "modules"

    if not modules_dir.exists():
        return command_handlers

    for module_file in modules_dir.glob("*.py"):
        if module_file.name.startswith("_") or module_file.name == "logger.py":
            continue

        try:
            module_name = f"aipass.prax.apps.modules.{module_file.stem}"
            module = importlib.import_module(module_name)

            if hasattr(module, "handle_command"):
                command_handlers.append(module.handle_command)

        except Exception as e:
            logger.warning("Failed to load module %s: %s", module_file.name, e)
            warning(f"Failed to load module {module_file.name}: {e}")

    return command_handlers


def print_introspection():
    """Display discovered modules (main entry point - modules only, no handlers)"""
    console.print()
    console.print("[bold cyan]PRAX - System-Wide Logging Infrastructure[/bold cyan]")
    console.print()
    console.print("[dim]Unified logging system for AIPass ecosystem[/dim]")
    console.print()

    modules_dir = Path(__file__).parent / "modules"
    discovered_modules = []

    if modules_dir.exists():
        for module_file in modules_dir.glob("*.py"):
            if module_file.name.startswith("_") or module_file.name == "logger.py":
                continue
            discovered_modules.append(module_file.stem)

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(discovered_modules)}")
    console.print()

    for module_name in sorted(discovered_modules):
        console.print(f"  [cyan]•[/cyan] {module_name}")

    console.print()
    console.print("[dim]Run 'drone @prax --help' for usage information[/dim]")
    console.print()


def print_help():
    """Rich-formatted top-level help for PRAX"""
    console.print()
    console.print("[bold cyan]PRAX - System-Wide Logging Infrastructure[/bold cyan]")
    console.print()
    console.print("[dim]Unified logging system for AIPass ecosystem[/dim]")
    console.print()

    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [green]drone @prax <command>[/green] [dim]\\[options][/dim]")
    console.print()

    console.print("[yellow]Commands:[/yellow]")
    console.print("  [cyan]monitor[/cyan]     Mission Control - unified real-time monitoring")
    console.print("  [cyan]status[/cyan]      Show PRAX system status")
    console.print("  [cyan]log-audit[/cyan]   Audit log file sizes and health")
    console.print("  [cyan]log-health[/cyan]  Log growth rates (scan / snapshot)")
    console.print("  [cyan]dashboard[/cyan]   System dashboard")
    console.print("  [cyan]discover[/cyan]    Scan the ecosystem into the module registry")
    console.print()

    console.print("[yellow]Flags:[/yellow]")
    console.print("  [cyan]--help[/cyan]       Show help information")
    console.print("  [cyan]--version[/cyan]    Show version")
    console.print()

    console.print("[yellow]Examples:[/yellow]")
    console.print("  $ drone @prax monitor run")
    console.print("  $ drone @prax status")
    console.print("  $ drone @prax log-audit audit")
    console.print("  $ drone @prax dashboard")
    console.print("  $ drone @prax discover run")
    console.print()


def route_command(command: str, args: List[str], handlers: List[Callable]) -> bool:
    """Route command to a module handler.

    True if a module owned the command, including one that failed (reported through error()); False if none owns it.
    """
    for handler in handlers:
        try:
            if handler(command, args):
                return True
        except UnknownArgument:
            # A refusal is an answer: main renders it and exits 1.
            raise
        except Exception as e:
            # Handled and failed: error() sets the flag resolve_exit turns into exit 2.
            logger.error("Handler failed: %s", e)
            error(f"Handler failed: {e}")
            return True

    return False


def main() -> int:
    """Main entry point — renders any unknown-argument refusal and exits 1.

    The exit seam: state is reset here so a failure flag from an earlier in-process run cannot leak in.
    """
    reset_command_state()
    try:
        return _run()
    except UnknownArgument as exc:
        error(str(exc), suggestion=exc.usage or None)
        return 1


def _run() -> int:
    """Parse the command line and route it. Refusals are raised, never returned."""
    parser = argparse.ArgumentParser(
        description="PRAX - System-Wide Logging Infrastructure",
        add_help=False,  # We route --help to modules when a command is given
    )

    parser.add_argument("command", nargs="?", help="Command to execute")

    parser.add_argument("args", nargs="*", help="Arguments for the command")

    parser.add_argument("--help", "-h", action="store_true", dest="show_help", help="Show help information")
    parser.add_argument("--version", "-V", action="version", version="PRAX v2.4.0")

    parsed_args, remaining = parser.parse_known_args()

    # Stray-flag check first: argparse hands unrecognised flags back instead of erroring.
    if not parsed_args.command:
        stray = unknown_option(remaining, TOP_LEVEL_OPTIONS)
        if stray is not None:
            nearest = did_you_mean(stray, TOP_LEVEL_OPTIONS)
            refuse("prax", stray, f"drone @prax {nearest}" if nearest else "drone @prax --help")
        if parsed_args.show_help:
            print_help()
        else:
            print_introspection()
        return 0

    handlers = discover_command_modules()

    if not handlers:
        error("No command modules discovered")
        return 1

    all_args = parsed_args.args + remaining

    if parsed_args.show_help:
        all_args = ["--help"] + all_args

    if route_command(parsed_args.command, all_args, handlers):
        return resolve_exit(True)
    else:
        error(f"Unknown command: {parsed_args.command}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        logger.error("Unhandled error in main: %s", exc)
        sys.exit(1)
