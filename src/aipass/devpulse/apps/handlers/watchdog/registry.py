# =================== AIPass ====================
# Name: registry.py
# Description: Watchdog Watch Registry — multi-watch tracking + lifecycle
# Version: 1.1.1
# Created: 2026-04-14
# Modified: 2026-10-10
# =============================================

# Storage: .watchdog/watchdog_active.json with atomic write (tmp + os.replace).
# Relocated out of .trinity/ (2026-08-27, File set ruling): .trinity/ holds
# identity and memory only — operational state lives in its own dot-dir.
# Devpulse root resolved same way timer.py does (walk upward to AIPASS_REGISTRY.json).
# Zombie detection reads /proc/<pid>/status on Linux and `ps -o state=` everywhere
# else (FPLAN-0554): os.kill(pid, 0) SUCCEEDS for a zombie, so skipping the check
# off Linux made an exited-but-unreaped pid read alive. Concurrent
# register/deregister uses fcntl.flock for a cross-process write lock.

"""
Watchdog Watch Registry — register/deregister/list/kill active watches.

Public surface:
  register(watch_type, metadata, storage_path=None) -> handle
  deregister(handle, storage_path=None) -> bool
  list_active(storage_path=None, prune_stale=True) -> list[dict]
  is_pid_alive(pid) -> bool
  is_zombie(pid) -> bool
  kill_watch(handle, storage_path=None) -> dict
  kill_all(storage_path=None) -> list[dict]
  default_storage_path() -> Path   (where the registry lives when no storage_path is given)

Registry file schema (version 1):
  {
    "version": 1,
    "watches": [
      {
        "handle": "agent-a1b2c3",
        "type": "agent",
        "started_at": "2026-04-14T18:03:12.123456",
        "started_epoch": 1712345678.9,
        "pid": 12345,
        "metadata": {...}
      },
      ...
    ]
  }
"""

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
from aipass.devpulse.apps.handlers.json import json_handler

try:
    import fcntl  # POSIX advisory locks: absent on Windows, so the lock door reads this, not sys.platform
except ImportError as exc:  # pragma: no cover - the host that lacks it is the Windows runner
    fcntl = None  # type: ignore[assignment]
    logger.info("[watchdog.registry] fcntl absent on this host, registry writes run unlocked: %s", exc)


_STORAGE_FILENAME = "watchdog_active.json"
_STORAGE_VERSION = 1
_HANDLE_HASH_LEN = 6
_KILL_WAIT_SECONDS = 2.0
_KILL_POLL_INTERVAL = 0.1

# Ceiling on the off-Linux ``ps`` probe. It answers in milliseconds on a healthy
# host; the timeout is there so a wedged one cannot hang a liveness check.
_PROBE_TIMEOUT_SECONDS = 5.0


