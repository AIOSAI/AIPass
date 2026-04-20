# =================== AIPass ====================
# Name: agent.py
# Description: Watchdog Agent Handler — block until dispatched agent exits
# Version: 1.0.0
# Created: 2026-04-14
# Modified: 2026-04-14
# =============================================

# Signal choice: ai_mail dispatch lock file polling.
#
# When ai_mail dispatches an agent, dispatch_monitor.py creates
# branch_path/.ai_mail.local/.dispatch.lock containing the monitor PID,
# and ALWAYS deletes it on exit (success OR crash). So the lock
# file's existence is the agent's liveness signal — OS-level, crash-aware,
# template-independent. We poll for: (a) lock file gone, OR (b) monitor
# PID dead. Crash vs success is distinguished by the presence of
# .ai_mail.local/last_bounce.json which the monitor writes on failure.

"""
Watchdog Agent Handler — block until a dispatched agent process exits.

The whole point: this function returns ONLY when the dispatched agent
has finished, however it finished. The exit is the wake signal — when
this function returns from a `run_in_background: true` invocation,
devpulse wakes.
"""

import json
import os
import sys
import time
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.devpulse.apps.handlers.watchdog import registry as _registry


def _stderr(msg: str) -> None:
    """Write to stderr — visible in debug runs, doesn't pollute stdout capture."""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _find_repo_root(start: Path | None = None) -> Path | None:
    """Walk upward looking for AIPASS_REGISTRY.json. Returns None if not found."""
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "AIPASS_REGISTRY.json").exists():
            return candidate
    return None


def _resolve_branch_path(agent_id: str) -> Path | None:
    """Resolve an `@branch` token (or bare name) to its absolute branch path."""
    repo_root = _find_repo_root()
    if repo_root is None:
        logger.warning("[watchdog.agent] AIPASS_REGISTRY.json not found")
        return None

    registry_file = repo_root / "AIPASS_REGISTRY.json"
    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[watchdog.agent] failed to read registry: %s", exc)
        return None

    target = f"@{agent_id.lstrip('@').lower()}"
    for branch in registry.get("branches", []):
        if branch.get("email", "").lower() == target:
            raw_path = branch.get("path", "")
            path = Path(raw_path)
            if not path.is_absolute():
                path = repo_root / path
            return path if path.exists() else None
    return None


def _is_zombie_linux(pid: int) -> bool:
    """Linux-only zombie check via /proc. Returns True if zombie."""
    try:
        status_text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError as exc:
        logger.info("[watchdog.agent] /proc/%s/status unreadable: %s", pid, exc)
        return False
    for line in status_text.splitlines():
        if line.startswith("State:"):
            return "Z" in line
    return False


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


def _pid_alive(pid: int) -> bool:
    """Return True if the process is alive (not zombie)."""
    if sys.platform == "win32":
        try:
            return _pid_alive_windows(pid)
        except Exception as exc:
            logger.info("[watchdog.agent] PID %s Windows check failed (assuming alive): %s", pid, exc)
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError as exc:
        logger.info("[watchdog.agent] PID %s not found: %s", pid, exc)
        return False
    except PermissionError as exc:
        logger.info("[watchdog.agent] PID %s permission denied (alive): %s", pid, exc)
        return True
    except OSError as exc:
        logger.info("[watchdog.agent] PID %s os.kill error (assuming dead): %s", pid, exc)
        return False
    if sys.platform == "linux" and _is_zombie_linux(pid):
        return False
    return True


