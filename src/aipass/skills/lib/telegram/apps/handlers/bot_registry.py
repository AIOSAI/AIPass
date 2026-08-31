# =================== AIPass ====================
# Name: bot_registry.py
# Description: Telegram bot registry — JSON store with advisory file locking
# Version: 1.0.0
# Created: 2026-06-24
# Modified: 2026-06-25
# =============================================

"""Telegram bot registry.

Persists registered bots to a JSON file with advisory file locking so concurrent
read-modify-write operations don't corrupt the store. Provides CRUD plus lookup
helpers (by id, branch, work_dir).
"""

# Standard library
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Logging
from aipass.prax import logger
from aipass.skills.apps.handlers.module_paths import module_file

# fcntl is POSIX-only (Linux/macOS); unavailable on Windows. Guard the import and
# skip advisory locking when absent. Matches the codebase convention (hooks/cadence,
# daemon) — see seedgo windows_compat standard.
try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]
    logger.info("[TELEGRAM] bot_registry: fcntl unavailable (Windows) — skipping advisory locks")


def _lock(f, *, exclusive: bool) -> None:
    """Acquire an advisory lock on an open file; no-op without fcntl (Windows)."""
    if fcntl is None:
        return
    fcntl.flock(f.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)


def _unlock(f) -> None:
    """Release an advisory lock; no-op when fcntl is unavailable (Windows)."""
    if fcntl is None:
        return
    fcntl.flock(f.fileno(), fcntl.LOCK_UN)


# =============================================
# CONSTANTS
# =============================================

SKILL_ROOT = module_file(__file__).parents[2]
REGISTRY_DIR = SKILL_ROOT / ".local" / "state"
REGISTRY_FILE = REGISTRY_DIR / "_registry.json"

# =============================================
# EMPTY REGISTRY TEMPLATE
# =============================================


def _empty_registry() -> dict:
    """Return a fresh empty registry structure."""
    return {
        "bots": {},
        "metadata": {
            "version": "1.0.0",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        },
    }


def _now_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


# =============================================
# REGISTRY LIFECYCLE
# =============================================


def ensure_registry() -> None:
    """
    Create registry directory and file if they don't exist.

    Safe to call multiple times - only creates what is missing.
    """
    try:
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        if not REGISTRY_FILE.exists():
            data = _empty_registry()
            with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
                _lock(f, exclusive=True)
                try:
                    json.dump(data, f, indent=2)
                finally:
                    _unlock(f)
            logger.info("Created new bot registry at %s", REGISTRY_FILE)
    except OSError as e:
        logger.warning("Failed to ensure registry: %s", e)


# =============================================
# READ / WRITE WITH LOCKING
# =============================================


def load_registry() -> dict:
    """
    Load registry with fcntl shared lock.

    Returns:
        Registry dict. Returns empty structure if file missing or corrupt.
    """
    if not REGISTRY_FILE.exists():
        return _empty_registry()

    try:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            _lock(f, exclusive=False)
            try:
                data = json.load(f)
            finally:
                _unlock(f)

        if not isinstance(data, dict) or "bots" not in data:
            logger.warning("Registry file has unexpected structure, returning empty")
            return _empty_registry()

        return data

    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load registry: %s", e)
        return _empty_registry()


def save_registry(data: dict) -> bool:
    """
    Save registry with fcntl exclusive lock.

    Args:
        data: Full registry dict to write.

    Returns:
        True if saved successfully, False on error.
    """
    try:
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

        # Update metadata timestamp
        if "metadata" not in data:
            data["metadata"] = {}
        data["metadata"]["last_updated"] = _now_iso()

        with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
            _lock(f, exclusive=True)
            try:
                json.dump(data, f, indent=2)
            finally:
                _unlock(f)

        return True

    except OSError as e:
        logger.warning("Failed to save registry: %s", e)
        return False


# =============================================
# CRUD OPERATIONS
# =============================================


def get_bot(bot_id: str) -> Optional[dict]:
    """
    Get a single bot entry by bot_id.

    Args:
        bot_id: Unique bot identifier.

    Returns:
        Bot entry dict or None if not found.
    """
    registry = load_registry()
    return registry.get("bots", {}).get(bot_id)


