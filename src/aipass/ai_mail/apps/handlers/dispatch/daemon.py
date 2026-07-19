# =================== AIPass ====================
# Name: daemon.py
# Description: Dispatch Daemon Handler
# Version: 1.8.0
# Created: 2026-02-17
# Modified: 2026-02-17
# =============================================

"""
Dispatch Daemon Handler

Polls registered branch inboxes for --dispatch emails and spawns agents.
The daemon IS the continuity - agents are ephemeral, wake-do-exit.

Architecture:
  - Polls every N seconds (configurable via safety_config.json)
  - Spawns via dispatch_monitor wrapper (bounce emails + guaranteed lock cleanup)
  - Enforces: kill switch, max turns, max dispatches/day, lock files
  - Tracks daily dispatch counts per branch
"""

import json
import os
import sys
import time
import signal
import subprocess
from pathlib import Path
from datetime import datetime, date
from typing import Dict, Any, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.dispatch.status import log_dispatch
from aipass.ai_mail.apps.handlers.paths import find_repo_root
from aipass.ai_mail.apps.handlers.dispatch.test_token import scan_and_ack_test_emails
from aipass.ai_mail.apps.handlers.dispatch.wake import DEFAULT_MODEL


# Infrastructure paths
_REPO_ROOT = find_repo_root()
_AI_MAIL_DIR = Path(__file__).resolve().parents[3]  # ai_mail/

# Paths
CONFIG_FILE = _AI_MAIL_DIR / "safety_config.json"
DAEMON_STATE_FILE = _AI_MAIL_DIR / ".ai_mail.local" / "daemon_state.json"
DAEMON_LOG_FILE = _AI_MAIL_DIR / ".ai_mail.local" / "dispatch_daemon.log"
DAEMON_PID_FILE = _AI_MAIL_DIR / ".ai_mail.local" / "daemon.pid"
BRANCH_REGISTRY = _REPO_ROOT / "AIPASS_REGISTRY.json"

# Graceful shutdown
SHUTDOWN = False


def _handle_signal(signum, _frame):
    """Handle shutdown signals for graceful daemon stop."""
    global SHUTDOWN
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    SHUTDOWN = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def _read_json(filepath: Path) -> Optional[Dict[str, Any]]:
    """Read and parse a JSON file, returning None on failure."""
    if not filepath.exists():
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[daemon] Failed to read JSON %s: %s", filepath, e)
        return None


