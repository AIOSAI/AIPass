# =================== AIPass ====================
# Name: lookup.py
# Description: Command lookup and matching for custom command shortcuts
# Version: 1.0.3
# Created: 2026-03-17
# Modified: 2026-10-24
# =============================================

"""Command Lookup and Matching for Custom Commands."""

from __future__ import annotations

from typing import Any

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from .ops import load_registry

MODULE_NAME = "command_lookup"


def lookup_command(name: str) -> dict[str, Any] | None:
    """Look up a custom command by exact name."""
    try:
        registry = load_registry()
        return registry.get("commands", {}).get(name)
    except Exception as exc:
        logger.error("[%s] Failed to look up command '%s': %s", MODULE_NAME, name, exc)
        return None


def match_command(args: list[str]) -> tuple[dict[str, Any], list[str]] | None:
    """Match user input against registered commands using greedy multi-word matching.

    Longest candidate first, up to 4 words; returns (command_dict, remaining_args) or None.
    The hit's operation log is telemetry: a raising write is a warning and the matched command runs.
    Raises only what ``load_registry`` raises: a registry that cannot load is never "no match".
    """
    if not args:
        return None

    try:
        registry = load_registry()
        commands = registry.get("commands", {})
    except Exception as exc:
        logger.error("[%s] Failed to load registry for matching: %s", MODULE_NAME, exc)
        raise

    for i in range(min(len(args), 4), 0, -1):
        candidate = " ".join(args[:i])
        if candidate in commands:
            remaining = args[i:]
            try:
                json_handler.log_operation(
                    "match_command",
                    {"matched": candidate, "remaining_args": remaining},
                )
            except Exception as exc:
                logger.warning("[%s] match log for '%s' not written: %s", MODULE_NAME, candidate, exc)
            return (commands[candidate], remaining)

    return None


def list_commands() -> list[dict[str, Any]]:
    """List all registered custom commands, sorted by name; raises what ``load_registry`` raises."""
    commands = load_registry().get("commands", {})
    return sorted(commands.values(), key=lambda c: c.get("name", ""))


def list_commands_by_branch(branch_name: str) -> list[dict[str, Any]]:
    """List commands whose ``source_branch`` is exactly *branch_name* (bare, no @); raises as load_registry."""
    commands = load_registry().get("commands", {})
    filtered = [cmd for cmd in commands.values() if cmd.get("source_branch") == branch_name]
    return sorted(filtered, key=lambda c: c.get("name", ""))
