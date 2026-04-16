# =================== AIPass ====================
# Name: commands.py
# Description: Module orchestrator for custom command shortcuts
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""Module orchestrator for custom command shortcuts.

Thin orchestrator that delegates to the command_registry handler package
for all CRUD and lookup operations on user-defined command aliases.
"""

from __future__ import annotations

from typing import Any

from aipass.prax import logger
from aipass.cli.apps.modules import console
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.command_registry.ops import (
    add_command as _add_command,
    remove_command as _remove_command,
)
from aipass.drone.apps.handlers.command_registry.lookup import (
    list_commands as _list_commands,
    list_commands_by_branch as _list_commands_by_branch,
    lookup_command as _lookup_command,
    match_command as _match_command,
)
from aipass.drone.apps.handlers.command_registry.formatters import (
    format_activation_results,
    format_command_list,
    format_removal,
)

__all__ = [
    "add",
    "format_activation_results",
    "format_command_list",
    "format_removal",
    "handle_command",
    "list_all",
    "lookup",
    "match",
    "print_help",
    "print_introspection",
    "remove",
]


# ---------------------------------------------------------------------------
# Standard module interface
# ---------------------------------------------------------------------------


def handle_command(command: str | None = None, args: list[str] | None = None) -> bool:
    """Route commands subcommands to handler functions.

    Args:
        command: The subcommand string (e.g. ``"add"``, ``"remove"``, ``"list"``).
        args: List of arguments for the subcommand.

    Returns:
        True if the command succeeded, False otherwise.
    """
    if not args:
        if command is None:
            print_introspection()
            return True
        args = []
    if command in ("--help", "-h") or (args and args[0] in ("--help", "-h")):
        print_help()
        return True

    json_handler.log_operation("handle_command", {"module": "commands", "command": command})

    if command == "add":
        if len(args) < 3:
            logger.warning("commands add requires: <name> <target> <command> [args...] [--desc=...] [--branch=...]")
            return False
        name = args[0]
        target = args[1]
        cmd = args[2]
        extra = args[3:]

        # Extract optional --desc= and --branch= flags
        description = ""
        source_branch = ""
        cmd_args: list[str] = []
        for arg in extra:
            if arg.startswith("--desc="):
                description = arg[len("--desc=") :]
            elif arg.startswith("--branch="):
                source_branch = arg[len("--branch=") :]
            else:
                cmd_args.append(arg)

        return add(name, target, cmd, cmd_args, description, source_branch)

    if command == "remove":
        if not args:
            logger.warning("commands remove requires a command name")
            return False
        return remove(args[0])

    if command == "list":
        branch_filter = args[0] if args else None
        if branch_filter:
            cmds = _list_commands_by_branch(branch_filter)
        else:
            cmds = list_all()
        for cmd_entry in cmds:
            console.print(
                "  %s -> %s %s %s"
                % (
                    cmd_entry.get("name", "?"),
                    cmd_entry.get("target", "?"),
                    cmd_entry.get("command", "?"),
                    " ".join(cmd_entry.get("args", [])),
                )
            )
        if not cmds:
            console.print("  (no commands registered)")
        return True

    if command == "lookup":
        if not args:
            logger.warning("commands lookup requires a command name")
            return False
        result = lookup(args[0])
        if result:
            console.print(
                "  %s -> %s %s %s"
                % (result["name"], result["target"], result["command"], " ".join(result.get("args", [])))
            )
        else:
            logger.warning("  Command '%s' not found", args[0])
            return False
        return True

    logger.warning("commands: unknown subcommand '%s'", command)
    return False


def print_introspection() -> None:
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        logger.warning("CLI console not available, using fallback")
        from rich.console import Console

        console = Console()

    console.print()
    console.print("commands Module")
    console.print("Custom command shortcuts — map short names to full drone commands.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/command_registry/")
    console.print("    - ops.py (add_command, remove_command, update_command, command_exists)")
    console.print("    - lookup.py (lookup_command, match_command, list_commands, list_commands_by_branch)")
    console.print()


def print_help() -> None:
    """Print help for the commands module."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        logger.warning("CLI console not available, using fallback")
        from rich.console import Console

        console = Console()

    console.print("commands -- Custom command shortcuts")
    console.print()
    console.print("Commands:")
    console.print("  add <name> <target> <cmd> [args...] [--desc=...] [--branch=...]")
    console.print("  remove <name>                        Remove a custom command")
    console.print("  list [branch]                        List commands (optionally by branch)")
    console.print("  lookup <name>                        Look up a command by name")


# ---------------------------------------------------------------------------
# Delegated operations
# ---------------------------------------------------------------------------


def add(
    name: str,
    target: str,
    command: str,
    args: list[str] | None = None,
    description: str = "",
    source_branch: str = "",
) -> bool:
    """Add a custom command shortcut.

    Args:
        name: Shortcut name.
        target: Target branch (e.g. ``"@seedgo"``).
        command: Command to run on the target.
        args: Extra arguments.
        description: Human-readable description.
        source_branch: Originating branch name.

    Returns:
        True if added successfully.
    """
    return _add_command(name, target, command, args, description, source_branch)


def remove(name: str) -> bool:
    """Remove a custom command shortcut.

    Args:
        name: Shortcut name to remove.

    Returns:
        True if removed successfully.
    """
    return _remove_command(name)


def list_all() -> list[dict[str, Any]]:
    """List all registered custom commands sorted by name.

    Returns:
        List of command dicts.
    """
    return _list_commands()


def lookup(name: str) -> dict[str, Any] | None:
    """Look up a custom command by exact name.

    Args:
        name: Shortcut name.

    Returns:
        Command dict if found, None otherwise.
    """
    return _lookup_command(name)


def match(args: list[str]) -> tuple[dict[str, Any], list[str]] | None:
    """Match user input to a registered command using greedy multi-word matching.

    Args:
        args: Whitespace-split user input tokens.

    Returns:
        Tuple of (command_dict, remaining_args) on match, None otherwise.
    """
    return _match_command(args)
