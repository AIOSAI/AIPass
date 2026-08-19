# =================== AIPass ====================
# Name: hooksound.py
# Version: 1.1.0
# Description: Hook sound control — mute/unmute all hook audio
# Branch: hooks
# Layer: apps/modules
# Created: 2026-05-22
# Modified: 2026-08-18
# =============================================

"""Hook sound control — mute and unmute all hook audio via drone @hooks hooksound."""

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.sound import is_muted, mute, unmute
from aipass.prax.apps.modules.logger import system_logger as logger

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

        # The flag is written through sound.py, not touched here: one writer. This
        # module used to import the logger and never call it (noqa: F401), so a
        # state change nobody could audit left no trace at all. The split is real:
        # the door logs that the CLI was used, sound.py logs the effect — @api now
        # imports mute()/unmute() directly, and those two callers look different.
        if sub in ("on", "off"):
            logger.info("[HOOKS] hooksound: '%s' requested via CLI", sub)

        if sub == "off":
            mute()
            CONSOLE.print("[yellow]Hook sounds MUTED[/yellow]")
            return True

        if sub == "on":
            unmute()
            CONSOLE.print("[green]Hook sounds ACTIVE[/green]")
            return True

    return False
