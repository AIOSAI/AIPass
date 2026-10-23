# =================== AIPass ====================
# Name: registry.py
# Description: Watchdog Watch Registry — multi-watch tracking + lifecycle
# Version: 1.2.0
# Created: 2026-04-14
# Modified: 2026-10-22
# =============================================

# Operational state lives in .watchdog/, never .trinity/ (identity and memory only).

"""Watchdog Watch Registry — register/deregister/list/kill active watches."""

import json
import os
import secrets
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.devpulse.apps.handlers.file_lock import FileLock
from aipass.devpulse.apps.handlers.json import json_handler


_STORAGE_FILENAME = "watchdog_active.json"
_STORAGE_VERSION = 1
_HANDLE_HASH_LEN = 6
_KILL_WAIT_SECONDS = 2.0
_KILL_POLL_INTERVAL = 0.1

# A wedged host must not hang a liveness check; a healthy ``ps`` answers in milliseconds.
_PROBE_TIMEOUT_SECONDS = 5.0


def _devpulse_root() -> Path:
    """The devpulse package dir, derived from ``__file__`` — never from cwd.

    A cwd answer plants ``.watchdog/`` wherever the process stands (CI hands
    children cwd = repo root); AIPASS_REGISTRY.json is absent on a fresh checkout.
    """
    return Path(__file__).resolve().parents[3]


def default_storage_path() -> Path:
    """Resolve `.watchdog/watchdog_active.json` relative to the devpulse root."""
    return _devpulse_root() / ".watchdog" / _STORAGE_FILENAME


def _empty_store() -> dict:
    return {"version": _STORAGE_VERSION, "watches": []}


