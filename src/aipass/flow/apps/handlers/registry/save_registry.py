# =================== AIPass ====================
# Name: save_registry.py
# Description: Save Registry Handler
# Version: 1.4.0
# Created: 2025-11-07
# Modified: 2026-10-23
# =============================================

"""Save Registry Handler"""

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Any, Iterator

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.runner.lock_ops import os_file_lock

from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"

MODULE_NAME = "save_registry"
FLOW_JSON_DIR = FLOW_ROOT / "flow_json"
REGISTRY_FILE = FLOW_JSON_DIR / "fplan_registry.json"
LOCK_NAME = ".flow_writes.lock"

# Depth of registry_lock() in this process: nested holders must not wait on themselves.
_LOCK_STATE = {"depth": 0}


@contextmanager
def registry_lock() -> Iterator[None]:
    """Hold flow's one write lock: plan registries, CLOSED_PLANS and PLANS.central. Re-entrant per process.

    One lock for all: a close resolves across several registries and writes all three before it is done.
    Raises TimeoutError when another process keeps it past the timeout.
    """
    if _LOCK_STATE["depth"]:
        _LOCK_STATE["depth"] += 1
        try:
            yield
        finally:
            _LOCK_STATE["depth"] -= 1
        return
    FLOW_JSON_DIR.mkdir(parents=True, exist_ok=True)
    with os_file_lock(FLOW_JSON_DIR / LOCK_NAME):
        _LOCK_STATE["depth"] = 1
        try:
            yield
        finally:
            _LOCK_STATE["depth"] = 0


def save_registry(registry: Dict[str, Any], registry_file: str | None = None) -> bool:
    """Save PLAN registry

    Returns True if saved, False on error (logged). tmp+replace prevents torn reads.
    """
    target = FLOW_JSON_DIR / registry_file if registry_file else REGISTRY_FILE

    try:
        with registry_lock():
            registry["_notice"] = "DO NOT MANUALLY EDIT — managed by flow close pipeline"
            registry["last_updated"] = datetime.now(timezone.utc).isoformat()

            tmp_path = target.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(registry, f, indent=2, ensure_ascii=False)
            os.replace(str(tmp_path), str(target))

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
