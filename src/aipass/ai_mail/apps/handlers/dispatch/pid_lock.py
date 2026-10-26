# =================== AIPass ====================
# Name: pid_lock.py
# Description: Process liveness, branch occupancy and the dispatch lock
# Version: 1.2.0
# Created: 2026-10-04
# Modified: 2026-10-25
# =============================================

"""
Process liveness, branch occupancy and the dispatch lock.

Split out of wake.py in leg 13, when wake.py
passed the 1500-line line: these helpers ask the operating system about
processes and own the .dispatch.lock file, and the wake calls them.
Their public names are the interface wake.py imports.
"""

import json
import os
import sys
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

from aipass.prax.apps.modules.logger import system_logger as logger


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


# acquire_lock creates the lock empty (O_CREAT|O_EXCL) and fills it with one
# small json.dump an instant later, so a reader can meet it empty or half
# written. That window is milliseconds; 30 seconds is far past any such write
# and far below a wake's turn, so a corrupt lock older than this is a crashed
# writer's leftover and is reclaimed, and a younger one is held.
_CORRUPT_LOCK_GRACE_SECONDS = 30


def check_lock(branch_path: Path) -> Optional[dict]:
    """Return the lock data while the dispatch lock is held, or None once it is free.

    The one lock check of the wake. A holder
    that is dead, a linux zombie included, frees the lock and it is removed.
    A corrupt lock is removed only past _CORRUPT_LOCK_GRACE_SECONDS; younger,
    and a lock that cannot be read at all, answer held with a "corrupt" or
    "unreadable" key in place of the pid.
    """
    lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
    try:
        text = lock_file.read_text(encoding="utf-8")
        age = time.time() - lock_file.stat().st_mtime
    except FileNotFoundError:
        return None
    except OSError as e:
        logger.warning("[pid_lock] Unreadable lock %s, treated as held: %s", lock_file, e)
        return {"unreadable": str(e)}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.info("[pid_lock] Lock at %s is not JSON: %s", lock_file, e)
        data = None
    if not isinstance(data, dict):
        if age > _CORRUPT_LOCK_GRACE_SECONDS:
            logger.warning("[pid_lock] Corrupt lock removed at %s (age %.0fs)", lock_file, age)
            lock_file.unlink(missing_ok=True)
            return None
        logger.info("[pid_lock] Corrupt lock at %s is %.0fs old, held as mid-write", lock_file, age)
        return {"corrupt": True}
    pid = data.get("pid")
    if isinstance(pid, int) and check_pid_alive(pid):
        return data
    logger.warning("[pid_lock] Stale lock removed at %s (PID %s not running)", lock_file, pid)
    lock_file.unlink(missing_ok=True)
    return None


def acquire_lock(branch_path: Path, pid: int) -> Tuple[bool, str]:
    """Acquire dispatch lock for branch. Atomic creation."""
    lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
    lock_data = {"pid": pid, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "branch": str(branch_path)}
    try:
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            json.dump(lock_data, f, indent=2)
        return True, "Lock acquired"
    except FileExistsError as e:
        logger.warning("[wake] Lock file already exists at %s: %s", lock_file, e)
        return False, "Lock file already exists"
    except OSError as e:
        logger.warning("[wake] Lock acquisition failed at %s: %s", lock_file, e)
        return False, f"Lock failed: {e}"


def _get_pid_cwd(pid_str: str) -> Optional[str]:
    """Get the cwd of a process. Cross-platform: Linux /proc, macOS lsof."""
    if sys.platform == "linux":
        try:
            return os.readlink(f"/proc/{pid_str}/cwd")
        except (OSError, PermissionError):
            logger.info("[wake] Cannot read cwd for PID %s", pid_str)
            return None
    if sys.platform == "darwin":
        return _get_pid_cwd_darwin(pid_str)
    logger.info("[wake] Cannot determine cwd for PID %s on %s", pid_str, sys.platform)
    return None


