# =================== AIPass ====================
# Name: save_registry.py
# Description: Save Registry Handler
# Version: 1.1.0
# Created: 2025-11-07
# Modified: 2025-11-07
# =============================================

"""
Save Registry Handler

Saves the Flow PLAN registry to JSON file with automatic timestamp updates.

Features:
- Saves fplan_registry.json
- Auto-updates last_updated timestamp
- Creates directory if missing
- Graceful error handling
- Reusable across Flow modules

Usage:
    from aipass.flow.apps.handlers.registry.save_registry import save_registry
    registry = {"plans": {}, "next_number": 1}
    save_registry(registry)
"""

import json
import os
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.flow.apps.handlers.json import json_handler

# INFRASTRUCTURE IMPORT PATTERN
from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "save_registry"
FLOW_JSON_DIR = FLOW_ROOT / "flow_json"
REGISTRY_FILE = FLOW_JSON_DIR / "fplan_registry.json"

_LOCK_RETRIES = 10
_LOCK_BACKOFF_BASE = 0.05


def _acquire_lock(lock_path: Path) -> bool:
    """Atomically acquire a lockfile via O_CREAT|O_EXCL with retry+backoff."""
    for attempt in range(_LOCK_RETRIES):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            logger.info("[%s] Lock contention on %s, retry %d", MODULE_NAME, lock_path, attempt + 1)
            time.sleep(_LOCK_BACKOFF_BASE * (2**attempt))
        except OSError as exc:
            logger.warning("[%s] Lock creation failed for %s: %s", MODULE_NAME, lock_path, exc)
            return False
    return False


def _release_lock(lock_path: Path) -> None:
    """Remove lockfile, tolerating already-removed."""
    try:
        lock_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("[%s] Could not release lock %s: %s", MODULE_NAME, lock_path, exc)


# =============================================
# HANDLER FUNCTION
# =============================================


def save_registry(registry: Dict[str, Any], registry_file: str | None = None) -> bool:
    """Save PLAN registry

    Args:
        registry: Dictionary containing registry data
        registry_file: Optional filename (e.g. "fplan_registry.json",
            "dplan_registry.json"). When provided, saves to
            ``FLOW_JSON_DIR / registry_file`` instead of the default
            ``fplan_registry.json``.

    Returns:
        True if save successful, False on error

    Automatically updates the last_updated timestamp before saving.
    Creates the flow_json directory if it doesn't exist.
    Uses a lockfile to serialize concurrent writes and atomic
    tempfile+rename to prevent torn reads.
    """
    target = FLOW_JSON_DIR / registry_file if registry_file else REGISTRY_FILE
    lock_path = target.with_suffix(".lock")

    try:
        FLOW_JSON_DIR.mkdir(parents=True, exist_ok=True)

        if not _acquire_lock(lock_path):
            logger.error("[%s] Could not acquire lock for %s after %d retries", MODULE_NAME, target, _LOCK_RETRIES)
            return False

        try:
            registry["_notice"] = "DO NOT MANUALLY EDIT — managed by flow close pipeline"
            registry["last_updated"] = datetime.now(timezone.utc).isoformat()

            tmp_path = target.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(registry, f, indent=2, ensure_ascii=False)
            os.replace(str(tmp_path), str(target))
        finally:
            _release_lock(lock_path)

        json_handler.log_operation(
            "registry_saved",
            {
                "target_file": target.name,
                "plan_count": len(registry.get("plans", {})),
                "success": True,
            },
        )
        return True
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Failed to save registry to {target}: {e}")
        return False
