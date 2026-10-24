# =================== AIPass ====================
# Name: runner.py
# Description: Execute skills
# Version: 1.3.0
# Created: 2026-03-07
# Modified: 2026-10-24
# =============================================

"""Skill runner module."""

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.skills.apps.modules.loader import load_skill, print_skill_info
from aipass.skills.apps.handlers.runner_handler import run_handler, run_markdown
from aipass.skills.apps.handlers.switch_handler import SwitchStateUnreadable, is_enabled, off_reason
from aipass.skills.apps.handlers.json import json_handler


def handle_command(command: str, args: list) -> bool:
    """Handle the run command routed by the entry point."""
    if command != "run":
        return False
    if not args:
        print_introspection()
        error("Error: skill name required. Usage: skills run <name> [action] [args...]")
        return False
    if args[0] in ("--help", "-h", "help"):
        print_introspection()
        return True

    name = args[0]
    # Flags only: the bare word "help" is a published action (drone_commands), so it runs.
    if any(arg in ("--help", "-h") for arg in args[1:]):
        return print_skill_info(name)

    action = args[1] if len(args) > 1 else None
    result = run_skill(name, action=action, args=_parse_run_args(args[2:]))

    if not result["success"]:
        error(f"Error: {result.get('error', 'Unknown error')}")
        return False

    logger.info(f"run: executed skill '{name}' action={action}")
    # A skill's output is its own text: printed verbatim, never parsed as Rich markup.
    for line in (result["output"] or "").splitlines():
        console.print(f"  {line}", markup=False)
    return True


def _parse_run_args(arg_list):
    """Parse key=value and positional arguments into a dict (positionals as arg0, arg1, ...)."""
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
