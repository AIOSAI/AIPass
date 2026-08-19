# =================== AIPass ====================
# Name: switch.py
# Description: Per-skill off-switch — on, off, and status
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

"""Skill off-switch module.

Thin orchestration layer - delegates to switch_handler for state,
declaration parsing, and systemd actuation. Designed in DPLAN-0306.
"""

from aipass.cli.apps.modules import console, error, warning
from aipass.prax import logger
from aipass.skills.apps.handlers.switch_handler import (
    SwitchStateUnreadable,
    switch_rows,
    turn_off,
    turn_on,
)
from aipass.skills.apps.handlers.json import json_handler


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point.

    Args:
        command: The subcommand to execute (on, off, switch).
        args: List of additional arguments.

    Returns:
        bool: True if the command succeeded.
    """
    if not args:
        print_introspection()
        return True
    if "--help" in args:
        print_introspection()
        return True

    if command == "on":
        if not args:
            error("Error: skill name required. Usage: skills on <name>")
            return False
        return switch_on(args[0])

    if command == "off":
        if not args:
            error("Error: skill name required. Usage: skills off <name> [reason]")
            return False
        reason = " ".join(args[1:]) if len(args) > 1 else None
        return switch_off(args[0], reason)

    if command == "switch":
        return show_switch(args[0] if args else None)

    return False


def switch_on(name: str) -> bool:
    """Switch a skill on and start its declared processes.

    Args:
        name: Skill to switch on.

    Returns:
        bool: True when the skill is on and every declared unit is running.
    """
    result = turn_on(name)
    _report(result)
    logger.info("switch: turned '%s' on (success=%s)", name, result["success"])
    json_handler.log_operation("switch_on", {"skill": name, "success": result["success"]})
    return result["success"]


def switch_off(name: str, reason: str | None = None) -> bool:
    """Switch a skill off and stop its declared processes.

    Args:
        name: Skill to switch off.
        reason: Optional note kept with the recorded state.

    Returns:
        bool: True when the skill is off and no declared unit is running.
    """
    result = turn_off(name, reason=reason)
    _report(result)
    logger.info("switch: turned '%s' off (success=%s)", name, result["success"])
    json_handler.log_operation("switch_off", {"skill": name, "success": result["success"]})
    return result["success"]


def show_switch(name: str | None = None) -> bool:
    """Display the on/off state of every skill, or one skill.

    Args:
        name: Optional single skill to report.

    Returns:
        bool: True when the state could be read.
    """
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
        console.print(f"  {mark}  {row['name']}")
        if row["units"]:
            console.print(f"        units: {', '.join(row['units'])}")
        if row["reason"]:
            console.print(f"        reason: {row['reason']}")
        if row["live_units"]:
            # State says dark, machine says alive. Never collapse this into the
            # state's own claim — the discrepancy is the reason to look.
            warning(f"        STILL RUNNING: {', '.join(row['live_units'])}")
    console.print()
    return True


def _report(result: dict) -> None:
    """Print a handler result, routing failures to stderr.

    Args:
        result: {"success": bool, "output": str, "error": str|None}
    """
    if result["output"]:
        for line in result["output"].splitlines():
            console.print(f"  {line}")
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