def _read_lock(lock_file: Path) -> dict | None:
    """Read lock file, return dict or None on miss/error."""
    if not lock_file.exists():
        return None
    try:
        return json.loads(lock_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[watchdog.agent] could not read lock %s: %s", lock_file, exc)
        return None


def _classify_exit(branch_path: Path, lock_existed: bool) -> tuple[str, str, int | None]:
    """After lock disappears, decide success vs crash.

    Returns (agent_state, reason, exit_code).
    """
    bounce_file = branch_path / ".ai_mail.local" / "last_bounce.json"
    if bounce_file.exists():
        try:
            data = json.loads(bounce_file.read_text(encoding="utf-8"))
            exit_code = data.get("exit_code")
            return (
                "crashed",
                f"agent crashed (last_bounce.json exit_code={exit_code})",
                exit_code if isinstance(exit_code, int) else None,
            )
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[watchdog.agent] bounce file unreadable: %s", exc)
            return ("crashed", "agent crashed (bounce file present, unreadable)", None)

    if not lock_existed:
        return ("completed", "agent finished cleanly", 0)
    return ("completed", "agent finished cleanly (lock removed)", 0)


def watch_agent(
    agent_id: str,
    timeout_seconds: int = 600,
    poll_interval: float = 2.0,
) -> dict:
    """Block until the dispatched agent at `agent_id` exits.

    Args:
        agent_id: Branch token like ``@drone`` (or bare ``drone``).
        timeout_seconds: Maximum wait. Default 10 min — catches crashes + silent-finishes
            fast; long agent watches should pass an explicit ``--timeout``.
        poll_interval: Seconds between checks. Default 2.0.

    Returns:
        dict with keys: woke, reason, elapsed, agent_state, exit_code, agent_id.
        agent_state is one of: "completed", "crashed", "timeout".
    """
    started_at = time.monotonic()
    _stderr(f"[watchdog.agent] watching {agent_id} (timeout={timeout_seconds}s)")
    logger.info("[watchdog.agent] start agent_id=%s timeout=%s", agent_id, timeout_seconds)

    handle = _registry.register(
        "agent",
        metadata={"agent_id": agent_id, "timeout_seconds": timeout_seconds},
    )

    try:
        branch_path = _resolve_branch_path(agent_id)
        if branch_path is None:
            elapsed = int(time.monotonic() - started_at)
            _stderr(f"[watchdog.agent] {agent_id}: branch not found in registry")
            return {
                "woke": False,
                "reason": "agent not found",
                "elapsed": elapsed,
                "agent_state": "timeout",
                "exit_code": None,
                "agent_id": agent_id,
                "handle": handle,
            }

        lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
        initial_lock = _read_lock(lock_file)
        initial_pid = initial_lock.get("pid") if initial_lock else None
        lock_existed_initially = initial_lock is not None

        if not lock_existed_initially:
            _stderr(f"[watchdog.agent] {agent_id}: no active lock — agent already idle")
            elapsed = int(time.monotonic() - started_at)
            state, reason, exit_code = _classify_exit(branch_path, lock_existed=False)
            return {
                "woke": True,
                "reason": f"no active dispatch ({reason})",
                "elapsed": elapsed,
                "agent_state": state,
                "exit_code": exit_code,
                "agent_id": agent_id,
                "handle": handle,
            }

        _stderr(f"[watchdog.agent] {agent_id}: lock present, monitor PID={initial_pid}")

        while True:
            elapsed = time.monotonic() - started_at
            if elapsed >= timeout_seconds:
                _stderr(f"[watchdog.agent] {agent_id}: TIMEOUT after {int(elapsed)}s")
                logger.info("[watchdog.agent] timeout agent_id=%s elapsed=%s", agent_id, int(elapsed))
                return {
                    "woke": False,
                    "reason": f"timeout after {int(elapsed)}s",
                    "elapsed": int(elapsed),
                    "agent_state": "timeout",
                    "exit_code": None,
                    "agent_id": agent_id,
                    "handle": handle,
                }

            if not lock_file.exists():
                _stderr(f"[watchdog.agent] {agent_id}: lock removed — agent done")
                elapsed_int = int(time.monotonic() - started_at)
                state, reason, exit_code = _classify_exit(branch_path, lock_existed=True)
                logger.info("[watchdog.agent] wake agent_id=%s state=%s elapsed=%s", agent_id, state, elapsed_int)
                return {
                    "woke": True,
                    "reason": reason,
                    "elapsed": elapsed_int,
                    "agent_state": state,
                    "exit_code": exit_code,
                    "agent_id": agent_id,
                    "handle": handle,
                }

            if isinstance(initial_pid, int) and not _pid_alive(initial_pid):
                _stderr(
                    f"[watchdog.agent] {agent_id}: monitor PID {initial_pid} dead "
                    f"but lock still present — treating as crash"
                )
                elapsed_int = int(time.monotonic() - started_at)
                state, reason, exit_code = _classify_exit(branch_path, lock_existed=True)
                if state == "completed":
                    state = "crashed"
                    reason = f"monitor PID {initial_pid} dead, lock still present"
                logger.info("[watchdog.agent] wake agent_id=%s state=%s elapsed=%s", agent_id, state, elapsed_int)
                return {
                    "woke": True,
                    "reason": reason,
                    "elapsed": elapsed_int,
                    "agent_state": state,
                    "exit_code": exit_code,
                    "agent_id": agent_id,
                    "handle": handle,
                }

            time.sleep(poll_interval)
    finally:
        _registry.deregister(handle)