def _write_json(filepath: Path, data: Dict[str, Any]) -> bool:
    """Write data to a JSON file, returning success."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except OSError as e:
        logger.warning("[daemon] Failed to write JSON %s: %s", filepath, e)
        return False


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
    """Return True if the process is alive."""
    if sys.platform == "win32":
        try:
            return _pid_alive_windows(pid)
        except Exception as exc:
            logger.info("[daemon] PID %s Windows check failed (assuming alive): %s", pid, exc)
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError as exc:
        logger.info("[daemon] PID %s not found: %s", pid, exc)
        return False
    except PermissionError as exc:
        logger.info("[daemon] PID %s permission denied (alive): %s", pid, exc)
        return True
    except OSError as exc:
        logger.info("[daemon] PID %s os.kill error (assuming dead): %s", pid, exc)
        return False
    return True


def _check_lock(branch_path: Path) -> Optional[Dict[str, Any]]:
    """Check if branch has an active dispatch lock. Returns lock data or None."""
    lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
    if not lock_file.exists():
        return None
    try:
        with open(lock_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        pid = data.get("pid")
        if pid is not None:
            if _pid_alive(pid):
                return data
            logger.info("Lock PID %s dead — stale lock cleanup needed", pid)
        # Stale lock — check age (10 min timeout)
        ts = data.get("timestamp", "")
        if ts:
            try:
                lock_time = datetime.fromisoformat(ts)
                age = (datetime.now() - lock_time).total_seconds()
                if age > 600:
                    logger.warning("Stale lock removed at %s (PID %s dead, age %.0fs)", lock_file, pid, age)
                    lock_file.unlink(missing_ok=True)
                    return None
            except (ValueError, TypeError):
                logger.info("Unparseable lock timestamp at %s", lock_file)
        # Dead process, remove stale lock
        logger.warning("Stale lock removed at %s (PID %s no longer running)", lock_file, pid)
        lock_file.unlink(missing_ok=True)
        return None
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupt lock file removed at %s", lock_file)
        lock_file.unlink(missing_ok=True)
        return None


def _acquire_lock(branch_path: Path, pid: int) -> tuple[bool, str]:
    """Acquire dispatch lock for branch. Atomic creation via O_CREAT|O_EXCL."""
    lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
    lock_data = {"pid": pid, "timestamp": datetime.now().isoformat(), "branch": str(branch_path)}
    try:
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, json.dumps(lock_data, indent=2).encode("utf-8"))
        finally:
            os.close(fd)
        return True, "Lock acquired"
    except FileExistsError as e:
        logger.warning("[daemon] Lock file already exists at %s: %s", lock_file, e)
        return False, "Lock file already exists"
    except OSError as e:
        logger.warning("[daemon] Lock acquisition failed at %s: %s", lock_file, e)
        return False, f"Lock failed: {e}"


def load_config() -> Dict[str, Any]:
    """Load safety config from JSON file."""
    DEFAULTS = {
        "kill_switch_path": str(_REPO_ROOT / ".aipass" / "autonomous_pause"),
        "poll_interval_seconds": 300,
        "max_depth": 3,
        "max_turns_per_wake": 100,
        "max_dispatches_per_branch_per_day": 10,
        "session_rotation_cycles": 12,
        "cold_start_prompt": "Hi. Check inbox, process new emails, update memories when done.",
        "wake_prompt": "Wake. Check inbox, process new emails, continue work. Update memories when done.",
        "autonomous_branches": [],
    }

    config = _read_json(CONFIG_FILE)
    if config is None:
        return DEFAULTS

    for key, val in DEFAULTS.items():
        if key not in config:
            config[key] = val
    return config


def load_daemon_state() -> Dict[str, Any]:
    """Load daemon state (daily counts, session tracking)."""
    EMPTY_STATE = {"daily_counts": {}, "session_cycles": {}, "date": str(date.today())}

    state = _read_json(DAEMON_STATE_FILE)
    if state is None:
        return EMPTY_STATE

    # Reset counts on new day
    if state.get("date") != str(date.today()):
        state["daily_counts"] = {}
        state["date"] = str(date.today())
    return state


def save_daemon_state(state: Dict[str, Any]) -> None:
    """Persist daemon state to disk."""
    state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not _write_json(DAEMON_STATE_FILE, state):
        logger.info(f"Failed to save daemon state to {DAEMON_STATE_FILE}")


def is_kill_switch_active(config: Dict[str, Any]) -> bool:
    """Check if the system-wide kill switch is engaged."""
    kill_path = Path(config.get("kill_switch_path", str(_REPO_ROOT / ".aipass" / "autonomous_pause")))
    return kill_path.exists()


def _write_pid_file() -> bool:
    """Write current PID to daemon.pid atomically. Returns False if another daemon is running."""
    DAEMON_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(DAEMON_PID_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, str(os.getpid()).encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        logger.info("[daemon] PID file already exists, checking owner")

    # PID file exists — check if the owning process is alive
    try:
        old_pid = int(DAEMON_PID_FILE.read_text().strip())
        if _pid_alive(old_pid):
            logger.info("Another daemon already running (PID %s). Exiting.", old_pid)
            return False
        logger.info("Removing stale PID file (PID %s is dead)", old_pid)
    except (ValueError, OSError):
        logger.info("Corrupt PID file — removing")

    # Stale or corrupt — remove and retry atomically
    DAEMON_PID_FILE.unlink(missing_ok=True)
    try:
        fd = os.open(str(DAEMON_PID_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, str(os.getpid()).encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        logger.info("Another daemon raced us for the PID file. Exiting.")
        return False


def _remove_pid_file() -> None:
    """Remove the daemon PID file on shutdown."""
    try:
        if DAEMON_PID_FILE.exists():
            stored_pid = int(DAEMON_PID_FILE.read_text().strip())
            if stored_pid == os.getpid():
                DAEMON_PID_FILE.unlink(missing_ok=True)
    except (ValueError, OSError) as e:
        logger.warning("[daemon] Error reading PID file, removing: %s", e)
        DAEMON_PID_FILE.unlink(missing_ok=True)


def get_registered_branches() -> list:
    """Load all registered branches from AIPASS_REGISTRY.json."""
    data = _read_json(BRANCH_REGISTRY)
    if data is None:
        return []
    return data.get("branches", [])


def _is_registered_sender(sender: str) -> bool:
    """Check if sender email exists in the branch registry (DPLAN-0159 S2)."""
    registry = _read_json(BRANCH_REGISTRY)
    if registry is None:
        return True  # fail open if registry unreadable
    for branch in registry.get("branches", []):
        if branch.get("email") == sender:
            return True
    return False


def check_inbox_for_dispatch(branch_path: Path) -> Optional[Dict[str, Any]]:
    """
    Check a branch's inbox for unprocessed --dispatch emails.

    Returns the first eligible dispatch email, prioritizing new emails.
    Also retries opened dispatch emails orphaned for >30 min (agent crashed
    before completing).
    """
    inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
    inbox_data = _read_json(inbox_file)
    if inbox_data is None:
        return None

    orphan_threshold_seconds = 1800  # 30 minutes

    # Priority 1: new dispatch emails
    for msg in inbox_data.get("messages", []):
        if msg.get("auto_execute") and msg.get("status") == "new":
            return msg

    # Priority 2: opened dispatch emails orphaned >30 min
    now = datetime.now()
    for msg in inbox_data.get("messages", []):
        if msg.get("auto_execute") and msg.get("status") == "opened":
            ts = msg.get("timestamp", "")
            if not ts:
                continue
            try:
                msg_time = datetime.fromisoformat(ts)
                age = (now - msg_time).total_seconds()
                if age > orphan_threshold_seconds:
                    logger.warning(
                        "Retrying orphaned dispatch email %s (opened %.0f min ago)", msg.get("id", "?"), age / 60
                    )
                    return msg
            except (ValueError, TypeError):
                logger.info("Unparseable timestamp for email %s", msg.get("id", "?"))
                continue
    return None


def spawn_agent(
    branch_path: Path, branch_email: str, message: Dict[str, Any], config: Dict[str, Any], state: Dict[str, Any]
) -> bool:
    """
    Spawn a Claude agent at the target branch via dispatch_monitor wrapper.

    The monitor wraps the claude process, providing:
    - Bounce emails on agent failure (return-to-sender)
    - Guaranteed lock cleanup on exit (agent doesn't need to know about locks)
    - Stderr capture for diagnostics

    Args:
        branch_path: Path to target branch
        branch_email: Branch email (e.g., @flow)
        message: The dispatch email message dict
        config: Safety config
        state: Daemon state (for cycle tracking)

    Returns:
        True if monitor was spawned successfully
    """
    sender = message.get("from", "unknown")
    subject = message.get("subject", "")
    max_turns = config.get("max_turns_per_wake", 100)

    if message.get("auto_execute") and not _is_registered_sender(sender):
        logger.warning("[daemon] Dispatch from unregistered sender %s — rejecting", sender)
        return False

    lock_file_path = str(branch_path / ".ai_mail.local" / ".dispatch.lock")

    # Prompt — only interpolate system-generated metadata (id, sender email).
    # Free-form fields (subject, body) stay in inbox.json (DPLAN-0155 M1).
    msg_id = message.get("id", "")
    safe_id = msg_id if msg_id.isalnum() and len(msg_id) <= 12 else ""
    sender_addr = message.get("from", "")
    safe_sender = sender_addr if sender_addr.startswith("@") and sender_addr[1:].replace("_", "").isalnum() else ""

    if safe_id:
        reply_cmd = f'drone @ai_mail reply {safe_id} "your results summary"'
        reply_instr = f" When done, reply via: {reply_cmd}. This is required — do not skip the reply step."
    else:
        reply_instr = (
            " When done, reply to the dispatch email via drone @ai_mail reply <id> with your results."
            " This is required — do not skip the reply step."
        )

    sender_note = f" Dispatch from {safe_sender}." if safe_sender else ""

    prompt = "Hi. Check inbox, process new emails, update memories when done." + sender_note + reply_instr

    claude_cmd = [
        "claude",
        "-c",
        "-p",
        prompt,
        "--model",
        DEFAULT_MODEL,
        "--max-turns",
        str(max_turns),
        "--permission-mode",
        "bypassPermissions",
        "--output-format",
        "json",
    ]

    # Build monitor command (dispatch_monitor wraps claude, handles bounce + lock cleanup)
    MONITOR_SCRIPT = Path(__file__).resolve().parent / "dispatch_monitor.py"
    LOG_DIR = branch_path / "logs"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STDERR_LOG = str(LOG_DIR / "dispatch_stderr.log")

    monitor_cmd = [
        sys.executable,
        str(MONITOR_SCRIPT),
        branch_email,
        lock_file_path,
        sender,
        STDERR_LOG,
        "--",
        *claude_cmd,
    ]

    spawn_env = os.environ.copy()
    spawn_env["AIPASS_SPAWNED"] = "1"
    spawn_env["AIPASS_SESSION_TYPE"] = "daemon"
    # Strip CLAUDE* vars (prevent nested session) and AIPASS_BOT_ID (prevent log leak to parent chat)
    for key in list(spawn_env.keys()):
        if key.startswith("CLAUDE") or key == "AIPASS_BOT_ID":
            spawn_env.pop(key)

    # Acquire lock BEFORE spawn to prevent TOCTOU race (DPLAN-0155 Phase 5).
    # Use current PID as placeholder; overwrite with monitor PID after spawn.
    acquired, lock_msg = _acquire_lock(branch_path, os.getpid())
    if not acquired:
        logger.info(f"Lock acquisition failed for {branch_email}: {lock_msg}")
        return False

    _detach_kwargs: dict = {}
    if sys.platform == "win32":
        _detach_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        _detach_kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(
            monitor_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(branch_path),
            env=spawn_env,
            **_detach_kwargs,
        )

        monitor_pid = process.pid

        # Update lock with real monitor PID
        lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
        lock_data = {
            "pid": monitor_pid,
            "timestamp": datetime.now().isoformat(),
            "branch": str(branch_path),
            "subject": subject,
        }
        _write_json(lock_file, lock_data)

        # Track session cycles for rotation
        cycles = state.get("session_cycles", {})
        branch_key = str(branch_path)
        cycles[branch_key] = cycles.get(branch_key, 0) + 1
        state["session_cycles"] = cycles

        # Increment daily count
        daily = state.get("daily_counts", {})
        daily[branch_email] = daily.get(branch_email, 0) + 1
        state["daily_counts"] = daily

        # Desktop notification — show who woke and why
        notif_title = f"Daemon → {branch_email}"
        notif_body = f'Task from {sender}: "{subject[:80]}"' if subject else f"Dispatch from {sender}"
        try:
            from aipass.ai_mail.apps.handlers.notify import send_notification

            send_notification(notif_title, notif_body, source=branch_email.lstrip("@"))
        except Exception:
            logger.info(f"Desktop notification unavailable for {branch_email}")

        logger.info(f'SPAWN {branch_email} PID={monitor_pid} (monitor) sender={sender} subject="{subject[:60]}"')
        log_dispatch(branch_email, monitor_pid, "spawned")
        return True

    except Exception as e:
        # Release lock on spawn failure so branch isn't stuck locked
        lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
        lock_file.unlink(missing_ok=True)
        logger.info(f"SPAWN FAILED {branch_email}: {e}")
        log_dispatch(branch_email, None, "failed", error_msg=str(e))
        return False


def is_protected_branch(branch_email: str) -> bool:
    """Check if a branch is protected from auto-dispatch."""
    return branch_email == "@devpulse"


def _get_pid_cwd(pid_str: str) -> Optional[str]:
    """Get the cwd of a process. Cross-platform: Linux /proc, macOS lsof."""
    if sys.platform == "linux":
        try:
            return os.readlink(f"/proc/{pid_str}/cwd")
        except (OSError, PermissionError):
            logger.info("[daemon] Cannot read cwd for PID %s", pid_str)
            return None
    if sys.platform == "darwin":
        return _get_pid_cwd_darwin(pid_str)
    logger.info("[daemon] Cannot determine cwd for PID %s on %s", pid_str, sys.platform)
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
        logger.info("[daemon] Cannot read cwd for PID %s on macOS", pid_str)
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
            logger.info("[daemon] Cannot read session type for PID %s", pid_str)
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
        logger.info("[daemon] Cannot read session type for PID %s on macOS", pid_str)
        return "interactive"
    if result.returncode != 0:
        return "interactive"
    for token in result.stdout.split():
        if token.startswith("AIPASS_SESSION_TYPE="):
            return token.split("=", 1)[1]
    return "interactive"


# Session types that should NOT block dispatch (idle/background sessions)
_NON_BLOCKING_SESSION_TYPES = {"dispatched", "daemon"}


def _is_branch_occupied(branch_path: Path) -> bool:
    """Check if an interactive Claude session is running in this branch."""
    resolved = str(branch_path.resolve())
    try:
        result = subprocess.run(["pgrep", "-x", "claude"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return False
        for pid_str in result.stdout.strip().split("\n"):
            pid_str = pid_str.strip()
            if not pid_str:
                continue
            cwd = _get_pid_cwd(pid_str)
            if cwd is None:
                continue
            if str(Path(cwd).resolve()) == resolved:
                session_type = _read_session_type(pid_str)
                if session_type not in _NON_BLOCKING_SESSION_TYPES:
                    return True
    except Exception:
        logger.info("[daemon] Failed to check branch occupancy for %s", branch_path)
    return False


def poll_cycle(config: Dict[str, Any], state: Dict[str, Any]) -> int:
    """
    Run one poll cycle across all registered branches.

    Returns:
        Number of agents spawned this cycle
    """
    branches = get_registered_branches()
    autonomous_list = config.get("autonomous_branches", [])
    max_daily = config.get("max_dispatches_per_branch_per_day", 10)
    spawned = 0

    for branch in branches:
        if SHUTDOWN:
            break

        branch_email = branch.get("email", "")
        branch_path_str = branch.get("path", "")
        if not branch_email or not branch_path_str:
            continue

        branch_path = Path(branch_path_str)
        if not branch_path.is_absolute():
            branch_path = _REPO_ROOT / branch_path

        if is_protected_branch(branch_email):
            continue

        if autonomous_list and branch_email not in autonomous_list:
            continue

        daily_count = state.get("daily_counts", {}).get(branch_email, 0)
        if daily_count >= max_daily:
            logger.info(f"SKIP {branch_email}: daily limit reached ({daily_count}/{max_daily})")
            continue

        # Intercept AIPASS-TEST ping emails before dispatch scan
        scan_and_ack_test_emails(branch_path, branch_email)

        # Always check/clean stale locks (even without dispatch emails)
        existing_lock = _check_lock(branch_path)
        if existing_lock is not None:
            logger.info(f"SKIP {branch_email}: active lock (PID {existing_lock.get('pid', '?')})")
            continue

        dispatch_msg = check_inbox_for_dispatch(branch_path)
        if dispatch_msg is None:
            continue

        if _is_branch_occupied(branch_path):
            logger.info(f"SKIP {branch_email}: active Claude session detected (email already in inbox)")
            continue

        if spawn_agent(branch_path, branch_email, dispatch_msg, config, state):
            spawned += 1

    return spawned


def run_daemon() -> None:
    """
    Main daemon loop. Polls inboxes at configured interval, spawns agents.

    Exits gracefully on SIGTERM/SIGINT or kill switch.
    """
    json_handler.log_operation("run_daemon", {"pid": os.getpid()})

    if not _write_pid_file():
        return

    logger.info("=" * 60)
    logger.info(f"DISPATCH DAEMON STARTING (PID {os.getpid()})")
    logger.info("=" * 60)

    config = load_config()
    poll_interval = config.get("poll_interval_seconds", 300)

    logger.info(f"Poll interval: {poll_interval}s")
    logger.info(f"Kill switch: {config.get('kill_switch_path')}")
    logger.info(f"Max turns/wake: {config.get('max_turns_per_wake')}")
    logger.info(f"Max dispatches/branch/day: {config.get('max_dispatches_per_branch_per_day')}")

    autonomous = config.get("autonomous_branches", [])
    if autonomous:
        logger.info(f"Autonomous branches: {', '.join(autonomous)}")
    else:
        logger.info("Autonomous branches: ALL (no filter)")

    cycle_count = 0

    while not SHUTDOWN:
        if sys.platform != "win32":
            try:
                while True:
                    pid, _ = os.waitpid(-1, os.WNOHANG)
                    if pid == 0:
                        break
                    logger.info(f"Reaped child process PID {pid}")
            except ChildProcessError:
                logger.info("No child processes to reap")

        if is_kill_switch_active(config):
            logger.info("Kill switch ACTIVE - pausing all dispatches")
            time.sleep(poll_interval)
            continue

        config = load_config()
        poll_interval = config.get("poll_interval_seconds", 300)

        state = load_daemon_state()
        cycle_count += 1

        logger.info(f"--- Poll cycle {cycle_count} ---")

        spawned = poll_cycle(config, state)

        if spawned > 0:
            logger.info(f"Cycle {cycle_count}: spawned {spawned} agent(s)")

        save_daemon_state(state)

        elapsed = 0
        while elapsed < poll_interval and not SHUTDOWN:
            time.sleep(min(5, poll_interval - elapsed))
            elapsed += 5

    _remove_pid_file()
    logger.info("DISPATCH DAEMON STOPPED")


if __name__ == "__main__":
    run_daemon()