def _devpulse_root() -> Path:
    """The devpulse package dir, derived from ``__file__`` — never from cwd.

    The store is package state, so it lives where the package lives. The old
    walk keyed on AIPASS_REGISTRY.json — machine-local runtime state, absent
    on every fresh checkout — and fell back to Path.cwd(), which planted
    ``.watchdog/`` at whatever directory the process happened to stand in
    (CI's composed runner hands children cwd = repo root; caught by seedgo's
    left-nothing-behind fixture, 2026-08-31). ``__file__`` gives the same
    answer on a dev machine, a fresh checkout, and a dead cwd.
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


class _FileLock:
    """Exclusive lock on a sibling .lock file (fcntl where it exists, no-op without it).

    Using a sibling avoids racing with the atomic replace of the data file:
    if we locked the data file itself, os.replace would swap the inode out
    from under the lock.

    The door is the module-level ``fcntl`` binding, not ``sys.platform``: a test
    that pretends darwin to reach the portable zombie rule must not make a
    Windows host import a module it does not have (CI red on PR #774, run
    38068553235, two rows in test_watchdog_agent.py).
    """

    def __init__(self, storage_path: Path) -> None:
        self._lock_path = storage_path.with_suffix(storage_path.suffix + ".lock")
        self._fh = None

    def __enter__(self) -> "_FileLock":
        # No fcntl (Windows): skip file locking entirely (single-user typical).
        if fcntl is not None:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            # 'a+' so the file is created if missing and lock survives concurrent opens.
            self._fh = open(self._lock_path, "a+", encoding="utf-8")
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if fcntl is not None and self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None


def _generate_handle(watch_type: str) -> str:
    """Generate ``<type>-<6 hex chars>`` — unique-enough for a single-user registry."""
    return f"{watch_type}-{secrets.token_hex(_HANDLE_HASH_LEN // 2)}"


def _is_zombie_linux(pid: int) -> bool | None:
    """Linux-only zombie check via /proc: True only if the state is 'Z'.

    None when /proc has no readable entry for the pid: it vanished between the
    caller's probe and this read, or there is no /proc. That is not an answer
    about the state; the caller decides what a missing entry means.
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

    The trailing ``=`` suppresses the header, so the whole answer is the state
    code: ``Z`` (BSD) or ``Z+``/``Zs`` with the modifier flags appended. False on
    any failure, and a gone pid prints nothing — not-a-zombie is the right
    answer there, because the liveness caller has already proved otherwise.
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

    Linux reads /proc/<pid>/status as the fast path; every other host asks
    ``ps``. This has to be portable, not skipped: ``os.kill(pid, 0)`` SUCCEEDS
    for a zombie, so gating the check on Linux made a killed-but-unreaped pid
    read ALIVE off Linux — ``kill_watch`` then reported killed=False "still
    alive after 2.0s" for a process it had just killed, and a dead watch stayed
    listed (macOS CI 34682737363, FPLAN-0554).
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

    ``"exists"`` when the signal went through, ``"absent"`` when there is no
    such process, ``"foreign"`` when it exists but belongs to another user.
    The two handler answers are words the success path never returns. Never
    called on Windows, where signal 0 terminates the target: the guard raises.
    """
    if sys.platform == "win32":
        raise OSError("signal 0 terminates the target on Windows; is_pid_alive routes Windows to OpenProcess")
    try:
        os.kill(pid, 0)
    except ProcessLookupError as exc:
        logger.info("[watchdog.registry] PID %s not found: %s", pid, exc)
        return "absent"
    except PermissionError as exc:
        # Process exists but is owned by someone else — still "alive".
        logger.info("[watchdog.registry] PID %s permission denied (alive): %s", pid, exc)
        return "foreign"
    return "exists"


def is_pid_alive(pid: int) -> bool:
    """Return True if the process exists and is not a zombie. Windows-safe.

    Off Windows the kernel answers through signal 0: absent is dead, foreign is
    alive, and an existing pid is alive unless ``is_zombie`` reads it as exited
    and unreaped. On Windows the probe is OpenProcess; a probe that raises is a
    defect to see, never a pid to assume alive.
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
    """Register a new watch, return its handle.

    Args:
        watch_type: "agent" | "timer" | "schedule" (any string accepted — caller discipline).
        metadata: arbitrary handler-specific info (agent_id, duration, scheduled_for, ...).
        storage_path: override registry path (tests).

    Returns:
        Handle string like ``agent-a1b2c3``.
    """
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

    with _FileLock(path):
        store = _load_store_unlocked(path)
        # Paranoia: if a handle collision somehow occurs, retry once.
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
    with _FileLock(path):
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
    """Return the active watch list. Optionally prunes entries for dead pids.

    Each returned entry is a shallow copy with a live ``elapsed_seconds`` key
    computed against ``time.time()``.
    """
    path = storage_path or default_storage_path()
    now = time.time()
    pruned_count = 0

    with _FileLock(path):
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
    """Look up ``handle``, SIGTERM its pid, wait briefly for exit, deregister.

    Returns:
        dict with keys ``handle``, ``killed``, ``was_alive``, ``reason``.
    """
    path = storage_path or default_storage_path()
    watch = None
    with _FileLock(path):
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
        # Process didn't exit in the grace window — still deregister so the
        # caller can reclaim the handle; the runaway pid is the caller's
        # problem from here.
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
