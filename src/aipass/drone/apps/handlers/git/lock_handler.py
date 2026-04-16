# =================== AIPass ====================
# Name: lock_handler.py
# Description: Atomic lock management for git PR workflow
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""
Atomic lock management for git PR workflow.

Provides acquire/release/check/force-unlock operations using an atomic
lockfile (.git_pr.lock) at the repository root. Uses os.open with
O_CREAT | O_EXCL | O_WRONLY for race-free lock acquisition.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler

_LOCK_FILENAME = ".git_pr.lock"
_STALE_THRESHOLD_SECONDS = 600


def find_repo_root() -> Path:
    """Walk up from CWD looking for AIPASS_REGISTRY.json, fallback to git rev-parse."""
    cwd = Path.cwd()
    current = cwd
    while current != current.parent:
        if (current / "AIPASS_REGISTRY.json").exists():
            return current
        current = current.parent

    # Fallback: git rev-parse --show-toplevel
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=str(cwd),
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("find_repo_root: git rev-parse fallback failed, using CWD: %s", exc)

    return cwd


def acquire_lock(branch_name: str) -> dict:
    """Acquire an atomic lock for git PR workflow.

    Uses os.open with O_CREAT | O_EXCL | O_WRONLY for race-free creation.

    Args:
        branch_name: The branch acquiring the lock (e.g. "@api").

    Returns:
        Dict with success (bool) and message (str).
    """
    repo_root = find_repo_root()
    lock_path = repo_root / _LOCK_FILENAME

    lock_data = {
        "branch": branch_name,
        "feature_branch": "",
        "started": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
    }

    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, json.dumps(lock_data, indent=2).encode("utf-8"))
        finally:
            os.close(fd)

        json_handler.log_operation("acquire_lock", {"branch": branch_name})
        logger.info("Lock acquired by %s", branch_name)
        return {"success": True, "message": f"Lock acquired by {branch_name}"}

    except FileExistsError:
        # Lock already held
        holder_info = _read_lock_file(lock_path)
        holder = holder_info.get("branch", "unknown") if holder_info else "unknown"
        msg = f"Lock blocked: already held by {holder}"
        logger.warning(msg)
        return {"success": False, "message": msg}


def release_lock(force: bool = False) -> dict:
    """Release the lock file.

    Args:
        force: If True, remove regardless of PID match.

    Returns:
        Dict with success (bool) and message (str).
    """
    repo_root = find_repo_root()
    lock_path = repo_root / _LOCK_FILENAME

    if not lock_path.exists():
        return {"success": True, "message": "No lock to release"}

    if not force:
        lock_data = _read_lock_file(lock_path)
        if lock_data and lock_data.get("pid") != os.getpid():
            return {
                "success": False,
                "message": (
                    f"Lock held by PID {lock_data.get('pid')}, "
                    f"current PID is {os.getpid()}. Use force=True to override."
                ),
            }

    try:
        lock_path.unlink()
        json_handler.log_operation("release_lock", {"force": force})
        logger.info("Lock released (force=%s)", force)
        return {"success": True, "message": "Lock released"}
    except OSError as exc:
        logger.warning("release_lock: failed to remove lock file: %s", exc)
        return {"success": False, "message": f"Failed to release lock: {exc}"}


def check_lock_status() -> dict:
    """Check the current lock status, including stale and orphan detection.

    Returns:
        Dict with locked, branch, started, pid, stale, orphaned,
        age_seconds, and message.
    """
    repo_root = find_repo_root()
    lock_path = repo_root / _LOCK_FILENAME

    if not lock_path.exists():
        return {
            "locked": False,
            "branch": "",
            "started": "",
            "pid": 0,
            "stale": False,
            "orphaned": False,
            "age_seconds": 0.0,
            "message": "No active lock",
        }

    lock_data = _read_lock_file(lock_path)
    if lock_data is None:
        return {
            "locked": True,
            "branch": "unknown",
            "started": "",
            "pid": 0,
            "stale": False,
            "orphaned": False,
            "age_seconds": 0.0,
            "message": "Lock file exists but is unreadable",
        }

    branch = lock_data.get("branch", "unknown")
    started = lock_data.get("started", "")
    pid = lock_data.get("pid", 0)

    # Calculate age
    age_seconds = 0.0
    stale = False
    if started:
        try:
            start_time = datetime.fromisoformat(started)
            age_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
            stale = age_seconds > _STALE_THRESHOLD_SECONDS
        except (ValueError, TypeError) as exc:
            logger.warning("check_lock_status: could not parse lock start time '%s': %s", started, exc)

    # Check if PID is still alive (orphan detection)
    orphaned = False
    if pid:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            logger.info("check_lock_status: PID %d not found — lock is orphaned", pid)
            orphaned = True
        except PermissionError as exc:
            # Process exists but we can't signal it — not orphaned
            logger.warning("check_lock_status: PID %d exists but permission denied for signal check: %s", pid, exc)

    status = "active"
    if orphaned:
        status = "orphaned"
    elif stale:
        status = "stale"

    message = f"Lock held by {branch} (PID {pid}, {status}, {age_seconds:.0f}s)"
    json_handler.log_operation("check_lock_status", {"status": status, "branch": branch})

    return {
        "locked": True,
        "branch": branch,
        "started": started,
        "pid": pid,
        "stale": stale,
        "orphaned": orphaned,
        "age_seconds": age_seconds,
        "message": message,
    }


def force_unlock() -> dict:
    """Force remove lock file regardless of holder.

    Returns:
        Dict with success (bool) and message (str).
    """
    json_handler.log_operation("force_unlock", {})
    return release_lock(force=True)


def _read_lock_file(lock_path: Path) -> dict | None:
    """Read and parse the lock file. Returns None on failure."""
    try:
        content = lock_path.read_text(encoding="utf-8")
        return json.loads(content)
    except (OSError, json.JSONDecodeError):
        logger.warning("_read_lock_file: could not read or parse lock file %s", lock_path)
        return None
