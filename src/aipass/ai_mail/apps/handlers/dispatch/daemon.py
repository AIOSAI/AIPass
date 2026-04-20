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
from urllib.request import Request, urlopen
from urllib.error import URLError

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.dispatch.status import log_dispatch
from aipass.ai_mail.apps.handlers.paths import find_repo_root


# Infrastructure paths
_REPO_ROOT = find_repo_root()
_AI_MAIL_DIR = Path(__file__).resolve().parents[3]  # ai_mail/

# Paths
CONFIG_FILE = _AI_MAIL_DIR / "safety_config.json"
DAEMON_STATE_FILE = _AI_MAIL_DIR / ".ai_mail.local" / "daemon_state.json"
DAEMON_LOG_FILE = _AI_MAIL_DIR / ".ai_mail.local" / "dispatch_daemon.log"
DAEMON_PID_FILE = _AI_MAIL_DIR / ".ai_mail.local" / "daemon.pid"
BRANCH_REGISTRY = _REPO_ROOT / "AIPASS_REGISTRY.json"

# Telegram notifications (scheduler bot)
SCHEDULER_CONFIG = _REPO_ROOT / ".aipass" / "scheduler_config.json"

# Graceful shutdown
SHUTDOWN = False

# AIPASS-TEST ping token — exact string that marks a test-only email.
# daemon intercepts these before dispatch scan and auto-acks without spawning.
TEST_TOKEN = "[AIPASS-TEST — do not update memories, do not execute, reply 'ack' only]"


