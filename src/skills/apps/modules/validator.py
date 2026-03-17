# =================== AIPass ====================
# Name: validator.py
# Description: Skill validation module
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""Skill validator module.

Thin orchestration layer - delegates to validator handler for
checking skill requirements (pip packages, CLI bins, config/env vars).
"""

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from skills.apps.handlers.validator import validate_skill as _handler_validate
from skills.apps.handlers.json import json_handler


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

    if command == "validate":
        if not args:
            error("Error: skill name required. Usage: skills validate <name>")
            return False

        from skills.apps.modules.loader import load_skill

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
    """Check if a skill's requirements are met.

    Delegates to handler for validation logic.

    Args:
        skill_metadata: Dict with 'requires' key containing:
            - pip: list of Python package names
            - bins: list of CLI tool names
            - config: list of env var / config key names

    Returns:
        dict: {
            "valid": bool,
            "missing_pip": list[str],
            "missing_bins": list[str],
            "missing_config": list[str]
        }
    """
    result = _handler_validate(skill_metadata)
    json_handler.log_operation("skill_validated", {
        "valid": result["valid"],
    })
    return result


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("validator Module")
    console.print("Check if a skill's requirements are met (pip packages, CLI bins, config/env vars)")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - validator.py (validate_skill — check pip, bins, and config requirements)")
    console.print()
