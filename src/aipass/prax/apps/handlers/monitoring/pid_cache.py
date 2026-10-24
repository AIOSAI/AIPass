# =================== AIPass ====================
# Name: pid_cache.py
# Description: PID cache for branch-to-agent mapping
# Version: 1.0.0
# Created: 2026-07-10
# Modified: 2026-10-24
# =============================================

"""PID cache — maps branch names to active agent PIDs from dispatch lock files.

The monitor attributes events to the owning agent process through this map.
"""

import json as _json
import sys
import threading
import time as _time
from pathlib import Path
from typing import Optional

from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.repo_root import find_repo_root

logger = get_direct_logger()

_pid_cache: dict[str, int] = {}
_pid_cache_lock = threading.Lock()
_pid_cache_last_refresh: float = 0.0
_PID_CACHE_TTL = 30.0


def parse_lock_pid(branch_entry: dict, new_cache: dict[str, int], repo_root: Path) -> None:
    """Parse a single dispatch lock file and add to cache if PID is live."""
    # Registry paths are repo-relative; an absolute one survives the join unchanged.
    branch_path = repo_root / branch_entry.get("path", "")
    lock_path = branch_path / ".ai_mail.local" / ".dispatch.lock"
    if not lock_path.exists():
        return
    try:
        lock_data = _json.loads(lock_path.read_text(encoding="utf-8"))
        pid = lock_data.get("pid", 0)
        if not pid or not (sys.platform == "linux" and Path(f"/proc/{pid}").exists()):
            return
        name = branch_entry.get("name", "").upper()
        if name:
            new_cache[name] = pid
    except (ValueError, OSError) as e:
        logger.info("[pid_cache] Skipping dispatch lock %s: %s", lock_path, e)


def refresh(repo_root: Optional[Path] = None) -> None:
    """Scan dispatch lock files to build branch-to-PID mapping."""
    global _pid_cache_last_refresh

    now = _time.time()
    with _pid_cache_lock:
        if now - _pid_cache_last_refresh < _PID_CACHE_TTL:
            return
        _pid_cache_last_refresh = now

    try:
        if repo_root is None:
            repo_root = find_repo_root()
        registry_path = repo_root / "AIPASS_REGISTRY.json"
        if not registry_path.exists():
            return
        data = _json.loads(registry_path.read_text(encoding="utf-8"))
        new_cache: dict[str, int] = {}
        for branch in data.get("branches", []):
            parse_lock_pid(branch, new_cache, repo_root)
        with _pid_cache_lock:
            _pid_cache.clear()
            _pid_cache.update(new_cache)
        json_handler.log_operation("pid_cache_refresh", {"count": len(new_cache)})
    except Exception as e:
        logger.info("[pid_cache] Refresh failed: %s", e)


def get_pid_for_branch(branch: str) -> Optional[int]:
    """Look up PID for a branch from the cache."""
    refresh()
    base = branch.upper()
    if base.endswith(" AGENT"):
        base = base[:-6]
    with _pid_cache_lock:
        return _pid_cache.get(base)