def _notify_telegram(message: str) -> bool:
    """Send a notification to Patrick's Telegram via the scheduler bot."""
    try:
        with open(SCHEDULER_CONFIG, "r", encoding="utf-8") as f:
            config = json.load(f)
        bot_token = config["telegram_bot_token"]
        chat_id = config["telegram_chat_id"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        logger.info("Telegram notification skipped (no scheduler config)")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": message}).encode("utf-8")
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except (URLError, Exception):
        logger.info("Telegram notification failed: %s", message[:60])
        return False


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


def _set_session_name(branch_path: Path, name: str) -> bool:
    """Write custom-title to the most recent Claude session JSONL for a branch.

    Claude stores sessions at ~/.claude/projects/{encoded-cwd}/*.jsonl.
    Writing a custom-title entry makes the session identifiable in /resume picker.
    """
    encoded_cwd = str(branch_path).replace("/", "-")
    projects_dir = Path("~/.claude/projects").expanduser() / encoded_cwd
    if not projects_dir.exists():
        return False
    jsonl_files = sorted(projects_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not jsonl_files:
        return False
    latest = jsonl_files[0]
    session_id = latest.stem
    entry = json.dumps({"type": "custom-title", "customTitle": name, "sessionId": session_id})
    try:
        with open(latest, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
        return True
    except OSError as e:
        logger.warning("[daemon] Failed to write session name for %s: %s", branch_path, e)
        return False


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
            try:
                os.kill(pid, 0)
                return data  # Process alive, lock valid
            except ProcessLookupError:
                logger.info("Lock PID %s dead — stale lock cleanup needed", pid)
            except PermissionError as e:
                logger.warning("[daemon] Lock PID %s permission error: %s", pid, e)
                return data  # Process exists, can't signal
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
    """Write current PID to daemon.pid. Returns False if another daemon is running."""
    if DAEMON_PID_FILE.exists():
        try:
            old_pid = int(DAEMON_PID_FILE.read_text().strip())
            try:
                os.kill(old_pid, 0)
                # Process exists — another daemon is running
                logger.info(f"Another daemon already running (PID {old_pid}). Exiting.")
                return False
            except ProcessLookupError:
                # Stale PID file — process is dead, we can take over
                logger.info(f"Removing stale PID file (PID {old_pid} is dead)")
            except PermissionError:
                # Process exists but we can't signal it
                logger.info(f"Another daemon already running (PID {old_pid}, permission denied). Exiting.")
                return False
        except (ValueError, OSError):
            logger.info("Corrupt PID file — removing")

    DAEMON_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    DAEMON_PID_FILE.write_text(str(os.getpid()))
    return True


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
    msg_id = message.get("id", "unknown")
    subject = message.get("subject", "")
    max_turns = config.get("max_turns_per_wake", 100)

    lock_file_path = str(branch_path / ".ai_mail.local" / ".dispatch.lock")

    # Prompt — no lock cleanup instruction (dispatch_monitor handles it)
    prompt = f"Hi. Check inbox for task from {sender} (message ID: {msg_id}). Execute it. Send confirmation when done."

    claude_cmd = [
        "claude",
        "-c",
        "-p",
        prompt,
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

    # Set session name for /resume picker (daemon always uses -c resume)
    spawn_branch_name = branch_email.lstrip("@").upper()
    _set_session_name(branch_path, f"{spawn_branch_name}-daemon")

    try:
        process = subprocess.Popen(
            monitor_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(branch_path),
            env=spawn_env,
        )

        monitor_pid = process.pid

        # Lock PID = monitor PID (stays alive as long as claude does)
        acquired, lock_msg = _acquire_lock(branch_path, monitor_pid)
        if not acquired:
            logger.info(f"Lock acquisition failed after spawn for {branch_email}: {lock_msg}")

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
        _notify_telegram(f"[Dispatch] {branch_email} woke\nTask from {sender}: {subject[:80]}")
        return True

    except Exception as e:
        logger.info(f"SPAWN FAILED {branch_email}: {e}")
        log_dispatch(branch_email, None, "failed", error_msg=str(e))
        _notify_telegram(f"[Dispatch FAILED] {branch_email}\n{type(e).__name__}: {e}")
        return False


def is_protected_branch(branch_email: str) -> bool:
    """Check if a branch is protected from auto-dispatch."""
    return branch_email == "@devpulse"


def _read_session_type(pid_str: str) -> str:
    """Read AIPASS_SESSION_TYPE from /proc/{pid}/environ. Returns 'interactive' if unset."""
    if sys.platform != "linux":
        return "interactive"
    try:
        with open(f"/proc/{pid_str}/environ", "rb") as f:
            data = f.read()
        for entry in data.split(b"\0"):
            if entry.startswith(b"AIPASS_SESSION_TYPE="):
                return entry.split(b"=", 1)[1].decode("utf-8")
    except (OSError, PermissionError):
        logger.info("Cannot read session type for PID %s", pid_str)
    return "interactive"


# Session types that should NOT block dispatch (idle/background sessions)
_NON_BLOCKING_SESSION_TYPES = {"telegram", "dispatched", "daemon"}


def _is_branch_occupied(branch_path: Path) -> bool:
    """
    Check if an interactive Claude session is running in this branch.

    Only interactive sessions block dispatch. Telegram, dispatched, and daemon
    sessions are idle/background and should not prevent new agent spawns.
    """
    resolved = branch_path.resolve()
    try:
        result = subprocess.run(["pgrep", "-x", "claude"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return False

        for pid_str in result.stdout.strip().split("\n"):
            pid_str = pid_str.strip()
            if not pid_str:
                continue
            try:
                if sys.platform != "linux":
                    continue
                cwd = os.readlink(f"/proc/{pid_str}/cwd")
                if Path(cwd).resolve() == resolved:
                    session_type = _read_session_type(pid_str)
                    if session_type not in _NON_BLOCKING_SESSION_TYPES:
                        return True
            except (OSError, PermissionError, ValueError):
                logger.info("Cannot read cwd for PID %s", pid_str)
                continue
    except Exception:
        logger.info("Failed to check branch occupancy for %s", branch_path)
    return False


def _has_test_token(body: str) -> bool:
    """Return True if body contains the AIPASS-TEST token outside a code fence.

    Code-fence-aware: lines between ``` markers are skipped so the token
    inside a quoted example does not trigger auto-ack. Detection is
    case-sensitive and line-anchored (strips whitespace before comparing).
    """
    in_fence = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and stripped == TEST_TOKEN:
            return True
    return False


def _auto_ack_test_email(branch_path: Path, branch_email: str, message: Dict[str, Any]) -> bool:
    """Send an 'ack' reply to a test-token email and close it.

    Runs drone commands with cwd=branch_path so sender identity resolves
    to the target branch, not @ai_mail.

    Returns True if both reply and close succeed.
    """
    msg_id = message.get("id", "")
    sender = message.get("from_email") or message.get("from", "")
    subject = message.get("subject", "")
    if not msg_id or not sender:
        logger.warning("[daemon] _auto_ack_test_email: missing id or sender in message")
        return False

    reply_subject = f"Re: {subject}" if subject else "Re: (no subject)"
    try:
        result = subprocess.run(
            ["drone", "@ai_mail", "email", sender, reply_subject, "ack"],
            cwd=str(branch_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("[daemon] _auto_ack_test_email: reply failed for %s: %s", msg_id, result.stderr)
            return False
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("[daemon] _auto_ack_test_email: reply subprocess error: %s", exc)
        return False

    try:
        result = subprocess.run(
            ["drone", "@ai_mail", "close", msg_id],
            cwd=str(branch_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("[daemon] _auto_ack_test_email: close failed for %s: %s", msg_id, result.stderr)
            return False
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("[daemon] _auto_ack_test_email: close subprocess error: %s", exc)
        return False

    logger.info("[daemon] auto-acked test email %s at %s", msg_id, branch_email)
    return True


def scan_and_ack_test_emails(branch_path: Path, branch_email: str) -> int:
    """Scan a branch inbox for AIPASS-TEST tokens and auto-ack each one.

    Called at the start of poll_cycle per-branch, before check_inbox_for_dispatch,
    so test emails are consumed and never reach the dispatch scanner.

    Returns the count of test emails acked.
    """
    inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
    inbox_data = _read_json(inbox_file)
    if inbox_data is None:
        return 0

    acked = 0
    for msg in inbox_data.get("messages", []):
        if msg.get("status") not in ("new", "opened"):
            continue
        body = msg.get("body", "")
        if _has_test_token(body):
            if _auto_ack_test_email(branch_path, branch_email, msg):
                acked += 1
    return acked


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
    _notify_telegram(f"[Daemon] Started (PID {os.getpid()})")

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
        # Reap zombie children from previously spawned agents
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
    _notify_telegram("[Daemon] Stopped")


if __name__ == "__main__":
    run_daemon()
