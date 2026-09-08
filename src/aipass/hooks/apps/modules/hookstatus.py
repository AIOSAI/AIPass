# =================== AIPass ====================
# Name: hookstatus.py
# Version: 1.1.0
# Description: Hook status — read-only view of per-project hook config
# Branch: hooks
# Layer: apps/modules
# Created: 2026-05-28
# Modified: 2026-09-07
# =============================================

"""Hook status — read-only view of per-project hook configuration via drone @hooks status."""

import sys

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.handlers.config.loader import config_unavailable_reason, find_project_config
from aipass.prax.apps.modules.logger import system_logger as logger  # noqa: F401

CONSOLE = err_console

HELP_COMMANDS = [
    ("status", "Show current project hook config"),
]

EVENT_TYPES = [
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "SubagentStop",
    "Stop",
    "Notification",
    "SessionStart",
    "PreCompact",
]


def print_introspection():
    """Print module structure for drone routing."""
    CONSOLE.print("[bold cyan]hookstatus[/bold cyan] — Read-only hook config viewer")


def _render_status(config: dict) -> None:
    """Render the hook configuration to stderr console."""
    master = config.get("hooks_enabled", True)

    CONSOLE.print()
    if master:
        CONSOLE.print("[bold green]hooks_enabled: ON[/bold green]")
    else:
        CONSOLE.print("[bold red]hooks_enabled: OFF — ALL HOOKS DISABLED[/bold red]")
    CONSOLE.print()

    total = 0
    enabled = 0

    for event_type in EVENT_TYPES:
        group = config.get(event_type)
        if not group or not isinstance(group, dict):
            continue

        CONSOLE.print(f"[bold]{event_type}[/bold]")

        for name, hook_def in group.items():
            if not isinstance(hook_def, dict):
                continue
            total += 1
            is_enabled = hook_def.get("enabled", False)
            if is_enabled:
                enabled += 1

            glyph = "[green]✓[/green]" if is_enabled else "[dim]✗[/dim]"
            matcher = hook_def.get("matcher", "")
            matcher_str = f"  [dim]matcher: {matcher}[/dim]" if matcher else ""
            CONSOLE.print(f"  {glyph} {name}{matcher_str}")

        CONSOLE.print()

    CONSOLE.print(f"[bold]{enabled} enabled / {total} total[/bold]")


def handle_command(command: str, args: list) -> bool:
    """Route status commands from drone @hooks."""
    if command != "status":
        return False

    if not args:
        print_introspection()
        config = find_project_config()
        if config is None:
            # Exit 1, though this module only ever displays. "Display only" is a
            # promise not to WRITE config; it was never a promise to report
            # success having shown nothing. All four reasons mean the status was
            # not rendered, and three of them (unenrolled, hash mismatch,
            # unreadable) mean no hooks run here at all — the exact condition
            # that went unnoticed for two hours on 2026-09-07 because every
            # surface reporting it still exited 0.
            CONSOLE.print(f"[yellow]{config_unavailable_reason()}[/yellow]")
            sys.exit(1)
        _render_status(config)
        return True

    if wants_help(args):
        CONSOLE.print("[bold cyan]hookstatus[/bold cyan] — Read-only hook config viewer")
        CONSOLE.print()
        CONSOLE.print("  drone @hooks status           Show current project hook config")
        CONSOLE.print("  drone @hooks status --help    Show this help")
        CONSOLE.print()
        CONSOLE.print("Reads .aipass/hooks.json from the current directory tree.")
        CONSOLE.print("Display only — never modifies config. Exits 1 when there is no config to show.")
        return True

    return False
