# =================== AIPass ====================
# Name: loader.py
# Description: Load SKILL.md and handlers
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-03-08
# =============================================

"""Skill loader module.

Thin orchestration layer - delegates to loader_handler for parsing
SKILL.md files and dynamically importing handler modules.
"""

from aipass.cli.apps.modules import console, warning
from aipass.prax import logger
from skills.apps.modules.discovery import discover_all
from skills.apps.handlers.loader_handler import load_skill as _handler_load_skill
from skills.apps.handlers.json import json_handler


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point.

    Loader is a service module used by other modules (runner, validator, etc.).
    It does not handle any direct CLI commands.

    Args:
        command: The subcommand to execute.
        args: List of additional arguments.

    Returns:
        bool: Always False - loader is a service module, not a command handler.
    """
    if not args:
        print_introspection()
        return True

    return False


def load_skill(name):
    """Load a skill by name.

    Discovers all skills, then delegates to handler for loading logic.

    Args:
        name: The skill name to load.

    Returns:
        dict: {
            "success": bool,
            "metadata": dict or None,
            "body": str or None,
            "handler": module or None,
            "path": Path or None,
            "error": str or None
        }
    """
    registry = discover_all()
    result = _handler_load_skill(name, registry)

    if not result["success"]:
        logger.warning(f"Failed to load skill: {result['error']}")

    if result["success"] and result["handler"] is None and result["metadata"].get("has_handler", False):
        warning(f"Warning: has_handler is true but handler.py not found at {result['path']}")

    json_handler.log_operation("skill_loaded", {
        "name": name,
        "success": result["success"],
    })
    return result


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("loader Module")
    console.print("Load SKILL.md metadata, body, and optional handler module by name")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - loader_handler.py (load_skill, parse_full_skill_md, import_handler — skill loading and dynamic handler import)")
    console.print()
    console.print("Connected Modules:")
    console.print("  modules/")
    console.print("    - discovery.py (discover_all — skill registry for name lookup)")
    console.print()
