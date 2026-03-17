# =================== AIPass ====================
# Name: runner.py
# Description: Execute skills
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-03-08
# =============================================

"""Skill runner module.

Thin orchestration layer - delegates to runner_handler for executing
skill handlers and assembling markdown output.
"""

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from skills.apps.modules.loader import load_skill
from skills.apps.handlers.runner_handler import run_handler, run_markdown
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

    if command == "run":
        if not args:
            error("Error: skill name required. Usage: skills run <name> [action] [args...]")
            return False

        name = args[0]
        action = args[1] if len(args) > 1 else None
        extra_args = _parse_run_args(args[2:]) if len(args) > 2 else {}

        result = run_skill(name, action=action, args=extra_args)

        if result["success"]:
            if result["output"]:
                for line in result["output"].splitlines():
                    console.print(f"  {line}")
        else:
            err = result.get("error", "Unknown error")
            error(f"Error: {err}")

        return result["success"]

    return False


def _parse_run_args(arg_list):
    """Parse extra arguments into a dict."""
    result = {}
    positional_idx = 0
    for arg in arg_list:
        if "=" in arg:
            key, value = arg.split("=", 1)
            result[key] = value
        else:
            result[f"arg{positional_idx}"] = arg
            positional_idx += 1
    return result


def run_skill(name, action=None, args=None, config=None):
    """Execute a skill by name.

    Args:
        name: The skill name to run.
        action: The action to perform (required for handler-based skills).
        args: Dict of action arguments.
        config: Dict of resolved config values.

    Returns:
        dict: {"success": bool, "output": str, "error": str|None}
    """
    args = args or {}
    config = config or {}

    # Load the skill
    loaded = load_skill(name)
    if not loaded["success"]:
        return {
            "success": False,
            "output": "",
            "error": loaded["error"],
        }

    handler = loaded["handler"]
    metadata = loaded["metadata"]
    body = loaded["body"]

    # Delegate to handler for execution
    if handler is not None:
        result = run_handler(handler, name, action, args, config)
    else:
        result = run_markdown(name, metadata, body)

    json_handler.log_operation("skill_executed", {
        "name": name,
        "success": result["success"],
        "has_handler": handler is not None,
    })
    return result


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("runner Module")
    console.print("Execute skills by name — runs handler-based or markdown-only skills")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - runner_handler.py (run_handler, run_markdown — skill execution and markdown output)")
    console.print()
    console.print("Connected Modules:")
    console.print("  modules/")
    console.print("    - loader.py (load_skill — load skill metadata, body, and handler)")
    console.print()
