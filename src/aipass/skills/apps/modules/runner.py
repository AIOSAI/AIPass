# =================== AIPass ====================
# Name: runner.py
# Description: Execute skills
# Version: 1.2.1
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""Skill runner module."""

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.skills.apps.modules.loader import load_skill
from aipass.skills.apps.handlers.runner_handler import run_handler, run_markdown
from aipass.skills.apps.handlers.switch_handler import SwitchStateUnreadable, is_enabled, off_reason
from aipass.skills.apps.handlers.json import json_handler


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point."""
    if not args:
        print_introspection()
        return True
    if "--help" in args:
        print_introspection()
        return True

    if command == "run":
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
    """Execute a skill by name: {success, output, error}."""
    args = args or {}
    config = config or {}

    # This path runs skill code in-process, bypassing systemd, so the off-switch
    # gates here too — before load_skill, which imports the skill's handler.
    try:
        if not is_enabled(name):
            reason = off_reason(name)
            why = f" ({reason})" if reason else ""
            return {
                "success": False,
                "output": "",
                "error": (
                    f"Skill '{name}' is switched OFF and will not run{why}. "
                    f"Turn it back on with: drone @skills on {name}"
                ),
            }
    except SwitchStateUnreadable as exc:
        # Fail closed: treating unreadable state as "on" would run switched-off skills.
        logger.error("Refusing to run '%s' — switch state unreadable: %s", name, exc)
        return {"success": False, "output": "", "error": str(exc)}

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

    if handler is not None:
        result = run_handler(handler, name, action, args, config)
    else:
        result = run_markdown(name, metadata, body)

    json_handler.log_operation(
        "skill_executed",
        {
            "name": name,
            "success": result["success"],
            "has_handler": handler is not None,
        },
    )
    return result


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]runner Module[/bold cyan]")
    console.print("[dim]Execute skills by name — runs handler-based or markdown-only skills[/dim]")
    console.print()
    console.print("[bold]Connected Handlers:[/bold]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print(
        "    [dim]- runner_handler.py (run_handler, run_markdown — skill execution and markdown output)[/dim]"
    )
    console.print()
    console.print("[bold]Connected Modules:[/bold]")
    console.print("  [cyan]modules/[/cyan]")
    console.print("    [dim]- loader.py (load_skill — load skill metadata, body, and handler)[/dim]")
    console.print()
