# =================== AIPass ====================
# Name: hooksound.py
# Version: 1.0.0
# Description: Hook sound control — mute/unmute all hook audio
# Branch: hooks
# Layer: apps/modules
# Created: 2026-05-22
# Modified: 2026-05-22
# =============================================

"""Hook sound control — mute and unmute all hook audio via drone @hooks hooksound."""

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.sound import MUTE_FLAG, is_muted
from aipass.prax.apps.modules.logger import system_logger as logger  # noqa: F401

CONSOLE = err_console

HELP_COMMANDS = [
    ("hooksound on", "Unmute all hook sounds"),
    ("hooksound off", "Mute all hook sounds"),
    ("hooksound", "Show current sound status"),
]


def print_introspection():
    """Print module structure for drone routing."""
    status = "MUTED" if is_muted() else "ACTIVE"
    CONSOLE.print(f"[bold cyan]hooksound[/bold cyan] — Hook sound control ({status})")


def handle_command(command: str, args: list) -> bool:
    """Route hooksound commands from drone @hooks."""
    if command == "hooksound":
        if not args:
            print_introspection()
            return True

        sub = args[0]

        if wants_help(args):
            CONSOLE.print("[bold cyan]hooksound[/bold cyan] — Mute/unmute all hook audio")
            CONSOLE.print()
            CONSOLE.print("  drone @hooks hooksound        Show current status")
            CONSOLE.print("  drone @hooks hooksound on     Unmute all hook sounds")
            CONSOLE.print("  drone @hooks hooksound off    Mute all hook sounds")
            return True

        if sub == "off":
            MUTE_FLAG.touch()
            CONSOLE.print("[yellow]Hook sounds MUTED[/yellow]")
            return True

        if sub == "on":
            if MUTE_FLAG.exists():
                MUTE_FLAG.unlink()
            CONSOLE.print("[green]Hook sounds ACTIVE[/green]")
            return True

    return False
