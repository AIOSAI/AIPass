# =================== AIPass ====================
# Name: interactive_filter.py
# Description: Interactive Command Parser
# Version: 0.2.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""Parse interactive commands for monitor console. No filtering — all events display."""

from typing import List, Tuple, Optional

from aipass.prax.apps.handlers.json import json_handler


def parse_command(cmd: str) -> Tuple[Optional[str], List[str]]:
    """Parse user command into action and arguments.

    Args:
        cmd: Raw command string from user input

    Returns:
        Tuple of (command_name, arguments) or (None, []) for empty input
    """
    if not cmd:
        return None, []

    parts = cmd.strip().split()
    if not parts:
        return None, []

    command = parts[0].lower()
    args = parts[1:] if len(parts) > 1 else []

    json_handler.log_operation("filter_applied", {"command": command, "args": args})

    # Normalize aliases
    if command in ["exit", "q"]:
        command = "quit"

    return command, args


def get_help_text() -> str:
    """Get help text for interactive commands"""
    return """
Available Commands:
  status          - Show monitoring state
  help            - Show this help
  quit/exit       - Stop monitoring
"""
