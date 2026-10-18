# =================== AIPass ====================
# Name: save_registry.py
# Description: Save Registry Handler
# Version: 1.3.0
# Created: 2025-11-07
# Modified: 2026-10-17
# =============================================

"""Save Registry Handler"""

import json
import os
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.flow.apps.handlers.json import json_handler

from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"

MODULE_NAME = "save_registry"
FLOW_JSON_DIR = FLOW_ROOT / "flow_json"
REGISTRY_FILE = FLOW_JSON_DIR / "fplan_registry.json"

_LOCK_RETRIES = 10
_LOCK_BACKOFF_BASE = 0.05


def _sleep(seconds: float) -> None:
    """time.sleep(seconds), the lock backoff's wait.

    Tests patch this name so the backoff skips waiting without patching time.sleep globally.
    """
    time.sleep(seconds)


def _create_exclusive(lock_path: Path) -> int:
    """os.open(lock_path, O_CREAT | O_EXCL | O_WRONLY): the lock's one create.

    Tests inject Windows' delete-pending PermissionError here instead of patching os.open.
    """
    return os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)


def _acquire_lock(lock_path: Path) -> bool:
    """Atomically acquire a lockfile via O_CREAT|O_EXCL with retry+backoff.

    Returns: True once acquired; False only when the budget runs out on contention.
    Raises: PermissionError (chained) if the last attempt was denied; any other OSError at once.
    """
    denial: PermissionError | None = None
    waited = 0.0
    for attempt in range(_LOCK_RETRIES):
        try:
            fd = _create_exclusive(lock_path)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            denial = None
            logger.info("[%s] Lock contention on %s, retry %d", MODULE_NAME, lock_path, attempt + 1)
        except PermissionError as exc:
            denial = exc
            logger.info(
                "[%s] Lock denied on %s (delete-pending?), retry %d: %s", MODULE_NAME, lock_path, attempt + 1, exc
            )
        except OSError as exc:
            # False would read as a spent retry budget, so other OSErrors propagate.
            logger.warning("[%s] Lock creation failed for %s: %s", MODULE_NAME, lock_path, exc)
            raise
        delay = _LOCK_BACKOFF_BASE * (2**attempt)
        _sleep(delay)
        waited += delay
    if denial is not None:
        raise PermissionError(
            f"Lock {lock_path} still denied after {_LOCK_RETRIES} attempts ({waited:.2f}s waited)"
        ) from denial
    return False


def _release_lock(lock_path: Path) -> None:
    """Remove lockfile, tolerating already-removed."""
    try:
        lock_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("[%s] Could not release lock %s: %s", MODULE_NAME, lock_path, exc)


def save_registry(registry: Dict[str, Any], registry_file: str | None = None) -> bool:
    """Save PLAN registry

    Returns True if saved, False on error (logged). Lockfile serializes writers; tmp+replace prevents torn reads.
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
        logger.error("[%s] Failed to save registry to %s: %s", MODULE_NAME, target, e, exc_info=True)
        return False
