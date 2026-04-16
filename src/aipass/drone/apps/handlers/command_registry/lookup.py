# =================== AIPass ====================
# Name: lookup.py
# Description: Command lookup and matching for custom command shortcuts
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""Command Lookup and Matching for Custom Commands.

Provides exact-match lookup and greedy multi-word matching so that
user input like ``plan create flow`` resolves to the longest registered
shortcut name (trying 3 words, then 2, then 1).

Usage:
    from aipass.drone.apps.handlers.command_registry.lookup import (
        lookup_command, match_command, list_commands,
    )

    cmd = lookup_command("audit")
    result = match_command(["plan", "create", "flow", "--verbose"])
"""

from __future__ import annotations

from typing import Any

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from .ops import load_registry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODULE_NAME = "command_lookup"


# ---------------------------------------------------------------------------
# Lookup functions
# ---------------------------------------------------------------------------


def lookup_command(name: str) -> dict[str, Any] | None:
    """Look up a custom command by exact name.

    Args:
        name: Shortcut name to look up.

    Returns:
        Command dict if found, None otherwise.
    """
    try:
        registry = load_registry()
        return registry.get("commands", {}).get(name)
    except Exception as exc:
        logger.error("[%s] Failed to look up command '%s': %s", MODULE_NAME, name, exc)
        return None


def match_command(args: list[str]) -> tuple[dict[str, Any], list[str]] | None:
    """Match user input against registered commands using greedy multi-word matching.

    Tries the longest candidate first (up to 4 words), then progressively
    shorter candidates until a match is found.

    For example, given args ``["plan", "create", "flow", "--verbose"]``
    it tries:
    1. ``"plan create flow --verbose"`` (4 words)
    2. ``"plan create flow"`` (3 words)
    3. ``"plan create"`` (2 words)
    4. ``"plan"`` (1 word)

    Args:
        args: List of whitespace-split user input tokens.

    Returns:
        Tuple of (command_dict, remaining_args) on match, None otherwise.
    """
    if not args:
        return None

    try:
        registry = load_registry()
        commands = registry.get("commands", {})
    except Exception as exc:
        logger.error("[%s] Failed to load registry for matching: %s", MODULE_NAME, exc)
        return None

    for i in range(min(len(args), 4), 0, -1):
        candidate = " ".join(args[:i])
        if candidate in commands:
            remaining = args[i:]
            json_handler.log_operation(
                "match_command",
                {"matched": candidate, "remaining_args": remaining},
            )
            return (commands[candidate], remaining)

    return None


def list_commands() -> list[dict[str, Any]]:
    """List all registered custom commands, sorted by name.

    Returns:
        List of command dicts sorted alphabetically by name.
    """
    try:
        registry = load_registry()
        commands = registry.get("commands", {})
        return sorted(commands.values(), key=lambda c: c.get("name", ""))
    except Exception as exc:
        logger.error("[%s] Failed to list commands: %s", MODULE_NAME, exc)
        return []


def list_commands_by_branch(branch_name: str) -> list[dict[str, Any]]:
    """List custom commands filtered by source branch.

    Args:
        branch_name: Branch name to filter by (e.g. ``"seedgo"``).

    Returns:
        List of command dicts whose source_branch matches, sorted by name.
    """
    try:
        registry = load_registry()
        commands = registry.get("commands", {})
        filtered = [cmd for cmd in commands.values() if cmd.get("source_branch") == branch_name]
        return sorted(filtered, key=lambda c: c.get("name", ""))
    except Exception as exc:
        logger.error("[%s] Failed to list commands for branch '%s': %s", MODULE_NAME, branch_name, exc)
        return []