def _load_store_unlocked(storage_path: Path) -> dict:
    """Load the registry without locking — caller is responsible for locking."""
    if not storage_path.exists():
        return _empty_store()
    try:
        data = json.loads(storage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[watchdog.registry] could not load %s: %s", storage_path, exc)
        return _empty_store()

    if not isinstance(data, dict):
        return _empty_store()
    data.setdefault("version", _STORAGE_VERSION)
    data.setdefault("watches", [])
    if not isinstance(data["watches"], list):
        data["watches"] = []
    return data


def _atomic_write_unlocked(storage_path: Path, data: dict) -> None:
    """Write via .tmp + os.replace. Caller owns any higher-level locking."""
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = storage_path.with_suffix(storage_path.suffix + ".tmp")
    try:
        tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, storage_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError as exc:
                logger.warning("[watchdog.registry] leftover tmp %s: %s", tmp_path, exc)


def _generate_handle(watch_type: str) -> str:
    """Generate ``<type>-<6 hex chars>`` — unique-enough for a single-user registry."""
    return f"{watch_type}-{secrets.token_hex(_HANDLE_HASH_LEN // 2)}"


def _is_zombie_linux(pid: int) -> bool | None:
    """Linux-only zombie check via /proc: True only if the state is 'Z'.

    None when /proc has no readable entry: not an answer about the state.
    """
    try:
        status_text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError as exc:
        logger.info("[watchdog.registry] /proc/%s/status unreadable: %s", pid, exc)
        return None
    for line in status_text.splitlines():
        if line.startswith("State:"):
            return "Z" in line
    return False


def _is_zombie_ps(pid: int) -> bool:
    """``ps -o state= -p <pid>`` — the portable half of ``is_zombie``.

    The state may carry modifier flags (``Z+``, ``Zs``). A gone pid prints nothing:
    not-a-zombie is right there, as the liveness caller has already proved otherwise.
    """
    try:
        done = subprocess.run(
            ["ps", "-o", "state=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("[watchdog.registry] ps state unusable for pid=%s: %s", pid, exc)
        return False
    return done.stdout.strip().startswith("Z")


def is_zombie(pid: int) -> bool:
    """True if ``pid`` has exited but has not been reaped. False on any error.

    Portable, never Linux-only: ``os.kill(pid, 0)`` SUCCEEDS for a zombie, so a
    killed-but-unreaped pid would read alive and ``kill_watch`` report it unkilled.
    """
    if sys.platform == "linux":
        # A zombie keeps its /proc entry; no entry (None) means gone or reaped, not a zombie.
        return _is_zombie_linux(pid) is True
    return _is_zombie_ps(pid)


def _pid_alive_windows(pid: int) -> bool:
    """Windows-safe liveness via OpenProcess + GetExitCodeProcess (mirrors agent.py)."""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]  # Windows-only
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


def _signal_zero(pid: int) -> str:
    """Probe ``pid`` with signal 0 and name the kernel's answer.

    ``"exists"``, ``"absent"`` or ``"foreign"`` (another user's). Raises on
    Windows, where signal 0 terminates the target.
    """
    if sys.platform == "win32":
        raise OSError("signal 0 terminates the target on Windows; is_pid_alive routes Windows to OpenProcess")
    try:
        os.kill(pid, 0)
    except ProcessLookupError as exc:
        logger.info("[watchdog.registry] PID %s not found: %s", pid, exc)
        return "absent"
    except PermissionError as exc:
        logger.info("[watchdog.registry] PID %s permission denied (alive): %s", pid, exc)
        return "foreign"
    return "exists"


def is_pid_alive(pid: int) -> bool:
    """Return True if the process exists and is not a zombie. Windows-safe.

    A probe that raises is a defect to see, never a pid to assume alive.
    """
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        # os.kill(pid, 0) TERMINATES the target on Windows — use OpenProcess.
        return _pid_alive_windows(pid)
    answer = _signal_zero(pid)
    if answer == "absent":
        return False
    if answer == "foreign":
        return True
    return not is_zombie(pid)


def register(
    watch_type: str,
    metadata: dict | None = None,
    storage_path: Path | None = None,
) -> str:
    """Register a new watch, return its handle (``agent-a1b2c3``)."""
    if not isinstance(watch_type, str) or not watch_type.strip():
        raise ValueError(f"watch_type must be a non-empty string, got {watch_type!r}")

    path = storage_path or default_storage_path()
    handle = _generate_handle(watch_type)
    now_epoch = time.time()
    entry = {
        "handle": handle,
        "type": watch_type,
        "started_at": datetime.fromtimestamp(now_epoch).isoformat(),
        "started_epoch": now_epoch,
        "pid": os.getpid(),
        "metadata": metadata or {},
    }

    with FileLock(path):
        store = _load_store_unlocked(path)
        existing_handles = {w.get("handle") for w in store["watches"]}
        while handle in existing_handles:
            handle = _generate_handle(watch_type)
            entry["handle"] = handle
        store["watches"].append(entry)
        _atomic_write_unlocked(path, store)

    json_handler.log_operation("register_watch", {"watch_type": watch_type})
    logger.info("[watchdog.registry] register type=%s handle=%s pid=%s", watch_type, handle, entry["pid"])
    return handle


def deregister(handle: str, storage_path: Path | None = None) -> bool:
    """Remove ``handle`` from the registry. Returns True if removed, False if missing."""
    if not isinstance(handle, str) or not handle:
        return False

    path = storage_path or default_storage_path()
    with FileLock(path):
        store = _load_store_unlocked(path)
        before = len(store["watches"])
        store["watches"] = [w for w in store["watches"] if w.get("handle") != handle]
        removed = before - len(store["watches"])
        if removed:
            _atomic_write_unlocked(path, store)

    if removed:
        logger.info("[watchdog.registry] deregister handle=%s", handle)
        return True
    logger.info("[watchdog.registry] deregister miss handle=%s", handle)
    return False


def list_active(
    storage_path: Path | None = None,
    prune_stale: bool = True,
) -> list[dict]:
    """Return the active watch list, as copies carrying a live ``elapsed_seconds``; prunes dead pids."""
    path = storage_path or default_storage_path()
    now = time.time()
    pruned_count = 0

    with FileLock(path):
        store = _load_store_unlocked(path)
        if prune_stale:
            survivors = []
            for watch in store["watches"]:
                pid = watch.get("pid")
                if isinstance(pid, int) and is_pid_alive(pid):
                    survivors.append(watch)
                else:
                    pruned_count += 1
            if pruned_count:
                store["watches"] = survivors
                _atomic_write_unlocked(path, store)
        watches = list(store["watches"])

    if pruned_count:
        logger.info("[watchdog.registry] pruned %s stale watches", pruned_count)

    result = []
    for watch in watches:
        entry = dict(watch)
        started_epoch = float(entry.get("started_epoch", now))
        entry["elapsed_seconds"] = max(0, int(now - started_epoch))
        result.append(entry)
    return result


def _lookup(handle: str, storage_path: Path) -> dict | None:
    """Find a watch by handle — caller must already hold the lock."""
    store = _load_store_unlocked(storage_path)
    for watch in store["watches"]:
        if watch.get("handle") == handle:
            return watch
    return None


def kill_watch(handle: str, storage_path: Path | None = None) -> dict:
    """Look up ``handle``, SIGTERM its pid, wait briefly for exit, deregister."""
    path = storage_path or default_storage_path()
    watch = None
    with FileLock(path):
        watch = _lookup(handle, path)

    if watch is None:
        return {
            "handle": handle,
            "killed": False,
            "was_alive": False,
            "reason": "handle not found",
        }

    raw_pid = watch.get("pid")
    if not isinstance(raw_pid, int):
        deregister(handle, storage_path=path)
        return {
            "handle": handle,
            "killed": True,
            "was_alive": False,
            "reason": "no pid recorded — deregistered",
        }
    pid: int = raw_pid
    was_alive = is_pid_alive(pid)

    if not was_alive:
        deregister(handle, storage_path=path)
        return {
            "handle": handle,
            "killed": True,
            "was_alive": False,
            "reason": "pid already dead — deregistered",
        }

    killed = False
    reason = ""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError as exc:
        logger.info("[watchdog.registry] pid %s vanished before SIGTERM: %s", pid, exc)
        deregister(handle, storage_path=path)
        return {
            "handle": handle,
            "killed": True,
            "was_alive": True,
            "reason": "pid vanished before SIGTERM — deregistered",
        }
    except PermissionError as exc:
        logger.warning("[watchdog.registry] SIGTERM pid %s denied: %s", pid, exc)
        return {
            "handle": handle,
            "killed": False,
            "was_alive": True,
            "reason": f"permission denied: {exc}",
        }

    waited = 0.0
    while waited < _KILL_WAIT_SECONDS:
        if not is_pid_alive(pid):
            killed = True
            reason = f"SIGTERM — pid {pid} exited in {waited:.1f}s"
            break
        time.sleep(_KILL_POLL_INTERVAL)
        waited += _KILL_POLL_INTERVAL

    if not killed:
        # Deregister anyway so the handle is reclaimed; the runaway pid is the caller's.
        reason = f"SIGTERM sent but pid {pid} still alive after {_KILL_WAIT_SECONDS}s"

    deregister(handle, storage_path=path)
    logger.info("[watchdog.registry] kill_watch handle=%s killed=%s", handle, killed)
    return {
        "handle": handle,
        "killed": killed,
        "was_alive": True,
        "reason": reason,
    }


def kill_all(storage_path: Path | None = None) -> list[dict]:
    """Kill every active watch. Returns the list of per-watch kill results."""
    path = storage_path or default_storage_path()
    active = list_active(storage_path=path, prune_stale=False)
    results = []
    for watch in active:
        handle = watch.get("handle")
        if not isinstance(handle, str):
            continue
        results.append(kill_watch(handle, storage_path=path))
    return results
