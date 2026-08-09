# =================== AIPass ====================
# Name: medic_state.py
# Description: Medic state persistence and status collection handler
# Version: 1.2.0
# Created: 2026-02-12
# Modified: 2026-08-07
# =============================================

"""
Medic State Handler - Persistence and status for Medic toggle

Reads/writes medic_enabled flag and the mute lists in medic_state.json.
Collects status data from suppression logs and rate limit logs.

State lives in trigger_json/medic_state.json. It used to live in
trigger_json/trigger_config.json, which is a name json_handler's trio
machinery owns for module "trigger": any trio call under that caller name
validates the file against a config template, finds this hand-written shape
invalid, and overwrites it with a blank one — taking every live mute and the
persisted breaker state with it. Nothing routed there yet; the file moved
before something did. read_config() migrates on first read.

Two independent mute classes share the same entry format and TTL machinery:
    muted_branches         - CONTENT mutes. Silence error_detected dispatch for
                             a branch doing known-noisy work.
    volume_muted_branches  - VOLUME mutes. Silence runaway_log_detected alerts.

They are deliberately separate: a content mute says "expect error lines from
me right now", which says nothing about log volume. Gating volume alerts on a
content mute inverted their purpose — during build windows (when agents mute
themselves) runaway alerts were exactly the ones being dropped.

Architecture:
    Module (medic.py) orchestrates, this handler manages state.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.trigger.apps.config import (
    TRIGGER_JSON_DIR,
    TRIGGER_ROOT,
    atomic_write_json,
    json_file_lock,
    migrate_json_file,
)
from aipass.trigger.apps.handlers.json import json_handler

logger = get_direct_logger()

MEDIC_STATE_FILE = TRIGGER_JSON_DIR / "medic_state.json"
LEGACY_MEDIC_STATE_FILE = TRIGGER_JSON_DIR / "trigger_config.json"
MEDIC_SUPPRESSED_LOG = TRIGGER_ROOT / "logs" / "medic_suppressed.jsonl"
RATE_LIMITED_LOG = TRIGGER_ROOT / "logs" / "rate_limited.jsonl"

_DURATION_RE = re.compile(r"^(\d+)(h|d)$")

DEFAULT_MUTE_SECONDS = 86400  # 24 hours
DEFAULT_OFF_SECONDS = 86400  # 24 hours

# Two independent mute classes — see module docstring.
MUTE_KEY_CONTENT = "muted_branches"  # content-based error noise (medic)
MUTE_KEY_VOLUME = "volume_muted_branches"  # volume-based runaway alerts
MUTE_KEYS = (MUTE_KEY_CONTENT, MUTE_KEY_VOLUME)


def parse_duration(duration_str: str) -> Optional[float]:
    """Parse a duration string like '24h', '48h', '7d' into seconds.

    Args:
        duration_str: Duration with unit suffix (h=hours, d=days)

    Returns:
        Seconds as float, or None if unparseable
    """
    m = _DURATION_RE.match(duration_str.strip())
    if not m:
        return None
    value, unit = int(m.group(1)), m.group(2)
    if unit == "h":
        return float(value * 3600)
    return float(value * 86400)


def _is_mute_active(entry, now: datetime) -> bool:
    """Check if a single mute entry is still active."""
    if isinstance(entry, str):
        return True
    if not isinstance(entry, dict):
        return False
    expires_at = entry.get("expires_at")
    if expires_at is None:
        return True
    return datetime.fromisoformat(expires_at) > now


def _clean_expired_mutes(data: dict) -> None:
    """Remove expired mute entries from every mute class in config data, in-place."""
    config = data.get("config", {})
    now = datetime.now()
    for key in MUTE_KEYS:
        muted = config.get(key, [])
        if not muted:
            continue
        config[key] = [e for e in muted if _is_mute_active(e, now)]


def read_config() -> dict:
    """
    Read medic_state.json, migrating off the legacy path on first read.

    Returns:
        Parsed config dict, or empty dict on failure
    """
    migrate_json_file(LEGACY_MEDIC_STATE_FILE, MEDIC_STATE_FILE)
    try:
        if MEDIC_STATE_FILE.exists():
            return json.loads(MEDIC_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("read_config failed: %s", exc)
        return {}
    return {}


def write_config(data: dict) -> bool:
    """
    Write medic_state.json. Cleans expired mute entries before writing.

    Args:
        data: Config dict to persist

    Returns:
        True on success, False on failure
    """
    try:
        _clean_expired_mutes(data)
        atomic_write_json(MEDIC_STATE_FILE, data)
        return True
    except Exception as exc:
        logger.warning("write_config failed: %s", exc)
        return False


def is_enabled() -> bool:
    """
    Check if Medic is currently enabled.

    If disabled with a TTL (medic_disabled_until), treats an expired
    TTL as enabled — evaluate on read, no timers.

    Returns:
        True if medic_enabled is True or its TTL has expired
    """
    data = read_config()
    config = data.get("config", {})
    enabled = bool(config.get("medic_enabled", True))
    if not enabled:
        disabled_until = config.get("medic_disabled_until")
        if disabled_until:
            if datetime.fromisoformat(disabled_until) <= datetime.now():
                return True
    return enabled


def get_disabled_until() -> Optional[str]:
    """Get the medic_disabled_until timestamp if set.

    Returns:
        ISO timestamp string, or None if not set or permanent off
    """
    data = read_config()
    return data.get("config", {}).get("medic_disabled_until")


def set_enabled(enabled: bool, duration_seconds: Optional[float] = None) -> bool:
    """
    Set medic_enabled flag in config.

    When disabling with a duration, stores medic_disabled_until so the
    off state auto-expires. When enabling, clears any stored expiry.

    Args:
        enabled: True to enable, False to disable
        duration_seconds: TTL in seconds for disable (None = permanent)

    Returns:
        True on success
    """
    with json_file_lock(MEDIC_STATE_FILE):
        data = read_config()
        if "config" not in data:
            data["config"] = {}
        data["config"]["medic_enabled"] = enabled
        if not enabled and duration_seconds is not None:
            expires = datetime.now() + timedelta(seconds=duration_seconds)
            data["config"]["medic_disabled_until"] = expires.isoformat()
        else:
            data["config"].pop("medic_disabled_until", None)
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


def _get_muted_detail_for(key: str) -> List[Dict[str, Any]]:
    """
    Get active mute entries for one mute class, with expiry info.

    Args:
        key: Config key — MUTE_KEY_CONTENT or MUTE_KEY_VOLUME

    Returns:
        List of dicts with 'name' and 'expires_at' (None = permanent)
    """
    data = read_config()
    raw = data.get("config", {}).get(key, [])
    now = datetime.now()
    result = []
    for entry in raw:
        if isinstance(entry, str):
            result.append({"name": _normalize_branch_name(entry), "expires_at": None})
        elif isinstance(entry, dict):
            expires_at = entry.get("expires_at")
            if expires_at is None or datetime.fromisoformat(expires_at) > now:
                result.append(
                    {
                        "name": _normalize_branch_name(entry.get("name", "")),
                        "expires_at": expires_at,
                    }
                )
    return result


def get_muted_branches() -> List[str]:
    """
    Get list of currently active CONTENT-muted branch names.

    Evaluates TTL expiry on read — expired mutes are filtered out.

    Returns:
        List of muted branch names (lowercase, e.g., ['speakeasy', 'api'])
    """
    return [m["name"] for m in _get_muted_detail_for(MUTE_KEY_CONTENT)]


def get_muted_branches_detail() -> List[Dict[str, Any]]:
    """
    Get CONTENT-muted branches with expiry info for status display.

    Returns active mutes only (expired ones filtered out).

    Returns:
        List of dicts with 'name' and 'expires_at' (None = permanent)
    """
    return _get_muted_detail_for(MUTE_KEY_CONTENT)


def get_volume_muted_branches() -> List[str]:
    """
    Get list of currently active VOLUME-muted branch names.

    Volume mutes gate runaway_log_detected alerts only — they are independent
    of the content mutes used by the medic error pipeline.

    Returns:
        List of volume-muted branch names (lowercase)
    """
    return [m["name"] for m in _get_muted_detail_for(MUTE_KEY_VOLUME)]


def get_volume_muted_branches_detail() -> List[Dict[str, Any]]:
    """
    Get VOLUME-muted branches with expiry info for status display.

    Returns:
        List of dicts with 'name' and 'expires_at' (None = permanent)
    """
    return _get_muted_detail_for(MUTE_KEY_VOLUME)


def _mute_entry_name(entry) -> str:
    """Extract the normalized branch name from a mute entry (string or dict)."""
    if isinstance(entry, str):
        return _normalize_branch_name(entry)
    if isinstance(entry, dict):
        return _normalize_branch_name(entry.get("name", ""))
    return ""


def _mute_branch_in(key: str, branch_name: str, duration_seconds: Optional[float] = None) -> bool:
    """
    Add a branch to one mute class with optional TTL.

    Args:
        key: Config key — MUTE_KEY_CONTENT or MUTE_KEY_VOLUME
        branch_name: Branch name (with or without @)
        duration_seconds: TTL in seconds (None = permanent/forever)

    Returns:
        True on success
    """
    clean = _normalize_branch_name(branch_name)
    with json_file_lock(MEDIC_STATE_FILE):
        data = read_config()
        if "config" not in data:
            data["config"] = {}
        raw_muted = data["config"].get(key, [])
        new_muted = [e for e in raw_muted if _mute_entry_name(e) != clean]
        if duration_seconds is not None:
            expires = datetime.now() + timedelta(seconds=duration_seconds)
            new_muted.append({"name": clean, "expires_at": expires.isoformat()})
        else:
            new_muted.append({"name": clean, "expires_at": None})
        data["config"][key] = new_muted
        data["timestamp"] = datetime.now().strftime("%Y-%m-%d")
        return write_config(data)


def _unmute_branch_in(key: str, branch_name: str) -> bool:
    """
    Remove a branch from one mute class.

    Args:
        key: Config key — MUTE_KEY_CONTENT or MUTE_KEY_VOLUME
        branch_name: Branch name (with or without @)

    Returns:
        True on success
    """
    clean = _normalize_branch_name(branch_name)
    with json_file_lock(MEDIC_STATE_FILE):
        data = read_config()
        if "config" not in data:
            data["config"] = {}
        raw_muted = data["config"].get(key, [])
        data["config"][key] = [e for e in raw_muted if _mute_entry_name(e) != clean]
        data["timestamp"] = datetime.now().strftime("%Y-%m-%d")
        return write_config(data)


def mute_branch(branch_name: str, duration_seconds: Optional[float] = None) -> bool:
    """
    Add a branch to the CONTENT muted list with optional TTL.

    Muted branches will have errors detected but NOT dispatched. Does NOT
    gate runaway (volume) alerts — use mute_branch_volume for those.
    Persists in medic_state.json.

    Args:
        branch_name: Branch name (with or without @)
        duration_seconds: TTL in seconds (None = permanent/forever)

    Returns:
        True on success
    """
    return _mute_branch_in(MUTE_KEY_CONTENT, branch_name, duration_seconds)


def unmute_branch(branch_name: str) -> bool:
    """
    Remove a branch from the CONTENT muted list.

    Args:
        branch_name: Branch name (with or without @)

    Returns:
        True on success
    """
    return _unmute_branch_in(MUTE_KEY_CONTENT, branch_name)


def mute_branch_volume(branch_name: str, duration_seconds: Optional[float] = None) -> bool:
    """
    Add a branch to the VOLUME muted list with optional TTL.

    Volume mutes silence runaway_log_detected alerts for a branch that is
    knowingly producing heavy log output. CRITICAL-severity runaways still
    bypass this mute — see runaway_handler.

    Args:
        branch_name: Branch name (with or without @)
        duration_seconds: TTL in seconds (None = permanent/forever)

    Returns:
        True on success
    """
    return _mute_branch_in(MUTE_KEY_VOLUME, branch_name, duration_seconds)


def unmute_branch_volume(branch_name: str) -> bool:
    """
    Remove a branch from the VOLUME muted list.

    Args:
        branch_name: Branch name (with or without @)

    Returns:
        True on success
    """
    return _unmute_branch_in(MUTE_KEY_VOLUME, branch_name)


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
                entry = json.loads(lines[-1])
                last_suppressed = entry.get("ts", "unknown")
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
                entry = json.loads(lines[-1])
                last_dispatch = entry.get("ts", "unknown")
    except Exception as exc:
        logger.warning("get_rate_limit_stats failed: %s", exc)
        return {"rate_limited_count": 0, "last_rate_limited": "error reading log"}

    return {
        "rate_limited_count": dispatch_count,
        "last_rate_limited": last_dispatch,
    }
