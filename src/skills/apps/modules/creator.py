# =================== AIPass ====================
# Name: creator.py
# Description: Scaffold new skills from templates
# Version: 1.2.0
# Created: 2026-03-07
# Modified: 2026-03-08
# =============================================

"""Skill creator module.

Scaffolds new skills from templates into a target location.
Supports three tiers: markdown_only, with_handler, full.

Thin orchestration layer - delegates to creator_handler for logic.
"""

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from skills.apps.handlers.creator_handler import create_skill as _handler_create_skill
from skills.apps.handlers.json import json_handler

try:
    from aipass.trigger.apps.modules.core import trigger
except ImportError:
    trigger = None


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point.

    Args:
        command: The subcommand to execute.
        args: List of additional arguments.

    Returns:
        bool: True if command was handled, False otherwise.
    """
    if not args:
        print_introspection()
        return True

    if command == "create":
        if not args:
            error("Error: skill name required. Usage: skills create <name> [--with-handler|--full]")
            return False

        name = args[0]
        template_type = "markdown_only"
        if "--with-handler" in args:
            template_type = "with_handler"
        elif "--full" in args:
            template_type = "full"

        result = create_skill(name, template_type=template_type)
        return result["success"]

    return False


def create_skill(name, template_type="markdown_only", target_dir=None):
    """Create a new skill from a template.

    Delegates to handler for validation and creation logic,
    then renders results with Rich.

    Args:
        name: Name for the new skill (used as directory name and placeholder).
        template_type: Template tier - "markdown_only", "with_handler", or "full".
        target_dir: Directory to create the skill in. Defaults to
                    .aipass/skills/ in the current working directory.

    Returns:
        dict: {"success": bool, "path": str|None, "files": list[str], "error": str|None}
    """
    result = _handler_create_skill(name, template_type=template_type, target_dir=target_dir)

    if result["success"]:
        if trigger is not None:
            trigger.fire('skill_created', name=name, template_type=template_type, path=result['path'])

        console.print(f"  Created skill '{name}' at {result['path']}")
        console.print(f"  Template: {template_type}")
        console.print(f"  Files: {len(result['files'])}")
        for f in result["files"]:
            console.print(f"    - {f}")

    json_handler.log_operation("skill_created", {
        "name": name,
        "template_type": template_type,
        "success": result["success"],
    })
    return result


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("creator Module")
    console.print("Scaffold new skills from templates into a target location")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - creator_handler.py (create_skill — validate name, resolve template, copy to target)")
    console.print("    - template.py (copy_template, get_template — template resolution and file copy)")
    console.print()
