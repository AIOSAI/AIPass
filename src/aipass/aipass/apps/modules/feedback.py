# =================== AIPass ====================
# Name: feedback.py
# Description: aipass feedback — toggle the feedback reminder pulse on/off
# Version: 1.0.0
# Created: 2026-07-18
# Modified: 2026-07-18
# =============================================

"""
aipass feedback — user-facing alias for the @hooks feedback toggle.

Usage:
    aipass feedback          # show current state
    aipass feedback on       # enable feedback reminders
    aipass feedback off      # disable feedback reminders
    aipass feedback --help
"""

from __future__ import annotations

import subprocess

from aipass.cli.apps.modules import console, error, warning
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler

COMMAND = "feedback"

_DRONE_TIMEOUT = 15


def _run_hooks_feedback(action: str | None) -> int:
    """Delegate to drone @hooks feedback. Returns the subprocess exit code."""
    cmd = ["drone", "@hooks", "feedback"]
    if action:
        cmd.append(action)
    try:
        proc = subprocess.run(cmd, timeout=_DRONE_TIMEOUT)
        return proc.returncode
    except FileNotFoundError:
        logger.warning("[feedback] drone not found on PATH")
        warning("drone not found on PATH — cannot reach @hooks.")
        return 1
    except subprocess.TimeoutExpired:
        logger.warning("[feedback] drone @hooks feedback timed out")
        warning("drone @hooks feedback timed out.")
        return 1


def print_help() -> None:
    """Print usage help for the feedback command."""
    console.print()
    console.print("[bold cyan]aipass feedback[/bold cyan] — toggle the feedback reminder")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass feedback[/green]       [dim]# show current state[/dim]")
    console.print("  [green]aipass feedback on[/green]    [dim]# enable feedback reminders[/dim]")
    console.print("  [green]aipass feedback off[/green]   [dim]# disable feedback reminders[/dim]")
    console.print()
    console.print("[dim]Delegates to: drone @hooks feedback[/dim]")
    console.print()


def print_introspection() -> None:
    """Show module info for feedback."""
    console.print()
    console.print("[bold cyan]feedback Module[/bold cyan]")
    console.print("User-facing alias for the @hooks feedback pulse toggle.")
    console.print()
    console.print("[dim]Delegates to: drone @hooks feedback on/off[/dim]")
    console.print()


def handle_command(command: str, args: list[str]) -> bool:
    """Route the feedback command. Returns True if handled."""
    if command != COMMAND:
        return False

    if wants_help(args):
        json_handler.log_operation("feedback_help", {"command": command})
        print_help()
        return True
    if args and args[0] in ("--info", "info"):
        json_handler.log_operation("feedback_info", {"command": command})
        print_introspection()
        return True

    if not args:
        json_handler.log_operation("feedback_usage", {"command": command})
        print_introspection()
        return True

    action = args[0] if args[0] in ("on", "off") else None
    if action is None:
        error(f"Unknown option: {args[0]}. Use 'on' or 'off'.")
        print_help()
        return True

    rc = _run_hooks_feedback(action)
    json_handler.log_operation(
        "feedback_toggle",
        {"action": action or "status", "exit": rc},
    )
    if rc != 0:
        logger.warning("[feedback] drone @hooks feedback exited %d", rc)
    return True
