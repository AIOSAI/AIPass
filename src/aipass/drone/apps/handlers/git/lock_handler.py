# =================== AIPass ====================
# Name: lock_handler.py
# Description: Atomic lock management for git PR workflow
# Version: 1.1.1
# Created: 2026-03-17
# Modified: 2026-08-31
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
import sys
from datetime import datetime, timezone
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.router_handler import caller_cwd, registries_in

_LOCK_FILENAME = ".git_pr.lock"
_STALE_THRESHOLD_SECONDS = 600

# What marks a project root when no registry file exists to mark it — the same
# set find_registry() falls back to, because a second opinion on "where is the
# root" is how two answers to one question start disagreeing.
_PROJECT_MARKERS = (".git", "pyproject.toml", "setup.py", "setup.cfg")


def _pid_alive_windows(pid: int) -> bool:
    """Windows-safe liveness check via OpenProcess + GetExitCodeProcess."""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    """Return True if the process is alive. Platform-guarded: Windows uses
    OpenProcess (os.kill on win32 calls TerminateProcess — kills the target)."""
    if sys.platform == "win32":
        try:
            return _pid_alive_windows(pid)
        except Exception as exc:
            logger.info("_pid_alive: PID %s Windows check failed (assuming alive): %s", pid, exc)
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        logger.info("_pid_alive: PID %s not found", pid)
        return False
    except PermissionError:
        logger.info("_pid_alive: PID %s permission denied (alive)", pid)
        return True
    except OSError as exc:
        logger.info("_pid_alive: PID %s OSError (assuming dead): %s", pid, exc)
        return False
    return True


def find_repo_root() -> Path:
    """Walk up from CWD looking for a *_REGISTRY.json, fallback to git rev-parse.

    Any ``*_REGISTRY.json`` marks a project root, not just AIPass's own —
    external projects name theirs after themselves (VERA-STUDIO_REGISTRY.json),
    and hardcoding the AIPass name sent them down the toplevel-query fallback
    while registry resolution found the real root, so the two could disagree.

    NO-CWD PATH. This returns ``Path``, not ``Optional[Path]``, so unlike its
    siblings in this sweep it cannot answer "unknown" — callers build a lock
    path out of it. Both location-derived sources lose their starting point at
    once (the walk has nowhere to start, and the toplevel query would be handed
    the same dead directory), so the answer falls to the two sources that never
    needed a location: AIPASS_HOME, then the walk up from this file. That is
    ``find_registry``'s existing precedence, reused rather than re-invented —
    two orders for one question is how the answers start disagreeing.
    """
    cwd = caller_cwd()
    current = cwd
    while current is not None and current != current.parent:
        if registries_in(current):
            return current
        current = current.parent

    if cwd is None:
        aipass_home = os.environ.get("AIPASS_HOME")
        if aipass_home:
            home = Path(aipass_home)
            if home.is_dir() and registries_in(home):
                return home
        here = Path(__file__).resolve()
        for parent in here.parents:
            if registries_in(parent):
                return parent
        # Last resort, and the world CI actually runs in: a clean checkout has
        # no registry anywhere (it is gitignored and machine-local). Marker-based,
        # the same markers find_registry falls back to. Never the deleted
        # directory, which is the one place a lock could not be written.
        for parent in here.parents:
            if any((parent / marker).exists() for marker in _PROJECT_MARKERS):
                return parent
        return here.parent

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
    if pid and not _pid_alive(pid):
        logger.info("check_lock_status: PID %d not alive — lock is orphaned", pid)
        orphaned = True

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
