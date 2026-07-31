# =================== AIPass ====================
# Name: telegram_standards.py
# Description: Standard command registry, response builders, and helpers for Telegram bots
# Version: 1.0.0
# Created: 2026-02-24
# Modified: 2026-06-29
# =============================================

"""
Telegram Standards — shared command registry and response builders.

Provides the canonical STANDARD_COMMANDS dict, text builder functions for
/start, /help, /status, and /new responses, the BotFather setMyCommands
payload builder, and the parse_command / handle_standard_command dispatcher
used by BaseBot and all subclasses.

All functions are pure (no side effects) except _tmux_session_exists which
calls subprocess to check tmux state.
"""

import subprocess
from typing import Optional

from aipass.skills.apps.handlers.json import json_handler  # noqa: F401
from aipass.prax import logger


# =============================================
# STANDARD COMMAND REGISTRY
# =============================================

STANDARD_COMMANDS: dict[str, dict[str, str]] = {
    "start": {
        "description": "Welcome — what this bot is and how to use it",
        "menu_text": "What this bot does",
    },
    "help": {
        "description": "Show every command and what it does",
        "menu_text": "List commands",
    },
    "new": {
        "description": "Start a fresh conversation (clears Claude's current context)",
        "menu_text": "Fresh session",
    },
    "status": {
        "description": "Show the branch, uptime, and whether a session is active",
        "menu_text": "Session status",
    },
}


# =============================================
# RESPONSE TEMPLATES
# =============================================

PROCESSING_MSG = "Processing..."

ERROR_TEMPLATE = "Something went wrong: {error}"

HELP_FOOTER = "\nJust send any message to talk to me — or use a command above."

# Internal templates (used by builder functions)
_WELCOME_HEADER = "Hello! I'm {bot_name}."
_WELCOME_BRANCH = "Branch: @{branch_name}"

_STATUS_HEADER = "Session Status"


# =============================================
# TEXT BUILDERS
# =============================================


def _format_command_list(
    standard_commands: dict[str, dict[str, str]],
    custom_commands: Optional[dict[str, dict[str, str]]] = None,
) -> str:
    """
    Format a combined command list as readable text.

    Each command appears as: /command - description

    Args:
        standard_commands: The STANDARD_COMMANDS dict (or a subset).
        custom_commands: Optional additional commands in the same format.

    Returns:
        Multi-line string of formatted commands.
    """
    lines: list[str] = []
    for cmd, info in standard_commands.items():
        lines.append(f"/{cmd} - {info['description']}")
    if custom_commands:
        for cmd, info in custom_commands.items():
            lines.append(f"/{cmd} - {info['description']}")
    return "\n".join(lines)


def build_help_text(
    standard_commands: Optional[dict[str, dict[str, str]]] = None,
    custom_commands: Optional[dict[str, dict[str, str]]] = None,
) -> str:
    """
    Build a /help message combining standard and custom commands.

    Args:
        standard_commands: Command registry dict. Defaults to STANDARD_COMMANDS.
        custom_commands: Optional bot-specific commands in the same format.

    Returns:
        Formatted help text string.
    """
    if standard_commands is None:
        standard_commands = STANDARD_COMMANDS

    parts: list[str] = [
        "Available commands:",
        _format_command_list(standard_commands, custom_commands),
        HELP_FOOTER,
    ]
    return "\n".join(parts)


def build_welcome_text(
    bot_name: str,
    branch_name: str,
    standard_commands: Optional[dict[str, dict[str, str]]] = None,
    custom_commands: Optional[dict[str, dict[str, str]]] = None,
) -> str:
    """
    Build the /start welcome message.

    Args:
        bot_name: Display name of the bot (e.g., "AIPass Bridge Bot").
        branch_name: The branch this bot operates on (e.g., "dev_central").
        standard_commands: Command registry dict. Defaults to STANDARD_COMMANDS.
        custom_commands: Optional bot-specific commands in the same format.

    Returns:
        Formatted welcome text string.
    """
    if standard_commands is None:
        standard_commands = STANDARD_COMMANDS

    parts: list[str] = [
        _WELCOME_HEADER.format(bot_name=bot_name),
        _WELCOME_BRANCH.format(branch_name=branch_name),
        "",
        "Available commands:",
        _format_command_list(standard_commands, custom_commands),
        HELP_FOOTER,
    ]
    return "\n".join(parts)


def build_status_text(
    session_name: str,
    branch_name: str,
    uptime: Optional[str] = None,
    message_count: Optional[int] = None,
    chat_id: Optional[str | int] = None,
    daemon_uptime: Optional[str] = None,
) -> str:
    """
    Build the /status response.

    Checks tmux session state via subprocess. Reports branch, session,
    activity status, and optional metrics.

    Args:
        session_name: tmux session name (e.g., "telegram-assistant").
        branch_name: Branch name (e.g., "assistant").
        uptime: Optional conversation uptime (resets on /new).
        message_count: Optional count of messages in current conversation.
        chat_id: Optional Telegram chat ID to display.
        daemon_uptime: Optional daemon process uptime (since boot).

    Returns:
        Formatted status text string.
    """
    active = _tmux_session_exists(session_name)

    lines: list[str] = [_STATUS_HEADER]
    if chat_id is not None:
        lines.append(f"Chat ID: {chat_id}")
    lines.append(f"Branch: @{branch_name}")
    lines.append(f"Session: {session_name}")
    lines.append(f"State: {'Active' if active else 'Inactive'}")
    if uptime:
        lines.append(f"Uptime: {uptime}")
    if message_count is not None:
        lines.append(f"Messages: {message_count}")
    if daemon_uptime:
        lines.append(f"Daemon up: {daemon_uptime}")

    return "\n".join(lines)


