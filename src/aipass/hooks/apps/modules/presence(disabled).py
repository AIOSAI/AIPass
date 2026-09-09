# =================== AIPass ====================
# Name: presence(disabled).py
# Version: 1.0.1
# Description: RETIRED 2026-09-07 (FPLAN-0495 item 4) — superseded by cc_sessions.py
# Branch: hooks
# Layer: apps/modules
# Created: 2026-06-29
# Modified: 2026-09-07
# =============================================

"""RETIRED. Branch presence service for concurrent session detection.

Disabled 2026-09-07 (FPLAN-0495 item 4). PRESENCE.central.json has not been
written since 2026-06-30; cc_sessions.py reads CC's own ~/.claude/sessions/<pid>.json
instead, which is resume-aware and exit-aware. claim/release/refresh had zero
production callers, and `drone @hooks presence` was still rendering the frozen
June records as a live roster. The one part that was live — resolve_session_pid
and its two helpers — moved to cc_sessions.py, which presence_gate now calls.

The "(disabled)" name is what retires it: drone auto-discovers apps/modules/*.py
by module name, and this one no longer imports. Archive after a session cycle
proves nothing was connected.

Manages a shared PRESENCE.central.json in .ai_central/ at the AIPass project root.
Each branch can claim presence (one live session per branch), detect stale holders
via PID liveness + /proc/cwd verification, and release on exit.

File locking uses flock (POSIX) / msvcrt (Windows) to prevent concurrent corruption.
"""

import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

# Cross-platform flock
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _find_ai_central() -> Path:
    """Walk up from this file to find the directory containing .ai_central/."""
    current = Path(__file__).resolve().parent
    for _ in range(20):  # safety cap
        candidate = current / ".ai_central"
        if candidate.is_dir():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    raise FileNotFoundError("Cannot locate .ai_central/ directory from presence module")


_PRESENCE_FILE_NAME = "PRESENCE.central.json"
_LOCK_FILE_NAME = ".presence.lock"


def _presence_path() -> Path:
    """Return path to the PRESENCE.central.json file."""
    return _find_ai_central() / _PRESENCE_FILE_NAME


def _lock_path() -> Path:
    """Return path to the .presence.lock file."""
    return _find_ai_central() / _LOCK_FILE_NAME


# ---------------------------------------------------------------------------
# File locking context manager
# ---------------------------------------------------------------------------


