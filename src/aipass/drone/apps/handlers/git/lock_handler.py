# =================== AIPass ====================
# Name: lock_handler.py
# Description: Atomic lock management for git PR workflow
# Version: 1.1.5
# Created: 2026-03-17
# Modified: 2026-10-23
# =============================================

"""
Atomic lock management for git PR workflow.
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

# Must match find_registry()'s fallback set, or the two disagree on the root.
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
    OpenProcess (os.kill on win32 calls TerminateProcess — kills the target).

    A check that fails raises (the caller reports "unchecked"); permission denied means alive.
    """
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        logger.info("_pid_alive: PID %s not found", pid)
        return False
    except PermissionError:
        logger.info("_pid_alive: PID %s permission denied (alive)", pid)
        return True
    return True


def find_repo_root() -> Path:
    """Walk up from CWD looking for a *_REGISTRY.json, fallback to git rev-parse.

    Any ``*_REGISTRY.json`` marks a root: external projects name theirs after themselves.
    With no CWD it never answers "unknown" (callers build a lock path from it): it
    uses find_registry's order, AIPASS_HOME then the walk up from this file.
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
        # CI's case: a clean checkout has no registry (gitignored). Never the deleted cwd.
        for parent in here.parents:
            if any((parent / marker).exists() for marker in _PROJECT_MARKERS):
                return parent
        return here.parent

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


def release_lock(force: bool = False) -> dict:
    """Release the lock file; *force* removes it regardless of PID match."""
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

    A held lock carries pid_checked: False means status "unchecked", never active or orphaned.
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

    age_seconds = 0.0
    stale = False
    if started:
        try:
            start_time = datetime.fromisoformat(started)
            age_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
            stale = age_seconds > _STALE_THRESHOLD_SECONDS
        except (ValueError, TypeError) as exc:
            logger.warning("check_lock_status: could not parse lock start time '%s': %s", started, exc)

    orphaned = False
    pid_checked = True
    try:
        alive = _pid_alive(pid) if pid else True
    except (OSError, AttributeError) as exc:
        # Neither active nor orphaned: whether the holder lives is unknown.
        logger.warning("check_lock_status: could not check PID %s: %s", pid, exc)
        alive, pid_checked = True, False
    if not alive:
        logger.info("check_lock_status: PID %d not alive — lock is orphaned", pid)
        orphaned = True

    status = "active"
    if not pid_checked:
        status = "unchecked"
    elif orphaned:
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
        "pid_checked": pid_checked,
        "age_seconds": age_seconds,
        "message": message,
    }


def force_unlock() -> dict:
    """Force remove lock file regardless of holder."""
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