def build_botfather_commands(
    standard_commands: Optional[dict[str, dict[str, str]]] = None,
    custom_commands: Optional[dict[str, dict[str, str]]] = None,
) -> list[dict[str, str]]:
    """
    Build command list for BotFather setMyCommands API.

    Returns the format expected by Telegram's setMyCommands endpoint:
    [{"command": "start", "description": "Start / welcome message"}, ...]

    Args:
        standard_commands: Command registry dict. Defaults to STANDARD_COMMANDS.
        custom_commands: Optional bot-specific commands in the same format.

    Returns:
        List of dicts with "command" and "description" keys.
    """
    if standard_commands is None:
        standard_commands = STANDARD_COMMANDS

    result: list[dict[str, str]] = []
    for cmd, info in standard_commands.items():
        result.append({"command": cmd, "description": info["menu_text"]})
    if custom_commands:
        for cmd, info in custom_commands.items():
            result.append({"command": cmd, "description": info["menu_text"]})
    return result


# =============================================
# SYNC BOT UTILITIES (stdlib bots)
# =============================================


def parse_command(text: str) -> Optional[tuple[str, str]]:
    """
    Extract command name and arguments from message text.

    Handles both '/command' and '/command@bot_username' formats.
    Returns None if the text is not a command.

    Args:
        text: Raw message text from Telegram.

    Returns:
        Tuple of (command_name, args_string) or None if not a command.
        command_name is lowercase without the leading slash.
        args_string is everything after the command, stripped.

    Examples:
        parse_command("/status")        -> ("status", "")
        parse_command("/new please")    -> ("new", "please")
        parse_command("/help@mybot")    -> ("help", "")
        parse_command("hello world")    -> None
    """
    if not text or not text.startswith("/"):
        return None

    # Split on whitespace: first part is /command[@botname], rest is args
    parts = text.split(None, 1)
    raw_command = parts[0][1:]  # Remove leading /
    args = parts[1] if len(parts) > 1 else ""

    # Strip @bot_username suffix if present
    if "@" in raw_command:
        raw_command = raw_command.split("@", 1)[0]

    command = raw_command.lower().strip()
    if not command:
        return None

    return (command, args.strip())


def handle_standard_command(
    command: str,
    session_name: str,
    branch_name: str,
    bot_name: str,
    standard_commands: Optional[dict[str, dict[str, str]]] = None,
    custom_commands: Optional[dict[str, dict[str, str]]] = None,
    chat_id: Optional[str | int] = None,
    message_count: Optional[int] = None,
    uptime: Optional[str] = None,
) -> Optional[str | tuple[str, str]]:
    """
    Handle a standard command and return the response text.

    For most commands, returns a string with the response text.
    For /new, returns a tuple ("new", instructions_text) to signal
    the caller that they need to kill and restart their tmux session.
    The caller is responsible for tmux operations and for sending
    the response text.

    Returns None if the command is not a standard command.

    Args:
        command: The command name (lowercase, no slash).
        session_name: tmux session name (e.g., "telegram-assistant").
        branch_name: Branch name (e.g., "assistant").
        bot_name: Display name of the bot.
        standard_commands: Command registry dict. Defaults to STANDARD_COMMANDS.
        custom_commands: Optional bot-specific commands for help text.
        chat_id: Optional Telegram chat ID (for /status display).
        message_count: Optional message count (for /status display).
        uptime: Optional uptime string (for /status display).

    Returns:
        - str: Response text for /start, /help, /status
        - tuple[str, str]: ("new", response_text) for /new command
        - None: Command is not a standard command
    """
    json_handler.log_operation("standard_command", {"command": command, "branch": branch_name})

    if command == "start":
        return build_welcome_text(
            bot_name=bot_name,
            branch_name=branch_name,
            standard_commands=standard_commands,
            custom_commands=custom_commands,
        )

    if command == "help":
        return build_help_text(standard_commands=standard_commands, custom_commands=custom_commands)

    if command == "new":
        response_text = f"Session cleared for @{branch_name}. Next message starts fresh."
        return ("new", response_text)

    if command == "status":
        return build_status_text(
            session_name=session_name,
            branch_name=branch_name,
            uptime=uptime,
            message_count=message_count,
            chat_id=chat_id,
        )

    return None


# =============================================
# INTERNAL HELPERS
# =============================================


def _tmux_session_exists(session_name: str) -> bool:
    """
    Check if a tmux session exists by name.

    Args:
        session_name: The tmux session name to check.

    Returns:
        True if the session is running, False otherwise.
    """
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        logger.warning("tmux not found while checking session '%s'", session_name)
        return False
