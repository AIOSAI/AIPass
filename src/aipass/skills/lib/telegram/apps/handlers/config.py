# =================== AIPass ====================
# Name: config.py
# Description: Telegram bot config - the token in secrets, everything else in ordinary config
# Version: 2.0.0
# Created: 2026-06-15
# Modified: 2026-09-07
# =============================================

"""Telegram bot configuration, split across a secret store and ordinary config.

A bot is described by ten keys and exactly one of them is a credential. The
token lives in the @api secret store and is fetched in-process through
``aipass.api.apps.modules.secrets`` - no subprocess, no stdout parsing, so it
never crosses a pipe. Everything else - bot_id, branch_name, work_dir,
chat_id, the lot - is ordinary configuration in a plain file, because a
secret store is not a filing cabinet: whatever is put in one is treated as a
credential by every tool downstream, and mixing the two makes nine harmless
keys as radioactive as the tenth. ``load_bot_config`` merges the halves back
into the single dict every caller already expects.

Also validates a config before a bot is started, because a half-configured
bot that starts is worse than one that refuses.
"""

# Standard library
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional, List

# Logging
from aipass.prax import logger

# JSON handler (seedgo standard)
from aipass.skills.apps.handlers.json import json_handler

# Cross-branch in-process secrets API
from aipass.api.apps.modules.secrets import get_secret as _api_get_secret
from aipass.api.apps.modules.secrets import list_secrets as _api_list_secrets
from aipass.api.apps.modules.secrets import set_secret as _api_set_secret

# =============================================
# CONSTANTS
# =============================================

REQUIRED_BOT_FIELDS = ("bot_id", "bot_token")

# The ONLY keys a telegram secret document may carry. A secret store is not a
# filing cabinet: everything inside one is handled as a credential by every
# tool downstream, so a document that also carries branch_name and work_dir
# makes nine harmless keys as radioactive as the tenth - and drags them
# through every sink a scanner models. Anything not named here is ordinary
# configuration and belongs in BOT_CONFIG_DIR.
#
# api_id/api_hash are here because the telegram/telethon_config document is a
# Telegram APP credential, not a bot config, and it lives under the same
# provider. A first dry run of the migration over the live store proposed
# moving both to a plain file - true secrets are named here so that can never
# happen, to them or to anything like them.
SECRET_FIELDS = ("bot_token", "api_id", "api_hash")

# Ordinary, non-secret bot configuration. Read through bot_config_path() so
# the directory is resolved per call and a test can redirect it.
BOT_CONFIG_DIR = Path.home() / ".aipass" / "telegram_bots"

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
# THE SPLIT (secret store <-> ordinary config)
# =============================================


def bot_config_path(bot_id: str) -> Path:
    """
    Path of a bot's ordinary (non-secret) config document.

    Resolved per call off the module-level BOT_CONFIG_DIR, never captured at
    import: a captured constant is a directory a test cannot redirect.

    Args:
        bot_id: Bot identifier.

    Returns:
        Path to <BOT_CONFIG_DIR>/<bot_id>.json.
    """
    return BOT_CONFIG_DIR / f"{bot_id}.json"


def split_bot_config(config: dict) -> tuple[dict, dict]:
    """
    Split one bot config into the halves that get stored apart.

    Pure function — no I/O. SECRET_FIELDS is the whole rule, so "which half
    does this key belong in" has exactly one answer and a test can read it.

    Args:
        config: Full bot config dict.

    Returns:
        Tuple of (secret_document, config_document).
    """
    secret = {key: value for key, value in config.items() if key in SECRET_FIELDS}
    plain = {key: value for key, value in config.items() if key not in SECRET_FIELDS}
    return secret, plain


def non_secret_keys(document: object) -> list[str]:
    """
    Name every key in a document that has no business in a secret store.

    Args:
        document: The candidate secret document.

    Returns:
        Sorted list of offending key names; empty when the document is clean.
    """
    if not isinstance(document, dict):
        return []
    return sorted(key for key in document if key not in SECRET_FIELDS)


