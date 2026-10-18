# =================== AIPass ====================
# Name: validator.py
# Description: Skill validation module
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""Skill validator module."""

from aipass.prax import logger  # noqa: F401
from aipass.cli.apps.modules import console, error
from aipass.skills.apps.handlers.validator import validate_skill as _handler_validate
from aipass.skills.apps.handlers.json import json_handler


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point."""
    if not args:
        print_introspection()
        return True
    if "--help" in args:
        print_introspection()
        return True

    if command == "validate":
        if not args:
            error("Error: skill name required. Usage: skills validate <name>")
            return False

        from aipass.skills.apps.modules.loader import load_skill

        name = args[0]
        loaded = load_skill(name)
        if not loaded["success"]:
            error(f"Error: {loaded['error']}")
            return False

        result = validate_skill(loaded["metadata"])

        if result["valid"]:
            console.print(f"  Skill '{name}' - all requirements met.")
        else:
            console.print(f"  Skill '{name}' - requirements NOT met:")
            if result["missing_pip"]:
                console.print(f"    Missing pip packages: {', '.join(result['missing_pip'])}")
            if result["missing_bins"]:
                console.print(f"    Missing CLI tools: {', '.join(result['missing_bins'])}")
            if result["missing_config"]:
                console.print(f"    Missing config/env: {', '.join(result['missing_config'])}")

        return result["valid"]

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
