# =================== AIPass ====================
# Name: instance_lock.py
# Description: Single-instance lock for the prax monitor
# Version: 1.1.0
# Created: 2026-07-10
# Modified: 2026-08-02
# =============================================

"""Relay-scoped lock for the prax monitor Telegram relay.

Prevents duplicate Telegram sends when multiple monitor viewers run
concurrently. The display path is never blocked — only the TG relay
acquires this lock, so interactive viewers always start.

Uses a pidfile with liveness check — cross-platform (Linux / macOS / Windows).
Lock file lives in prax_json/relay.pid (outside system_logs/ to avoid
the tailed-directory feedback loop).
"""

import json as _json
import os
import sys
from pathlib import Path
from typing import Optional

from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.prax.apps.handlers.json import json_handler

logger = get_direct_logger()

_lock_path_override: Optional[Path] = None
_held_lock: Optional[Path] = None


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


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive. Cross-platform."""
    if sys.platform == "win32":
        try:
            return _pid_alive_windows(pid)
        except Exception as exc:
            logger.info("[instance_lock] PID %d Windows check failed (assuming alive): %s", pid, exc)
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        logger.info("[instance_lock] PID %d not found", pid)
        return False
    except PermissionError:
        logger.info("[instance_lock] PID %d alive (permission denied on signal)", pid)
        return True
    except OSError as exc:
        logger.info("[instance_lock] os.kill(%d, 0) raised %s", pid, exc)
        return False


def _current_boot_id() -> Optional[str]:
    """Return a stable identifier for the current boot, or None if unavailable.

    Linux exposes /proc/sys/kernel/random/boot_id, which is regenerated on
    every boot. Platforms without it get None, which falls back to plain
    pid-liveness — no regression, just no cross-boot protection.
    """
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip() or None
    except OSError as exc:
        logger.info("[instance_lock] boot_id unavailable, using pid liveness only: %s", exc)
        return None


def get_lock_path() -> Path:
    """Return the path for the relay lock file."""
    if _lock_path_override is not None:
        return _lock_path_override
    return Path(__file__).resolve().parent.parent.parent / "prax_json" / "relay.pid"


def try_acquire() -> bool:
    """Try to acquire the relay lock. Returns True if acquired, False if held by a live process."""
    global _held_lock
    lock_path = get_lock_path()
    json_handler.log_operation("instance_lock_acquire", {"pid": os.getpid()})

    current_boot = _current_boot_id()

    if lock_path.exists():
        try:
            data = _json.loads(lock_path.read_text(encoding="utf-8"))
            existing_pid = data.get("pid", 0)
            existing_boot = data.get("boot_id")

            if existing_boot and current_boot and existing_boot != current_boot:
                # The lock file outlived a reboot. Its PID belongs to the
                # previous boot, but the number may already be reused by an
                # unrelated early-boot process, so a liveness check would
                # wrongly report the relay as held. That stranded the relay in
                # viewer-only mode for 1h51m on 2026-07-31 (pid 1567 reused
                # seconds after boot). A lock from a past boot is always stale.
                logger.info(
                    "[instance_lock] Reclaiming lock from previous boot (PID %d, boot %s != %s)",
                    existing_pid,
                    existing_boot[:8],
                    current_boot[:8],
                )
            elif existing_pid and _is_pid_alive(existing_pid):
                logger.info("[instance_lock] Relay lock held by PID %d — skipping TG relay", existing_pid)
                return False
            else:
                logger.info("[instance_lock] Reclaiming stale lock (PID %d is dead)", existing_pid)
        except (ValueError, OSError) as exc:
            logger.info("[instance_lock] Removing corrupt lock file: %s", exc)

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"pid": os.getpid()}
    if current_boot:
        payload["boot_id"] = current_boot
    lock_path.write_text(_json.dumps(payload), encoding="utf-8")
    _held_lock = lock_path
    logger.info("[instance_lock] Acquired relay lock (PID %d)", os.getpid())
    return True


def release() -> None:
    """Release the single-instance lock file."""
    global _held_lock
    if _held_lock and _held_lock.exists():
        try:
            _held_lock.unlink()
            logger.info("[instance_lock] Released")
        except OSError as exc:
            logger.warning("[instance_lock] Failed to remove lock file: %s", exc)
    _held_lock = None
    json_handler.log_operation("instance_lock_release", {"pid": os.getpid()})
