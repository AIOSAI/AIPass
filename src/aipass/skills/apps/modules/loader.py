# =================== AIPass ====================
# Name: loader.py
# Description: Load SKILL.md and handlers; the info command
# Version: 1.3.1
# Created: 2026-03-07
# Modified: 2026-11-17
# =============================================

"""Skill loader module."""

from aipass.cli import console, error, escape, warning
from aipass.prax import logger
from aipass.skills.apps.modules.discovery import discover_all
from aipass.skills.apps.handlers.loader_handler import load_skill as _handler_load_skill
from aipass.skills.apps.handlers.switch_handler import SwitchStateUnreadable, is_enabled
from aipass.skills.apps.handlers.json import json_handler


def handle_command(command: str, args: list) -> bool:
    """Handle the info command routed by the entry point."""
    if command != "info":
        return False
    if not args:
        print_introspection()
        error("Error: skill name required. Usage: skills info <name>")
        return False
    if any(arg in ("--help", "-h", "help") for arg in args):
        print_info_help()
        return True
    return print_skill_info(args[0])


def print_skill_info(name):
    """Print a skill's metadata and SKILL.md body; False when it cannot be loaded."""
    loaded = load_skill(name)
    if not loaded["success"]:
        error(f"Error: {loaded['error']}")
        return False

    metadata = loaded["metadata"]
    # SKILL.md text is the author's, not ours: escaped so Rich prints its brackets.
    console.print(f"  Skill: {escape(str(metadata.get('name', name)))}")
    console.print(f"  Version: {escape(str(metadata.get('version', 'unknown')))}")
    console.print(f"  Description: {escape(str(metadata.get('description', 'No description')))}")
    console.print(f"  Path: {escape(str(loaded['path']))}")
    console.print(f"  Has Handler: {metadata.get('has_handler', False)}")
    off = loaded["off"]
    if off is not None:
        console.print("  Handler: not imported while the skill is OFF")

    tags = metadata.get("tags") or []
    if tags:
        console.print(f"  Tags: {escape(', '.join(map(str, tags)))}")

    requires = metadata.get("requires") or {}
    if isinstance(requires, dict):
        for key in ("pip", "bins", "config"):
            values = requires.get(key) or []
            if values:
                console.print(f"  Requires {key}: {escape(', '.join(map(str, values)))}")

    if loaded["body"]:
        console.print()
        console.print("  --- SKILL.md Body ---")
        for line in loaded["body"].splitlines():
            console.print(f"  {line}", markup=False)

    if off is not None:
        # An unreadable switch is a fault to fix; a skill switched off on purpose is not.
        (error if off["unreadable"] else warning)(off["notice"])
        return not off["unreadable"]

    logger.info(f"info: loaded skill '{name}'")
    return True


def load_skill(name):
    """Load a skill by name: {success, metadata, body, handler, path, error, off}.

    off is None for an ON skill. For an OFF skill, or an unreadable switch state, it is
    {notice, unreadable} and handler.py is never imported: off means no skill code runs."""
    off = _switch_notice(name)
    registry = discover_all()
    result = _handler_load_skill(name, registry, import_code=off is None)
    result["off"] = off

    if not result["success"]:
        logger.warning(f"Failed to load skill: {result['error']}")

    if result["success"] and off is None and result["handler"] is None and result["metadata"].get("has_handler"):
        warning(f"Warning: has_handler is true but handler.py not found at {result['path']}")

    json_handler.log_operation(
        "skill_loaded",
        {
            "name": name,
            "success": result["success"],
        },
    )
    return result


def _switch_notice(name):
    """None while the skill is on; else {notice, unreadable}. An unreadable state counts as off, as in the runner."""
    try:
        if is_enabled(name):
            return None
    except SwitchStateUnreadable as exc:
        logger.error("Treating '%s' as OFF - switch state unreadable: %s", name, exc)
        return {"notice": str(exc), "unreadable": True}
    logger.info("Not importing '%s' - the skill is switched off", name)
    return {
        "notice": f"Skill '{name}' is switched OFF. Turn it back on with: drone @skills on {name}",
        "unreadable": False,
    }


def print_info_help():
    """Print the usage page for this verb."""
    console.print("Skills Info - Show one skill")
    console.print()
    console.print("Usage:")
    console.print("  drone @skills info <name>    Print a skill's metadata and SKILL.md body")


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]loader Module[/bold cyan]")
    console.print("[dim]Load SKILL.md metadata, body, and optional handler module by name[/dim]")
    console.print()
    console.print("[bold]Connected Handlers:[/bold]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print(
        "    [dim]- loader_handler.py (load_skill, import_handler — skill loading and dynamic handler import)[/dim]"
    )
    console.print()
    console.print("[bold]Connected Modules:[/bold]")
    console.print("  [cyan]modules/[/cyan]")
    console.print("    [dim]- discovery.py (discover_all — skill registry for name lookup)[/dim]")
    console.print()