def write_bot_config(bot_id: str, config: dict) -> bool:
    """
    Write a bot's ordinary config document.

    Args:
        bot_id: Bot identifier.
        config: The non-secret half. A bot_token here is a caller bug and is
            refused rather than written to a plain file.

    Returns:
        True on success, False on write failure.
    """
    leaked = [key for key in config if key in SECRET_FIELDS]
    if leaked:
        logger.error("Refusing to write secret field(s) %s to plain config for '%s'", leaked, bot_id)
        return False

    path = bot_config_path(bot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not json_handler.write_json(path, config):
        logger.error("Failed to write bot config for '%s' to %s", bot_id, path)
        return False

    json_handler.log_operation("telegram_bot_config_written", {"bot_id": bot_id})
    return True


def read_bot_config_file(bot_id: str) -> dict | None:
    """
    Read a bot's ordinary config document.

    Args:
        bot_id: Bot identifier.

    Returns:
        Config dict, or None when the file is absent or unreadable.
    """
    document = json_handler.read_json(bot_config_path(bot_id))
    if document is None:
        return None
    if not isinstance(document, dict):
        logger.warning("Bot config %s is not a dict", bot_config_path(bot_id))
        return None
    return document


def migrate_bot_config(bot_id: str, *, dry_run: bool = True) -> dict:
    """
    Split one legacy document that still carries config in the secret store.

    Writes the ordinary config FIRST, then shrinks the secret document. In
    that order a failure halfway leaves the bot readable either way: the
    merge takes the secret half last, and the overlapping values are equal.

    Args:
        bot_id: Bot identifier.
        dry_run: When True (the default) nothing is written; the report says
            what would move. Rewriting live credentials is a decision, so it
            is never the default.

    Returns:
        Report dict: bot_id, moved (key names), kept (key names), migrated
        (bool), and reason when nothing happened.
    """
    secret = _get_secret(bot_id)
    if secret is None:
        return {"bot_id": bot_id, "moved": [], "kept": [], "migrated": False, "reason": "no secret document"}

    moved = non_secret_keys(secret)
    kept = sorted(key for key in secret if key in SECRET_FIELDS)
    if not moved:
        return {"bot_id": bot_id, "moved": [], "kept": kept, "migrated": False, "reason": "already split"}

    if dry_run:
        return {"bot_id": bot_id, "moved": moved, "kept": kept, "migrated": False, "reason": "dry run"}

    secret_half, plain_half = split_bot_config(secret)
    existing = read_bot_config_file(bot_id) or {}
    existing.update(plain_half)
    if not write_bot_config(bot_id, existing):
        return {"bot_id": bot_id, "moved": [], "kept": kept, "migrated": False, "reason": "config write failed"}

    try:
        _api_set_secret("telegram", bot_id, secret_half, as_json=True)
    except OSError as e:
        logger.error("Migration wrote config for '%s' but could not shrink the secret document: %s", bot_id, e)
        return {
            "bot_id": bot_id,
            "moved": moved,
            "kept": kept,
            "migrated": False,
            "reason": f"secret write failed: {e}",
        }

    logger.info("Migrated telegram/%s: moved %d non-secret key(s) to %s", bot_id, len(moved), bot_config_path(bot_id))
    json_handler.log_operation("telegram_bot_config_migrated", {"bot_id": bot_id, "moved": moved})
    return {"bot_id": bot_id, "moved": moved, "kept": kept, "migrated": True, "reason": ""}


# =============================================
# LEGACY SINGLE-BOT HELPERS (rewired to @api)
# =============================================


def load_telegram_config() -> Optional[dict]:
    """
    Load Telegram configuration via the API secrets store.

    Fetches the default bot config (bot_id="default"), both halves merged —
    username and allowed_user_ids are ordinary config, only the token is not.

    Returns:
        Configuration dict or None if load fails.
    """
    return load_bot_config("default")


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
        Config dict or None if neither half exists.
    """
    secret = _get_secret(bot_id)
    plain = read_bot_config_file(bot_id)

    if plain is None:
        if secret is None:
            return None
        # A document written before the split, still carrying the lot. It is
        # read, because a deployed bot must keep running - but it is named,
        # loudly, every single load, because "works" is not "correct".
        strays = non_secret_keys(secret)
        if strays:
            logger.warning(
                "Legacy secret document telegram/%s carries %d non-secret key(s) %s and has no config file at %s "
                "- run config.migrate_bot_config('%s', dry_run=False) to split it",
                bot_id,
                len(strays),
                strays,
                bot_config_path(bot_id),
                bot_id,
            )
        return dict(secret)

    # The secret half is applied last: on a half-migrated bot the two agree,
    # and where they disagree the credential store is the authority.
    merged = dict(plain)
    if secret:
        merged.update(secret)
    return merged


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
