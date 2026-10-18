# =================== AIPass ====================
# Name: loader.py
# Description: Load SKILL.md and handlers
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""Skill loader module."""

from aipass.cli.apps.modules import console, warning
from aipass.prax import logger
from aipass.skills.apps.modules.discovery import discover_all
from aipass.skills.apps.handlers.loader_handler import load_skill as _handler_load_skill
from aipass.skills.apps.handlers.json import json_handler


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point; loader is a service module with no CLI commands."""
    if not args:
        print_introspection()
        return True
    if "--help" in args:
        print_introspection()
        return True

    return False


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
        "    [dim]- loader_handler.py (load_skill, parse_full_skill_md, import_handler"
        " — skill loading and dynamic handler import)[/dim]"
    )
    console.print()
    console.print("[bold]Connected Modules:[/bold]")
    console.print("  [cyan]modules/[/cyan]")
    console.print("    [dim]- discovery.py (discover_all — skill registry for name lookup)[/dim]")
    console.print()