def _release_lock_fd(lock_fd) -> None:
    """Release and close a lock file descriptor."""
    try:
        if sys.platform == "win32":
            msvcrt.locking(lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()
    except Exception as exc:
        logger.warning("[PRESENCE] lock release failed: %s", exc)
        try:
            lock_fd.close()
        except Exception as close_exc:
            logger.warning("[PRESENCE] lock file close failed: %s", close_exc)


@contextmanager
def _presence_lock():
    """Acquire exclusive lock on the presence file for read-modify-write."""
    lock_file = _lock_path()
    lock_fd = None
    try:
        lock_fd = open(lock_file, "w", encoding="utf-8")
        if sys.platform == "win32":
            msvcrt.locking(lock_fd.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if lock_fd is not None:
            _release_lock_fd(lock_fd)


# ---------------------------------------------------------------------------
# JSON read/write helpers
# ---------------------------------------------------------------------------


def _read_presence() -> dict:
    """Read the presence JSON. Returns empty dict if missing or corrupt."""
    fp = _presence_path()
    if not fp.exists():
        return {}
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[PRESENCE] Failed to read %s: %s", fp, exc)
        return {}


def _write_presence(data: dict) -> None:
    """Write the presence JSON."""
    fp = _presence_path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Session PID resolution
# ---------------------------------------------------------------------------


def _read_proc_comm(pid: int) -> str:
    """Read /proc/<pid>/comm. Returns empty string on failure."""
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.info("[PRESENCE] Cannot read /proc/%d/comm: %s", pid, exc)
        return ""


def _read_proc_ppid(pid: int) -> int | None:
    """Read PPid from /proc/<pid>/status. Returns None on failure."""
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except OSError as exc:
        logger.info("[PRESENCE] Cannot read /proc/%d/status: %s", pid, exc)
    return None


def _get_ppid_portable(pid: int) -> int | None:
    """Get parent PID portably (Linux + macOS). Returns None on failure."""
    import subprocess as _sp

    try:
        result = _sp.run(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip())
    except (OSError, ValueError, _sp.TimeoutExpired) as exc:
        logger.info("[PRESENCE] ppid lookup failed for PID %d: %s", pid, exc)
    return None


def _has_session_file(pid: int) -> bool:
    """Check if ~/.claude/sessions/<pid>.json exists."""
    return (Path.home() / ".claude" / "sessions" / f"{pid}.json").is_file()


def _resolve_session_pid() -> int | None:
    """Walk the parent process chain to find the persistent claude session PID.

    The hook runs as an ephemeral subprocess — os.getpid() gives a PID that dies
    in milliseconds. The owning claude session is an ancestor that owns a
    ~/.claude/sessions/<pid>.json file (CC binary is version-named, so comm
    matching is unreliable).
    """
    pid = os.getpid()
    ancestors = []
    for _ in range(12):
        ancestors.append(str(pid))
        if _has_session_file(pid):
            logger.info("[PRESENCE] Resolved session PID: %d (chain: %s)", pid, " -> ".join(ancestors))
            return pid
        ppid = _get_ppid_portable(pid)
        if not ppid or ppid == pid or ppid <= 1:
            break
        pid = ppid
    logger.info("[PRESENCE] No session-file ancestor found (chain: %s)", " -> ".join(ancestors))
    return None


# ---------------------------------------------------------------------------
# Liveness detection
# ---------------------------------------------------------------------------


def _pid_alive_windows(pid: int) -> bool:
    """Windows-safe liveness check via OpenProcess + GetExitCodeProcess."""
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


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID exists."""
    if sys.platform == "win32":
        try:
            return _pid_alive_windows(pid)
        except Exception as exc:
            logger.info("[PRESENCE] PID %d Windows check failed (assuming alive): %s", pid, exc)
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        logger.info("[PRESENCE] PID %d not found (dead)", pid)
        return False
    except PermissionError:
        logger.info("[PRESENCE] PID %d exists but permission denied — treating as alive", pid)
        return True
    except OSError as exc:
        logger.info("[PRESENCE] PID %d os.kill failed: %s — treating as dead", pid, exc)
        return False


def _cwd_matches(pid: int, expected_dir: str) -> bool:
    """Check if the process CWD matches the expected branch directory.

    Linux only — reads /proc/<pid>/cwd.
    On non-Linux platforms, returns True (skip the check, rely on os.kill alone).
    """
    if sys.platform != "linux":
        return True
    try:
        actual_cwd = os.readlink(f"/proc/{pid}/cwd")
        return str(Path(actual_cwd).resolve()) == str(Path(expected_dir).resolve())
    except (OSError, PermissionError):
        logger.info("[PRESENCE] Cannot read /proc/%d/cwd — treating as stale", pid)
        return False


def _is_holder_alive(entry: dict) -> bool:
    """Determine if the holder recorded in the presence entry is still alive.

    A holder is alive if:
      1. The PID exists (os.kill signal 0)
      2. AND the PID's CWD matches the branch work_dir (Linux /proc check)

    If either check fails, the holder is stale and can be reclaimed.
    """
    pid = entry.get("pid")
    if pid is None:
        return False
    if not _is_pid_alive(pid):
        return False
    work_dir = entry.get("work_dir", "")
    if not work_dir:
        return False
    return _cwd_matches(pid, work_dir)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def claim(
    branch: str,
    session_id: str = "",
    session_type: str = "interactive",
    attach_handle: str = "",
) -> dict:
    """Claim presence for a branch.

    Records the persistent claude session PID (resolved via parent chain),
    not the ephemeral hook subprocess PID. Fails OPEN if no claude ancestor found.

    Returns:
        {"status": "ACQUIRED"} on success, or
        {"status": "OCCUPIED", "pid": N, "session_id": "...",
         "work_dir": "...", "session_type": "..."}
        when a live session already owns the branch.
    """
    session_pid = _resolve_session_pid()
    if session_pid is None:
        logger.info("[PRESENCE] No claude session PID resolved — allowing (fail-open)")
        return {"status": "ACQUIRED"}

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    cwd = os.getcwd()

    with _presence_lock():
        data = _read_presence()
        existing = data.get(branch)

        if existing:
            result = _handle_existing(data, existing, branch, session_pid, now, session_id)
            if result is not None:
                return result

        data[branch] = {
            "pid": session_pid,
            "session_id": session_id,
            "work_dir": cwd,
            "session_type": session_type,
            "attach_handle": attach_handle,
            "started": now,
            "last_seen": now,
        }
        _write_presence(data)
        logger.info("[PRESENCE] Acquired %s (session PID %d)", branch, session_pid)
        return {"status": "ACQUIRED"}


def _handle_existing(
    data: dict,
    existing: dict,
    branch: str,
    my_pid: int,
    now: str,
    session_id: str,
) -> dict | None:
    """Handle an existing presence entry. Returns a result dict or None to proceed."""
    holder_pid = existing.get("pid")

    # Re-entry: same PID already holds it
    if holder_pid == my_pid:
        existing["last_seen"] = now
        existing["session_id"] = session_id or existing.get("session_id", "")
        _write_presence(data)
        logger.info("[PRESENCE] Re-entry for %s (PID %d)", branch, my_pid)
        return {"status": "ACQUIRED"}

    # Check if the holder is still alive
    if _is_holder_alive(existing):
        logger.info(
            "[PRESENCE] %s occupied by PID %d (session_type=%s)",
            branch,
            holder_pid,
            existing.get("session_type", "unknown"),
        )
        return {
            "status": "OCCUPIED",
            "pid": holder_pid,
            "session_id": existing.get("session_id", ""),
            "work_dir": existing.get("work_dir", ""),
            "session_type": existing.get("session_type", ""),
        }

    # Stale holder — let caller reclaim
    logger.info(
        "[PRESENCE] Stale holder for %s (PID %d) — reclaiming",
        branch,
        holder_pid,
    )
    return None


def release(branch: str) -> bool:
    """Release presence for a branch. Only the holder session can release its own entry."""
    session_pid = _resolve_session_pid()
    if session_pid is None:
        logger.info("[PRESENCE] Release skipped for %s — no claude session PID resolved", branch)
        return False
    with _presence_lock():
        data = _read_presence()
        if branch not in data:
            return False
        if data[branch].get("pid") != session_pid:
            logger.info(
                "[PRESENCE] Release skipped for %s — not our session (ours=%d, holder=%d)",
                branch,
                session_pid,
                data[branch].get("pid", 0),
            )
            return False
        del data[branch]
        _write_presence(data)
        logger.info("[PRESENCE] Released %s (session PID %d)", branch, session_pid)
        return True


def refresh(branch: str) -> None:
    """Update last_seen timestamp for the branch entry."""
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with _presence_lock():
        data = _read_presence()
        if branch in data:
            data[branch]["last_seen"] = now
            _write_presence(data)
            logger.info("[PRESENCE] Refreshed %s", branch)


def read_all() -> dict:
    """Return the full presence JSON (all branches)."""
    return _read_presence()


# =============================================================================
# MODULE INTERFACE (drone @hooks routing)
# =============================================================================


def print_introspection() -> None:
    """Print presence state for drone routing."""
    CONSOLE.print("[bold cyan]presence[/bold cyan] Module")
    try:
        data = _read_presence()
        if not data:
            CONSOLE.print("  No branches currently present")
        else:
            for branch, entry in data.items():
                pid = entry.get("pid", "?")
                stype = entry.get("session_type", "unknown")
                last = entry.get("last_seen", "?")
                alive = _is_holder_alive(entry)
                status = "[green]live[/green]" if alive else "[dim]stale[/dim]"
                CONSOLE.print(f"  {branch}: PID {pid}  type={stype}  last_seen={last}  {status}")
    except FileNotFoundError as exc:
        logger.info("[PRESENCE] introspection: %s", exc)
        CONSOLE.print("  .ai_central/ not found")


def handle_command(command: str, args: list) -> bool:
    """Route presence commands from drone @hooks."""
    if command in ("--help", "-h", "help"):
        CONSOLE.print("[bold cyan]presence[/bold cyan] — Branch presence claim/release service")
        CONSOLE.print()
        CONSOLE.print("  drone @hooks presence    Show current presence state for all branches")
        return True

    if command == "presence":
        if not args:
            print_introspection()
            return True
    return False
