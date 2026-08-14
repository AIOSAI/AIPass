# =================== AIPass ====================
# Name: feedback.py
# Version: 1.0.0
# Description: Feedback pulse toggle — on/off control for periodic feedback ask
# Branch: hooks
# Layer: apps/modules
# Created: 2026-07-18
# Modified: 2026-07-18
# =============================================

"""Feedback pulse toggle — on/off control for the periodic feedback ask via drone @hooks feedback."""

from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.handlers.json import json_handler
from aipass.prax.apps.modules.logger import system_logger as logger  # noqa: F401

CONSOLE = err_console

HELP_COMMANDS = [
    ("feedback on", "Enable feedback pulse (default)"),
    ("feedback off", "Disable feedback pulse"),
    ("feedback", "Show current feedback pulse status"),
]


def _find_aipass_dir() -> Path | None:
    """Walk up from CWD to find the nearest .aipass/ directory."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / ".aipass"
        if candidate.is_dir():
            return candidate
        if parent == parent.parent:
            break
    return None


def _sentinel() -> Path | None:
    """Return the sentinel file path, or None if no .aipass/ dir found."""
    aipass_dir = _find_aipass_dir()
    if aipass_dir is None:
        return None
    return aipass_dir / "feedback_off"


def print_introspection() -> None:
    """Print module structure for drone routing."""
    sentinel = _sentinel()
    if sentinel is None:
        status = "NO PROJECT"
    else:
        status = "DISABLED" if sentinel.exists() else "ENABLED"
    CONSOLE.print(f"[bold cyan]feedback[/bold cyan] — Feedback pulse ({status})")


def handle_command(command: str, args: list) -> bool:
    """Route feedback commands from drone @hooks."""
    if command == "feedback":
        if not args:
            print_introspection()
            return True

        sub = args[0]

        if wants_help(args):
            CONSOLE.print("[bold cyan]feedback[/bold cyan] — Toggle the periodic feedback pulse")
            CONSOLE.print()
            CONSOLE.print("  drone @hooks feedback        Show current status")
            CONSOLE.print("  drone @hooks feedback on     Enable feedback pulse (default)")
            CONSOLE.print("  drone @hooks feedback off    Disable feedback pulse")
            return True

        if sub == "off":
            sentinel = _sentinel()
            if sentinel is None:
                CONSOLE.print("[yellow]No .aipass/ directory found[/yellow]")
                return True
            sentinel.touch()
            json_handler.log_operation("feedback_toggle", {"state": "off"})
            CONSOLE.print("[yellow]Feedback pulse DISABLED[/yellow]")
            return True

        if sub == "on":
            sentinel = _sentinel()
            if sentinel is None:
                CONSOLE.print("[yellow]No .aipass/ directory found[/yellow]")
                return True
            if sentinel.exists():
                sentinel.unlink()
            json_handler.log_operation("feedback_toggle", {"state": "on"})
            CONSOLE.print("[green]Feedback pulse ENABLED[/green]")
            return True

    return False