def list_bots(status: Optional[str] = None) -> list[dict]:
    """
    List all bots, optionally filtered by status.

    Args:
        status: Filter by status (e.g., "active", "inactive"). None returns all.

    Returns:
        List of bot entry dicts.
    """
    registry = load_registry()
    bots = list(registry.get("bots", {}).values())

    if status is not None:
        bots = [b for b in bots if b.get("status") == status]

    return bots


def register_bot(
    bot_id: str,
    username: str,
    branch_name: Optional[str],
    work_dir: str,
    config_path: str,
    bot_token_ref: Optional[str] = None,
) -> bool:
    """
    Register a new bot in the registry.

    Args:
        bot_id: Unique bot identifier.
        username: Telegram bot username (e.g., "aipass_dev_central_bot").
        branch_name: AIPass branch name, or None for the base bot.
        work_dir: Working directory for Claude sessions.
        config_path: Path to the bot's config JSON file.
        bot_token_ref: Optional env var name or reference for the token.

    Returns:
        True on success, False if bot_id already exists or on error.
    """
    registry = load_registry()
    bots = registry.get("bots", {})

    if bot_id in bots:
        logger.warning("Bot '%s' already registered", bot_id)
        return False

    now = _now_iso()
    entry = {
        "bot_id": bot_id,
        "username": username,
        "branch_name": branch_name,
        "work_dir": str(work_dir),
        "config_path": str(config_path),
        "service_name": f"telegram-bot@{bot_id}",
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }

    if bot_token_ref:
        entry["bot_token_env"] = bot_token_ref

    bots[bot_id] = entry
    registry["bots"] = bots

    if not save_registry(registry):
        return False

    logger.info("Registered bot '%s' (branch=%s, work_dir=%s)", bot_id, branch_name, work_dir)
    return True


def update_bot(bot_id: str, **kwargs) -> bool:
    """
    Update specific fields of a bot entry.

    Auto-updates the updated_at timestamp.

    Args:
        bot_id: Bot identifier to update.
        **kwargs: Fields to update (e.g., status="inactive", username="new_name").

    Returns:
        True on success, False if bot not found or on error.
    """
    registry = load_registry()
    bots = registry.get("bots", {})

    if bot_id not in bots:
        logger.warning("Cannot update bot '%s': not found", bot_id)
        return False

    for key, value in kwargs.items():
        bots[bot_id][key] = value

    bots[bot_id]["updated_at"] = _now_iso()
    registry["bots"] = bots

    if not save_registry(registry):
        return False

    logger.info("Updated bot '%s': %s", bot_id, list(kwargs.keys()))
    return True


def deregister_bot(bot_id: str) -> bool:
    """
    Remove a bot from the registry.

    Args:
        bot_id: Bot identifier to remove.

    Returns:
        True on success, False if bot not found or on error.
    """
    registry = load_registry()
    bots = registry.get("bots", {})

    if bot_id not in bots:
        logger.warning("Cannot deregister bot '%s': not found", bot_id)
        return False

    del bots[bot_id]
    registry["bots"] = bots

    if not save_registry(registry):
        return False

    logger.info("Deregistered bot '%s'", bot_id)
    return True


# =============================================
# LOOKUP HELPERS
# =============================================


def get_bot_by_branch(branch_name: str) -> Optional[dict]:
    """
    Find a bot by its branch_name.

    Args:
        branch_name: AIPass branch name (e.g., "dev_central").

    Returns:
        Bot entry dict or None if not found.
    """
    registry = load_registry()
    for bot in registry.get("bots", {}).values():
        if bot.get("branch_name") == branch_name:
            return bot
    return None


def get_bot_by_work_dir(work_dir) -> Optional[dict]:
    """
    Find a bot whose work_dir matches the given path.

    Used by the response router to match CWD to a bot.

    Args:
        work_dir: Path (str or Path) to match against bot work_dir fields.

    Returns:
        Bot entry dict or None if not found.
    """
    target = str(Path(work_dir).resolve())
    registry = load_registry()

    for bot in registry.get("bots", {}).values():
        bot_dir = bot.get("work_dir", "")
        if bot_dir:
            try:
                if str(Path(bot_dir).resolve()) == target:
                    return bot
            except (ValueError, OSError) as e:
                logger.warning("Skipping unresolvable bot work_dir %r: %s", bot_dir, e)
                continue

    return None
