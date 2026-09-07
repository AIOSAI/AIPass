# =================== AIPass ====================
# Name: settings.py
# Description: Settings module — opens the PyQt5 settings UI for a project
# Version: 0.1.0
# Created: 2026-04-17
# Modified: 2026-04-17
# =============================================

"""Settings Module — thin CLI wrapper delegating to handlers.

Stub scaffold awaiting Phase 3 handler implementations.
"""

import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.cli.apps.modules import console, warning
from aipass.backup.apps.handlers.audit import trail


MODULE_NAME = "settings"
PRIMARY_COMMAND = "settings"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: stub scaffold, awaiting Phase 3 implementation")
    console.print("  Planned handlers: ui/settings_window")


def print_help():
    """Display help for this module."""
    print_introspection()


def handle_command(command: str, args: list) -> bool:
    """Handle the settings command. Returns True if handled."""
    if command != PRIMARY_COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_introspection()
        return True

    # Say it out loud. Logging to file and exiting 0 reads as success to the
    # caller, which is the one thing a deferred command must never do.
    logger.warning(f"[backup] {MODULE_NAME} stub invoked with args={args} — awaiting Phase 3")
    trail.log_operation(f"{MODULE_NAME}_stub_invoked", {"args": args})
    warning(f"{PRIMARY_COMMAND} is not implemented — the settings UI is deferred (Phase 3)")
    console.print("[dim]Edit .backup/config.json in the project directly for now.[/dim]")
    return True


# =============================================

if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)
    result = handle_command(sys.argv[1], sys.argv[2:])
    sys.exit(0 if result else 1)
