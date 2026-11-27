# =================== AIPass ====================
# Name: switch.py
# Description: Per-skill off-switch — on, off, and status
# Version: 1.4.0
# Created: 2026-08-18
# Modified: 2026-11-26
# =============================================

"""Skill off-switch module."""

from aipass.cli import console, error, escape, warning
from aipass.prax import logger
from aipass.skills.apps.handlers.switch_handler import (
    SwitchStateUnreadable,
    read_state as read_state,
    switch_rows,
    turn_off,
    turn_on,
)
from aipass.skills.apps.handlers.json import json_handler
from aipass.skills.apps.handlers.registry import get_skill
from aipass.skills.apps.modules.discovery import discover_all


def handle_command(command: str, args: list) -> bool:
    """Handle on, off and switch routed by the entry point."""
    if command not in ("on", "off", "switch"):
        return False
    if not args:
        # Bare `switch` is the status of every skill; bare on/off is missing its skill name.
        if command == "switch":
            return show_switch(None)
        print_introspection()
        error(f"Error: skill name required. Usage: skills {command} <name>")
        return False

    # on/off record their argument, so a help flag read as a skill name would be written to the state.
    if any(arg in ("--help", "-h", "help") for arg in args):
        print_help()
        return True

    if command == "switch":
        return show_switch(args[0])

    # on/off write whatever name they are given, so a typo would record a skill that does not exist.
    if get_skill(args[0], discover_all()) is None:
        error(f"Error: unknown skill '{args[0]}'. See every skill this machine can see: drone @skills list")
        return False

    if command == "on":
        return switch_on(args[0])

    reason = " ".join(args[1:]) if len(args) > 1 else None
    return switch_off(args[0], reason)


def print_help():
    """Print the usage page for on, off and switch."""
    console.print("[bold cyan]skills Switch[/bold cyan] - Disconnect and reconnect a skill")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print("  drone @skills off <name> \\[reason]    Switch a skill off, stop its processes")
    console.print("  drone @skills on <name>              Switch a skill on, start its processes")
    console.print("  drone @skills switch \\[name]          Show each skill's on/off state")
    console.print()
    console.print("[yellow]Examples:[/yellow]")
    console.print('  [green]drone @skills off screen_lock "not on this host"[/green]')
    console.print("  [green]drone @skills on screen_lock[/green]")


def switch_on(name: str) -> bool:
    """Switch a skill on and start its declared processes; True only when every unit runs."""
    try:
        result = turn_on(name)
    except SwitchStateUnreadable as exc:
        return _refuse("on", exc)
    _report(result)
    logger.info("switch: turned '%s' on (success=%s)", name, result["success"])
    json_handler.log_operation("switch_on", {"skill": name, "success": result["success"]})
    return result["success"]


def switch_off(name: str, reason: str | None = None) -> bool:
    """Switch a skill off and stop its declared processes; True only when no unit runs."""
    try:
        result = turn_off(name, reason=reason)
    except SwitchStateUnreadable as exc:
        return _refuse("off", exc)
    _report(result)
    logger.info("switch: turned '%s' off (success=%s)", name, result["success"])
    json_handler.log_operation("switch_off", {"skill": name, "success": result["success"]})
    return result["success"]


def show_switch(name: str | None = None) -> bool:
    """Display the on/off state of every skill, or one skill."""
    try:
        rows = switch_rows()
    except SwitchStateUnreadable as exc:
        logger.error("Cannot report switch state: %s", exc)
        error(f"Error: {exc}")
        return False

    if name:
        rows = [row for row in rows if row["name"] == name]
        if not rows:
            error(f"Error: skill '{name}' not found")
            return False

    console.print()
    for row in rows:
        mark = "[green]ON [/green]" if row["enabled"] else "[red]OFF[/red]"
        console.print(f"  {mark}  {escape(row['name'])}")
        if row["units"]:
            console.print(f"        units: {escape(', '.join(row['units']))}")
        if row["reason"]:
            console.print(f"        reason: {escape(str(row['reason']))}")
        if row["live_units"]:
            # Off in state but alive on the machine: show the discrepancy, never hide it.
            warning(f"        STILL RUNNING: {', '.join(row['live_units'])}")
    console.print()
    return True


def _refuse(command: str, exc: SwitchStateUnreadable) -> bool:
    """Surface an unreadable switch state: one ERROR for medic, the fix on stderr, nothing written."""
    logger.error("Refusing '%s': %s", command, exc)
    error(f"Error: {exc}")
    return False


def _report(result: dict) -> None:
    """Print a handler result, routing failures to stderr."""
    if result["output"]:
        for line in result["output"].splitlines():
            console.print(f"  {line}", markup=False)
    if result.get("error"):
        error(f"Error: {result['error']}")


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]switch Module[/bold cyan]")
    console.print("[dim]Per-skill off-switch — disconnect a skill from AIPass, or reconnect it[/dim]")
    console.print()
    console.print("[bold]Connected Handlers:[/bold]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print("    [dim]- switch_handler.py (turn_on, turn_off, switch_rows — state, declaration, systemd)[/dim]")
    console.print()
    console.print("[bold]Commands:[/bold]")
    console.print("  [dim]- skills on <name>            Reconnect a skill and start its processes[/dim]")
    console.print("  [dim]- skills off <name> \\[reason]  Disconnect a skill and stop its processes[/dim]")
    console.print("  [dim]- skills switch \\[name]        Show on/off state[/dim]")
    console.print()
    console.print("[dim]Run 'drone @skills switch --help' for usage information[/dim]")
    console.print()
