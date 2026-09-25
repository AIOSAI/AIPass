# =================== AIPass ====================
# Name: bot_operations.py
# Description: Bot lifecycle operation handlers — start, stop, status, list
# Version: 1.0.1
# Created: 2026-02-24
# Modified: 2026-06-29
# =============================================

"""
Bot Operation Handlers for Multi-Bot Architecture

Implementation logic for bot lifecycle operations:
- start_bot: load config and run polling loop
- stop_bot: stop systemd service
- get_status: query registry for bot status
- get_all_bots: list all registered bots
- format_bot_details: format a bot entry for display

Called by the telegram_bot module (thin orchestration layer).
All functions return values - the module layer handles logging and display.
"""

# Standard library
import subprocess
from pathlib import Path

# Logging
from aipass.prax import logger

# JSON handler (seedgo standard)
from aipass.skills.apps.handlers.json import json_handler

# Internal handler imports
from .base_bot import BaseBot
from .branch_plugin import BranchPlugin
from .bot_registry import list_bots, get_bot
from .config import load_bot_config

# =============================================
# BOT OPERATIONS
# =============================================


def start_bot(bot_id: str) -> int | None:
    """
    Load config and start a bot's polling loop.

    Loads config via the in-process @api secrets API.
    If config has "branch_name", creates a BranchPlugin, else a BaseBot.
    Calls bot.run() which blocks until terminated.

    Args:
        bot_id: Bot identifier to start

    Returns:
        Bot exit code, or None if config loading failed.
    """
    json_handler.log_operation("start_bot", {"bot_id": bot_id})
    config = load_bot_config(bot_id)
    if not config:
        return None

    bot_token = config.get("bot_token")
    if not bot_token:
        return None

    work_dir = Path(config.get("work_dir", str(Path.home())))
    bot_name = config.get("bot_name", f"AIPass {bot_id} Bot")
    allowed_user_ids = config.get("allowed_user_ids", [])
    branch_name = config.get("branch_name")
    shared_session = config.get("shared_session")
    attach_only = config.get("attach_only", False)
    chat_id = config.get("chat_id")

    if branch_name:
        bot = BranchPlugin(
            branch_name=branch_name,
            bot_id=bot_id,
            bot_token=bot_token,
            work_dir=work_dir,
            bot_name=bot_name,
            allowed_user_ids=allowed_user_ids,
            shared_session=shared_session,
            attach_only=attach_only,
        )
    else:
        bot = BaseBot(
            bot_id=bot_id,
            bot_token=bot_token,
            work_dir=work_dir,
            bot_name=bot_name,
            allowed_user_ids=allowed_user_ids,
            shared_session=shared_session,
            attach_only=attach_only,
        )

    if chat_id is not None:
        bot._config_chat_id = chat_id

    return bot.run()


def stop_bot(bot_id: str) -> tuple[bool, str]:
    """
    Stop a bot's systemd service.

    Args:
        bot_id: Bot identifier to stop

    Returns:
        Tuple of (success, message).
    """
    service_name = f"telegram-bot@{bot_id}"

    try:
        result = subprocess.run(
            ["systemctl", "--user", "stop", service_name],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            return True, f"Stopped {service_name}"

        return False, f"Failed to stop {service_name}: {result.stderr.strip()}"

    except subprocess.TimeoutExpired:
        logger.warning("Timeout stopping %s", service_name)
        return False, f"Timeout stopping {service_name}"
    except OSError as e:
        logger.warning("Error stopping %s: %s", service_name, e)
        return False, f"Error stopping {service_name}: {e}"


def get_status(bot_id: str | None = None) -> list[dict]:
    """
    Get bot status entries. If no bot_id, returns all bots.

    Args:
        bot_id: Specific bot to check, or None for all bots

    Returns:
        List of bot entry dicts. Empty list if not found.
    """
    if bot_id:
        bot = get_bot(bot_id)
        return [bot] if bot else []

    return list_bots()


def get_all_bots() -> list[dict]:
    """
    Get all registered bots.

    Returns:
        List of bot entry dicts.
    """
    return list_bots()


def format_bot_details(bot: dict) -> list[str]:
    """
    Format a single bot entry into display lines.

    Args:
        bot: Bot entry dict from registry.

    Returns:
        List of formatted strings for display.
    """
    bot_id = bot.get("bot_id", "?")
    username = bot.get("username", "?")
    branch = bot.get("branch_name") or "none (base bot)"
    work_dir = bot.get("work_dir", "?")
    status = bot.get("status", "?")
    service = bot.get("service_name", f"telegram-bot@{bot_id}")

    return [
        f"Bot ID:      {bot_id}",
        f"Username:    @{username}",
        f"Branch:      {branch}",
        f"Work Dir:    {work_dir}",
        f"Status:      {status}",
        f"Service:     {service}",
    ]


def format_bot_table(bots: list[dict]) -> list[str]:
    """
    Format a list of bots into table rows.

    Args:
        bots: List of bot entry dicts.

    Returns:
        List of formatted strings (header + separator + rows + total).
    """
    lines = []
    lines.append(f"  {'Bot ID':<18} {'Branch':<16} {'Username':<24} {'Status':<10}")
    lines.append(f"  {'---' * 6:<18} {'---' * 5:<16} {'---' * 8:<24} {'---' * 3:<10}")

    for bot in bots:
        bot_id = bot.get("bot_id", "?")
        branch = bot.get("branch_name") or "-"
        username = f"@{bot.get('username', '?')}"
        status = bot.get("status", "?")
        lines.append(f"  {bot_id:<18} {branch:<16} {username:<24} {status}")

    lines.append(f"  Total: {len(bots)} bot(s)")
    return lines


def parse_create_args(args: list) -> dict | None:
    """
    Parse create command arguments.

    Args:
        args: Arguments after 'create' (bot_id, token, [--branch name], [--work-dir path])

    Returns:
        Dict with parsed values, or None if args are insufficient.
    """
    if len(args) < 2:
        return None

    result = {
        "bot_id": args[0],
        "bot_token": args[1],
        "branch_name": None,
        "work_dir": None,
    }

    i = 2
    while i < len(args):
        if args[i] == "--branch" and i + 1 < len(args):
            result["branch_name"] = args[i + 1]
            i += 2
        elif args[i] == "--work-dir" and i + 1 < len(args):
            result["work_dir"] = args[i + 1]
            i += 2
        else:
            i += 1

    return result
