# =================== AIPass ====================
# Name: medic_state.py
# Description: Medic state persistence and status collection handler
# Version: 1.1.0
# Created: 2026-02-12
# Modified: 2026-02-12
# =============================================

"""
Medic State Handler - Persistence and status for Medic toggle

Reads/writes medic_enabled flag and muted_branches list in trigger_config.json.
Collects status data from suppression logs and rate limit logs.

Architecture:
    Module (medic.py) orchestrates, this handler manages state.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.trigger.apps.config import TRIGGER_ROOT, atomic_write_json, json_file_lock
from aipass.trigger.apps.handlers.json import json_handler

logger = get_direct_logger()

TRIGGER_CONFIG_FILE = TRIGGER_ROOT / "trigger_json" / "trigger_config.json"
MEDIC_SUPPRESSED_LOG = TRIGGER_ROOT / "logs" / "medic_suppressed.log"
RATE_LIMITED_LOG = TRIGGER_ROOT / "logs" / "rate_limited.log"


def read_config() -> dict:
    """
    Read trigger_config.json.

    Returns:
        Parsed config dict, or empty dict on failure
    """
    try:
        if TRIGGER_CONFIG_FILE.exists():
            return json.loads(TRIGGER_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("read_config failed: %s", exc)
        return {}
    return {}


def write_config(data: dict) -> bool:
    """
    Write trigger_config.json.

    Args:
        data: Config dict to persist

    Returns:
        True on success, False on failure
    """
    try:
        atomic_write_json(TRIGGER_CONFIG_FILE, data)
        return True
    except Exception as exc:
        logger.warning("write_config failed: %s", exc)
        return False


def is_enabled() -> bool:
    """
    Check if Medic is currently enabled.

    Returns:
        True if medic_enabled is True in config (defaults to True)
    """
    data = read_config()
    return bool(data.get("config", {}).get("medic_enabled", True))


def set_enabled(enabled: bool) -> bool:
    """
    Set medic_enabled flag in config.

    Args:
        enabled: True to enable, False to disable

    Returns:
        True on success
    """
    with json_file_lock(TRIGGER_CONFIG_FILE):
        data = read_config()
        if "config" not in data:
            data["config"] = {}
        data["config"]["medic_enabled"] = enabled
        data["timestamp"] = datetime.now().strftime("%Y-%m-%d")

        if write_config(data):
            json_handler.log_operation("state_persisted", {"key": "medic_enabled", "value": enabled})
            return True
    return False


def _normalize_branch_name(name: str) -> str:
    """
    Normalize a branch name - strip @, extract from path if needed.

    Args:
        name: Raw branch name (could be path, @-prefixed, etc.)

    Returns:
        Lowercase branch name (e.g., 'speakeasy')
    """
    cleaned = name.lstrip("@")
    if "/" in cleaned:
        cleaned = Path(cleaned).name
    return cleaned.lower()


def get_muted_branches() -> List[str]:
    """
    Get list of muted branch names.

    Returns:
        List of muted branch names (lowercase, e.g., ['speakeasy', 'api'])
    """
    data = read_config()
    raw = data.get("config", {}).get("muted_branches", [])
    return [_normalize_branch_name(b) for b in raw]


def mute_branch(branch_name: str) -> bool:
    """
    Add a branch to the muted list.

    Muted branches will have errors detected but NOT dispatched.
    Persists in trigger_config.json.

    Args:
        branch_name: Branch name (with or without @)

    Returns:
        True on success
    """
    clean = _normalize_branch_name(branch_name)
    with json_file_lock(TRIGGER_CONFIG_FILE):
        data = read_config()
        if "config" not in data:
            data["config"] = {}
        muted = [_normalize_branch_name(b) for b in data["config"].get("muted_branches", [])]
        if clean not in muted:
            muted.append(clean)
        data["config"]["muted_branches"] = muted
        data["timestamp"] = datetime.now().strftime("%Y-%m-%d")
        return write_config(data)


def unmute_branch(branch_name: str) -> bool:
    """
    Remove a branch from the muted list.

    Args:
        branch_name: Branch name (with or without @)

    Returns:
        True on success
    """
    clean = _normalize_branch_name(branch_name)
    with json_file_lock(TRIGGER_CONFIG_FILE):
        data = read_config()
        if "config" not in data:
            data["config"] = {}
        muted = [_normalize_branch_name(b) for b in data["config"].get("muted_branches", [])]
        muted = [b for b in muted if b != clean]
        data["config"]["muted_branches"] = muted
        data["timestamp"] = datetime.now().strftime("%Y-%m-%d")
        return write_config(data)


def get_suppression_stats() -> Dict[str, Any]:
    """
    Get suppression log statistics.

    Returns:
        Dict with suppressed_count and last_suppressed timestamp
    """
    suppressed_count = 0
    last_suppressed = "never"
    try:
        if MEDIC_SUPPRESSED_LOG.exists():
            lines = MEDIC_SUPPRESSED_LOG.read_text(encoding="utf-8").strip().splitlines()
            suppressed_count = len(lines)
            if lines:
                last_line = lines[-1]
                last_suppressed = last_line.split(" | ")[0] if " | " in last_line else "unknown"
    except Exception as exc:
        logger.warning("get_suppression_stats failed: %s", exc)
        return {"suppressed_count": 0, "last_suppressed": "error reading log"}

    return {
        "suppressed_count": suppressed_count,
        "last_suppressed": last_suppressed,
    }


def get_rate_limit_stats() -> Dict[str, Any]:
    """
    Get rate limit log statistics.

    Returns:
        Dict with rate_limited_count and last_rate_limited timestamp
    """
    dispatch_count = 0
    last_dispatch = "never"
    try:
        if RATE_LIMITED_LOG.exists():
            lines = RATE_LIMITED_LOG.read_text(encoding="utf-8").strip().splitlines()
            dispatch_count = len(lines)
            if lines:
                last_line = lines[-1]
                last_dispatch = last_line.split(" | ")[0] if " | " in last_line else "unknown"
    except Exception as exc:
        logger.warning("get_rate_limit_stats failed: %s", exc)
        return {"rate_limited_count": 0, "last_rate_limited": "error reading log"}

    return {
        "rate_limited_count": dispatch_count,
        "last_rate_limited": last_dispatch,
    }
