# =================== AIPass ====================
# Name: loader.py
# Description: Load SKILL.md and handlers; the info command
# Version: 1.2.0
# Created: 2026-03-07
# Modified: 2026-10-24
# =============================================

"""Skill loader module."""

from aipass.cli.apps.modules import console, error, escape, warning
from aipass.prax import logger
from aipass.skills.apps.modules.discovery import discover_all
from aipass.skills.apps.handlers.loader_handler import load_skill as _handler_load_skill
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
        print_introspection()
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

    logger.info(f"info: loaded skill '{name}'")
    return True


def load_skill(name):
    """Load a skill by name: {success, metadata, body, handler, path, error}."""
    registry = discover_all()
    result = _handler_load_skill(name, registry)

    if not result["success"]:
        logger.warning(f"Failed to load skill: {result['error']}")

    if result["success"] and result["handler"] is None and result["metadata"].get("has_handler", False):
        warning(f"Warning: has_handler is true but handler.py not found at {result['path']}")

    json_handler.log_operation(
        "skill_loaded",
        {
            "name": name,
            "success": result["success"],
        },
    )
    return result


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