def _get_pid_cwd_darwin(pid_str: str) -> Optional[str]:
    """macOS: get process cwd via lsof."""
    try:
        result = subprocess.run(
            ["lsof", "-a", "-p", pid_str, "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        logger.info("[wake] Cannot read cwd for PID %s on macOS", pid_str)
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.strip().split("\n"):
        if line.startswith("n/"):
            return line[1:]
    return None


def _read_session_type(pid_str: str) -> str:
    """Read AIPASS_SESSION_TYPE from process environment. Returns 'interactive' if unset."""
    if sys.platform == "linux":
        try:
            with open(f"/proc/{pid_str}/environ", "rb") as f:
                data = f.read()
            for entry in data.split(b"\0"):
                if entry.startswith(b"AIPASS_SESSION_TYPE="):
                    return entry.split(b"=", 1)[1].decode("utf-8")
        except (OSError, PermissionError):
            logger.info("[wake] Cannot read session type for PID %s", pid_str)
        return "interactive"
    if sys.platform == "darwin":
        return _read_session_type_darwin(pid_str)
    return "interactive"


def _read_session_type_darwin(pid_str: str) -> str:
    """macOS: read AIPASS_SESSION_TYPE from ps environment output."""
    try:
        result = subprocess.run(
            ["ps", "-p", pid_str, "-wwE", "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        logger.info("[wake] Cannot read session type for PID %s on macOS", pid_str)
        return "interactive"
    if result.returncode != 0:
        return "interactive"
    for token in result.stdout.split():
        if token.startswith("AIPASS_SESSION_TYPE="):
            return token.split("=", 1)[1]
    return "interactive"


# The agent CLIs a wake can spawn; pgrep reads the pattern as an exact-match regex.
AGENT_PROCESS_NAMES = ("claude", "codex")
AGENT_PROCESS_PATTERN = "|".join(AGENT_PROCESS_NAMES)

# Session types that should NOT block dispatch (idle/background sessions)
_NON_BLOCKING_SESSION_TYPES = {"dispatched", "daemon"}

# Codex subcommands that are never a person's session: the app-server daemon family (spawned by the
# first TUI in a folder, parented by systemd --user, outliving every room) and headless `exec`.
# codex-code-mode-host never reaches here: its comm is not `codex`, so pgrep -x skips it.
CODEX_NON_SESSION_SUBCOMMANDS = frozenset({"app-server", "mcp-server", "exec"})


def _read_argv(pid_str: str) -> List[str]:
    """A process's argv. Raises OSError when it cannot be read (gone, foreign, or no reader on this OS)."""
    if sys.platform == "linux":
        with open(f"/proc/{pid_str}/cmdline", "rb") as f:
            raw = f.read()
        return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["ps", "-p", pid_str, "-ww", "-o", "command="], capture_output=True, text=True, timeout=5
            )
        except subprocess.SubprocessError as e:
            raise OSError(f"ps could not read PID {pid_str}: {e}") from e
        if result.returncode != 0:
            raise OSError(f"ps found no PID {pid_str}")
        return result.stdout.split()
    raise OSError(f"no argv reader on {sys.platform}")


def _is_codex_non_session(pid_str: str) -> bool:
    """True for a codex process whose first argument is a non-session subcommand.

    An unreadable argv counts as a session: refusing a wake is safer than spawning beside a live one.
    """
    try:
        argv = _read_argv(pid_str)
    except OSError as e:
        logger.info("[wake] Cannot read argv for codex PID %s, counted as a session: %s", pid_str, e)
        return False
    return len(argv) > 1 and argv[1] in CODEX_NON_SESSION_SUBCOMMANDS


def branch_occupant(branch_path: Path) -> Optional[str]:
    """The CLI ("claude" or "codex") of an interactive session in this branch directory, or None."""
    resolved = str(branch_path.resolve())
    try:
        # -l prints "<pid> <comm>": the comm is what matched, so it names the CLI.
        result = subprocess.run(["pgrep", "-l", "-x", AGENT_PROCESS_PATTERN], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return None
        for line in result.stdout.strip().split("\n"):
            fields = line.split()
            if not fields:
                continue
            pid_str = fields[0]
            cli = fields[1] if len(fields) > 1 else "agent"
            cwd = _get_pid_cwd(pid_str)
            if cwd is None or str(Path(cwd).resolve()) != resolved:
                continue
            if _read_session_type(pid_str) in _NON_BLOCKING_SESSION_TYPES:
                continue
            if cli == "codex" and _is_codex_non_session(pid_str):
                continue
            return cli
    except (subprocess.SubprocessError, OSError):
        logger.info("[wake] Failed to check branch occupancy")
    return None


def clean_zombies() -> int:
    """Find and report zombie Claude processes. Returns count found."""
    count = 0
    try:
        result = subprocess.run(["ps", "-eo", "pid,stat,comm"], capture_output=True, text=True, timeout=5)
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 3 and parts[2] in AGENT_PROCESS_NAMES and "Z" in parts[1]:
                count += 1
                logger.info("[wake] Found zombie Claude process PID %s", parts[0])
    except (subprocess.SubprocessError, OSError):
        logger.info("[wake] Failed to check for zombie processes")
    return count


def check_pid_alive(pid: int) -> bool:
    """Check if a process is alive (not zombie)."""
    if sys.platform == "win32":
        try:
            return _pid_alive_windows(pid)
        except Exception as exc:
            logger.info("[wake] PID %s Windows check failed (assuming alive): %s", pid, exc)
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError as exc:
        logger.warning("[wake] PID %s not found: %s", pid, exc)
        return False
    except PermissionError as exc:
        logger.warning("[wake] PID %s permission denied: %s", pid, exc)
        return True
    except OSError as exc:
        logger.warning("[wake] PID %s os.kill error (assuming dead): %s", pid, exc)
        return False
    if sys.platform == "linux" and _is_zombie_linux(pid):
        return False
    return True


def _is_zombie_linux(pid: int) -> bool:
    """Return True if PID is a zombie (Linux /proc/status check)."""
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("State:"):
                    return "Z" in line
    except FileNotFoundError as exc:
        logger.warning("[wake] PID %s /proc not found: %s", pid, exc)
    return False
