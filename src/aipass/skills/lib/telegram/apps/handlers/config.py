"""Telegram bot configuration, read from the @api secrets store.

Every bot's token, username and allowed-user list lives in secrets and is
fetched in-process through ``aipass.api.apps.modules.secrets`` - no
subprocess, no stdout parsing, so a token never crosses a pipe. Also
validates a config before a bot is started, because a half-configured bot
that starts is worse than one that refuses.
"""

# Standard library
from pathlib import PurePosixPath, PureWindowsPath
from typing import Optional, List

# Logging
from aipass.prax import logger

# Cross-branch in-process secrets API
from aipass.api.apps.modules.secrets import get_secret as _api_get_secret
from aipass.api.apps.modules.secrets import list_secrets as _api_list_secrets

# =============================================
# CONSTANTS
# =============================================

REQUIRED_BOT_FIELDS = ("bot_id", "bot_token")

# =============================================
# SECRETS ACCESS (in-process @api)
# =============================================


def _get_secret(bot_id: str) -> dict | None:
    """
    Retrieve bot config from the API secrets store.

    Uses the in-process aipass.api.apps.modules.secrets.get_secret API
    (no subprocess, no stdout parsing, no token leakage).

    Args:
        bot_id: Bot identifier to look up.

    Returns:
        Config dict or None if the call fails or returns no data.
    """
    try:
        result = _api_get_secret("telegram", bot_id, as_json=True)
        if result is None:
            logger.warning("Secret not found: telegram/%s", bot_id)
            return None
        if not isinstance(result, dict):
            logger.warning("Secret telegram/%s is not a dict", bot_id)
            return None
        return result
    except Exception as e:
        logger.error("Failed to fetch secret telegram/%s: %s", bot_id, e)
        return None


# =============================================
# LEGACY SINGLE-BOT HELPERS (rewired to @api)
# =============================================


def load_telegram_config() -> Optional[dict]:
    """
    Load Telegram configuration via the API secrets store.

    Fetches the default bot config (bot_id="default").

    Returns:
        Configuration dict or None if load fails.
    """
    return _get_secret("default")


def get_bot_token() -> Optional[str]:
    """
    Get Telegram bot token from the default bot config.

    Returns:
        Bot token string or None if not found.
    """
    config = load_telegram_config()
    if not config:
        return None

    token = config.get("bot_token") or config.get("telegram_bot_token")
    if not token:
        return None

    return token


def get_bot_username() -> Optional[str]:
    """
    Get Telegram bot username from the default bot config.

    Returns:
        Bot username string or None if not found.
    """
    config = load_telegram_config()
    if not config:
        return None

    username = config.get("bot_username") or config.get("telegram_bot_username")
    if not username:
        return None

    return username


def get_allowed_user_ids() -> List[int]:
    """
    Get list of allowed Telegram user IDs from the default bot config.

    Returns:
        List of allowed user IDs. Empty list means allow all (for testing).
    """
    config = load_telegram_config()
    if not config:
        return []

    allowed = config.get("allowed_user_ids", [])
    if not isinstance(allowed, list):
        return []

    return [int(uid) for uid in allowed if isinstance(uid, (int, str))]


def validate_config() -> bool:
    """
    Validate that the default Telegram bot configuration is complete.

    Returns:
        True if config is valid, False otherwise.
    """
    config = load_telegram_config()
    if not config:
        return False

    if not (config.get("bot_token") or config.get("telegram_bot_token")):
        return False

    return True


# =============================================
# MULTI-BOT CONFIGURATION (per-bot configs)
# =============================================


def load_bot_config(bot_id: str) -> dict | None:
    """
    Load per-bot config from the API secrets store.

    Uses the in-process secrets API: get_secret("telegram", bot_id).

    Config format:
    {
        "bot_id": "dev_central",
        "bot_token": "123:ABC...",
        "bot_name": "AIPass Dev Central Bot",
        "branch_name": "dev_central",  // null for base bot
        "work_dir": "/path/to/branch/work_dir",
        "allowed_user_ids": [7235222625]
    }

    Args:
        bot_id: Bot identifier to fetch.

    Returns:
        Config dict or None if not found/invalid.
    """
    return _get_secret(bot_id)


def list_bot_configs() -> list[str]:
    """
    List all registered bot IDs via the API secrets store.

    Uses the in-process aipass.api.apps.modules.secrets.list_secrets API.

    Returns:
        List of bot_id strings, or empty list on failure.
    """
    try:
        return _api_list_secrets("telegram")
    except Exception as e:
        logger.error("Failed to list telegram secrets: %s", e)
        return []


def validate_bot_config(config: object) -> tuple[bool, str]:
    """
    Validate a bot config dict.

    Checks for required fields and basic type correctness.
    Pure function — no I/O.

    Args:
        config: Bot config dict to validate.

    Returns:
        Tuple of (valid, error_message). error_message is empty on success.
    """
    if not isinstance(config, dict):
        return False, "Config must be a dict"

    # Check required fields
    for field in REQUIRED_BOT_FIELDS:
        if not config.get(field):
            return False, f"Missing required field: {field}"

    # Type checks
    bot_token = config.get("bot_token", "")
    if not isinstance(bot_token, str) or ":" not in bot_token:
        return False, "bot_token must be a string in format 'id:hash'"

    if "work_dir" in config and config["work_dir"] is not None:
        # work_dir is a deployment-target (Linux) path. Test absoluteness under
        # POSIX *and* Windows semantics so validation is platform-independent —
        # a bare host Path().is_absolute() would reject "/home/..." on Windows.
        work_dir = str(config["work_dir"])
        if not (PurePosixPath(work_dir).is_absolute() or PureWindowsPath(work_dir).is_absolute()):
            return False, "work_dir must be an absolute path"

    if "allowed_user_ids" in config:
        allowed = config["allowed_user_ids"]
        if not isinstance(allowed, list):
            return False, "allowed_user_ids must be a list"

    return True, ""
