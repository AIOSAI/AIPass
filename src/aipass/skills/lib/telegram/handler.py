# =================== AIPass ====================
# Name: handler.py
# Description: Telegram skill entry point — routes actions to multi-bot framework
# Version: 1.1.0
# Created: 2026-06-15
# Modified: 2026-06-15
# =============================================

"""
telegram — Full 3-layer skill handler.

Routes drone @skills run telegram <action> to the multi-bot framework.
"""

import sys

from aipass.prax import logger
from aipass.skills.apps.handlers.module_paths import module_file

_skill_root = module_file(__file__).parent
if str(_skill_root) not in sys.path:
    sys.path.insert(0, str(_skill_root))

_ACTIONS = {
    "start",
    "stop",
    "status",
    "create",
    "delete",
    "notify",
}


def _ok(output: str) -> dict:
    return {"success": True, "output": output, "error": None}


def _err(msg: str) -> dict:
    return {"success": False, "output": "", "error": msg}


def _normalize_args(args) -> list:
    """Normalize the skill runner's arg contract into a positional list.

    The AIPass skill runner passes action arguments as a DICT
    (``{"arg0": "base", "--branch": "seed", ...}`` from _parse_extra_args),
    while the _cmd_* handlers consume a positional LIST. Convert:
      - positional keys ``arg0..argN`` -> value only (preserves order)
      - ``key=value`` / flag keys      -> ``key, value`` (rebuilds ``--branch seed``)
    A list (e.g. from direct/unit-test calls) passes through unchanged.
    """
    if not isinstance(args, dict):
        return list(args or [])
    out: list = []
    for key, value in args.items():
        if key.startswith("arg") and key[3:].isdigit():
            out.append(value)
        else:
            out.append(key)
            out.append(value)
    return out


def _cmd_start(args: list) -> dict:
    if not args:
        return _err("start requires a bot_id: drone @skills run telegram start <bot_id>")
    from aipass.skills.lib.telegram.apps.handlers.bot_operations import start_bot

    bot_id = args[0]
    exit_code = start_bot(bot_id)
    if exit_code is None:
        return _err(f"Failed to load config for bot '{bot_id}'")
    return _ok(f"Bot '{bot_id}' exited with code {exit_code}")


def _cmd_stop(args: list) -> dict:
    if not args:
        return _err("stop requires a bot_id: drone @skills run telegram stop <bot_id>")
    from aipass.skills.lib.telegram.apps.handlers.bot_operations import stop_bot

    success, message = stop_bot(args[0])
    if success:
        return _ok(message)
    return _err(message)


def _cmd_status(args: list) -> dict:
    from aipass.skills.lib.telegram.apps.handlers.bot_operations import (
        format_bot_details,
        format_bot_table,
        get_status,
    )

    bot_id = args[0] if args else None
    bots = get_status(bot_id)
    if not bots:
        msg = f"No bot found with id '{bot_id}'" if bot_id else "No bots registered"
        return _ok(msg)
    if bot_id:
        return _ok("\n".join(format_bot_details(bots[0])))
    return _ok("\n".join(format_bot_table(bots)))


def _cmd_create(args: list) -> dict:
    from aipass.skills.lib.telegram.apps.handlers.bot_factory import create_bot
    from aipass.skills.lib.telegram.apps.handlers.bot_operations import parse_create_args

    parsed = parse_create_args(args)
    if not parsed:
        return _err("create requires: <bot_id> <token> [--branch name] [--work-dir path]")
    result = create_bot(
        bot_id=parsed["bot_id"],
        bot_token=parsed["bot_token"],
        branch_name=parsed.get("branch_name"),
        work_dir=parsed.get("work_dir"),
    )
    if result:
        return _ok(f"Bot '{parsed['bot_id']}' created successfully")
    return _err(f"Failed to create bot '{parsed['bot_id']}'")


def _cmd_delete(args: list) -> dict:
    if not args:
        return _err("delete requires a bot_id: drone @skills run telegram delete <bot_id>")
    from aipass.skills.lib.telegram.apps.handlers.bot_factory import delete_bot

    success = delete_bot(args[0])
    if success:
        return _ok(f"Bot '{args[0]}' deleted")
    return _err(f"Failed to delete bot '{args[0]}'")


def _cmd_notify(args: list) -> dict:
    if not args:
        return _err('notify requires a message: drone @skills run telegram notify "message"')
    from aipass.skills.lib.telegram.apps.handlers.notifier import send_telegram_notification

    message = " ".join(args)
    success = send_telegram_notification(message)
    if success:
        return _ok(f"Notification sent: {message}")
    return _err("Failed to send notification")


_DISPATCH = {
    "start": _cmd_start,
    "stop": _cmd_stop,
    "status": _cmd_status,
    "create": _cmd_create,
    "delete": _cmd_delete,
    "notify": _cmd_notify,
}


def run(action: str, args: list, config: dict) -> dict:
    """
    Route a skill action to the telegram multi-bot framework.

    Args:
        action: The action to perform (start, stop, status, create, delete, notify)
        args: Command arguments after the action
        config: Skill configuration from SKILL.md

    Returns:
        dict with keys: success (bool), output (str), error (str|None)
    """
    if not action:
        return _err(f"No action specified. Available: {', '.join(sorted(_ACTIONS))}")

    handler = _DISPATCH.get(action)
    if not handler:
        return _err(f"Unknown action '{action}'. Available: {', '.join(sorted(_ACTIONS))}")

    try:
        return handler(_normalize_args(args))
    except Exception as e:
        logger.error("telegram skill action '%s' failed: %s", action, e)
        return _err(f"{action} failed: {e}")
