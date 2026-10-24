# =================== AIPass ====================
# Name: validator.py
# Description: Skill validation module
# Version: 1.1.0
# Created: 2026-03-08
# Modified: 2026-10-24
# =============================================

"""Skill validator module."""

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, escape
from aipass.skills.apps.modules.loader import load_skill
from aipass.skills.apps.handlers.validator import validate_skill as _handler_validate
from aipass.skills.apps.handlers.json import json_handler


def handle_command(command: str, args: list) -> bool:
    """Handle the validate command routed by the entry point."""
    if command != "validate":
        return False
    if not args:
        print_introspection()
        error("Error: skill name required. Usage: skills validate <name>")
        return False
    if any(arg in ("--help", "-h", "help") for arg in args):
        print_introspection()
        return True

    name = args[0]
    loaded = load_skill(name)
    if not loaded["success"]:
        error(f"Error: {loaded['error']}")
        return False

    result = validate_skill(loaded["metadata"])
    shown = escape(name)
    if result["valid"]:
        logger.info(f"validate: skill '{name}' passed all requirements")
        console.print(f"  Skill '{shown}' - all requirements met.")
        return True

    console.print(f"  Skill '{shown}' - requirements NOT met:")
    if result.get("malformed"):
        console.print(f"    {escape(result['malformed'])}")
    for key, label in (
        ("missing_pip", "pip packages"),
        ("missing_bins", "CLI tools"),
        ("missing_config", "config/env"),
    ):
        if result[key]:
            console.print(f"    Missing {label}: {escape(', '.join(map(str, result[key])))}")
    return False


def validate_skill(skill_metadata):
    """Check a skill's requires {pip, bins, config}: {valid, missing_pip, missing_bins, missing_config}."""
    result = _handler_validate(skill_metadata)
    json_handler.log_operation(
        "skill_validated",
        {
            "valid": result["valid"],
        },
    )
    return result


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]validator Module[/bold cyan]")
    console.print("[dim]Check if a skill's requirements are met (pip packages, CLI bins, config/env vars)[/dim]")
    console.print()
    console.print("[bold]Connected Handlers:[/bold]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print("    [dim]- validator.py (validate_skill — check pip, bins, and config requirements)[/dim]")
    console.print()
