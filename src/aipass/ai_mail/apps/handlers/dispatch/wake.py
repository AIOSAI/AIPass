# =================== AIPass ====================
# Name: wake.py
# Description: Manual Branch Wake Handler
# Version: 2.0.0
# Created: 2026-03-02
# Modified: 2026-03-02
# =============================================

"""
Manual Branch Wake Handler

Spawns a Claude agent at a target branch using the same logic as daemon.py
but triggered manually via 'drone wake @branch "optional message"'.

v2.0: Now returns step-by-step status and spawns via dispatch_monitor.py
which handles agent lifecycle (cleanup, bounce emails on failure).
"""

import json
import os
import sys
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple, List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root


# Infrastructure paths
_REPO_ROOT = find_repo_root()
_AI_MAIL_DIR = Path(__file__).resolve().parents[3]  # ai_mail/
CONFIG_FILE = _AI_MAIL_DIR / "safety_config.json"
BRANCH_REGISTRY = _REPO_ROOT / "AIPASS_REGISTRY.json"
PAUSE_FILE = _REPO_ROOT / ".aipass" / "autonomous_pause"
MONITOR_SCRIPT = Path(__file__).parent / "dispatch_monitor.py"

# Default prompt when no custom message provided
DEFAULT_PROMPT = "Hi. Check inbox, process new emails, update memories when done."


# ─── Status Step Tracking ───────────────────────────────

class DispatchStatus:
    """Collects step-by-step status for a dispatch operation."""

    def __init__(self):
        self.steps: List[Tuple[str, str, str]] = []  # (status, label, detail)
        self.success = True

    def ok(self, label: str, detail: str):
        """Record a successful step."""
        self.steps.append(("ok", label, detail))

    def warn(self, label: str, detail: str):
        """Record a warning step."""
        self.steps.append(("warn", label, detail))

    def fail(self, label: str, detail: str):
        """Record a failed step and mark overall success as False."""
        self.steps.append(("fail", label, detail))
        self.success = False

    def info(self, label: str, detail: str):
        """Record an informational step."""
        self.steps.append(("info", label, detail))

    def format(self) -> str:
        """Format all steps as a multi-line status report with icons."""
        icons = {"ok": "✅", "warn": "⚠️", "fail": "❌", "info": "📨"}
        lines = []
        for status, label, detail in self.steps:
            icon = icons.get(status, "·")
            lines.append(f"{icon} {label} → {detail}")
        return "\n".join(lines)

    @property
    def summary(self) -> str:
        """Single-line summary from last step."""
        if self.steps:
            _, label, detail = self.steps[-1]
            return f"{label}: {detail}"
        return "no status"


# ─── Helpers ────────────────────────────────────────────

def _read_json(filepath: Path) -> Optional[dict]:
    """Read and parse a JSON file, returning None on failure."""
    if not filepath.exists():
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[wake] Failed to read %s: %s", filepath, e)
        return None


def _check_lock(branch_path: Path) -> Optional[dict]:
    """Check if branch has an active dispatch lock. Returns lock data or None."""
    lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
    if not lock_file.exists():
        return None
    try:
        with open(lock_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        pid = data.get("pid")
        if pid is not None:
            try:
                os.kill(pid, 0)
                return data  # Process alive, lock valid
            except ProcessLookupError:
                logger.info("[wake] Lock PID %s dead — cleaning stale lock", pid)
            except PermissionError as e:
                logger.warning("[wake] Lock PID %s permission error: %s", pid, e)
                return data  # Process exists but can't signal — treat as active
        # Stale lock — check age (10 min timeout)
        ts = data.get("timestamp", "")
        if ts:
            try:
                from datetime import datetime
                lock_time = datetime.fromisoformat(ts)
                age = (datetime.now() - lock_time).total_seconds()
                if age > 600:
                    lock_file.unlink(missing_ok=True)
                    return None
            except (ValueError, TypeError):
                logger.info("[wake] Unparseable lock timestamp at %s", lock_file)
        # Dead process, remove stale lock
        lock_file.unlink(missing_ok=True)
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[wake] Failed to read lock file %s: %s", lock_file, e)
        return None


def _acquire_lock(branch_path: Path, pid: int) -> Tuple[bool, str]:
    """Acquire dispatch lock for branch. Atomic creation."""
    lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
    lock_data = {
        "pid": pid,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "branch": str(branch_path)
    }
    try:
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, 'w') as f:
            json.dump(lock_data, f, indent=2)
        return True, "Lock acquired"
    except FileExistsError as e:
        logger.warning("[wake] Lock file already exists at %s: %s", lock_file, e)
        return False, "Lock file already exists"
    except OSError as e:
        logger.warning("[wake] Lock acquisition failed at %s: %s", lock_file, e)
        return False, f"Lock failed: {e}"


def _load_config() -> dict:
    """Load safety config for max_turns."""
    defaults = {"max_turns_per_wake": 100}
    config = _read_json(CONFIG_FILE)
    if config is None:
        return defaults
    for key, val in defaults.items():
        if key not in config:
            config[key] = val
    return config


def _set_session_name(branch_path: Path, name: str) -> bool:
    """Write custom-title to the most recent Claude session JSONL for a branch."""
    encoded_cwd = str(branch_path).replace("/", "-")
    projects_dir = Path("~/.claude/projects").expanduser() / encoded_cwd
    if not projects_dir.exists():
        return False
    jsonl_files = sorted(
        projects_dir.glob("*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )
    if not jsonl_files:
        return False
    latest = jsonl_files[0]
    session_id = latest.stem
    entry = json.dumps({
        "type": "custom-title",
        "customTitle": name,
        "sessionId": session_id
    })
    try:
        with open(latest, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
        return True
    except OSError as e:
        logger.warning("[wake] Failed to write session name for %s: %s", branch_path, e)
        return False


def _read_session_type(pid_str: str) -> str:
    """Read AIPASS_SESSION_TYPE from /proc/{pid}/environ. Returns 'interactive' if unset."""
    if sys.platform != "linux":
        return 'interactive'
    try:
        with open(f'/proc/{pid_str}/environ', 'rb') as f:
            data = f.read()
        for entry in data.split(b'\0'):
            if entry.startswith(b'AIPASS_SESSION_TYPE='):
                return entry.split(b'=', 1)[1].decode('utf-8')
    except (OSError, PermissionError):
        logger.info("[wake] Cannot read session type for PID %s", pid_str)
    return 'interactive'


# Session types that should NOT block dispatch (idle/background sessions)
_NON_BLOCKING_SESSION_TYPES = {'telegram', 'dispatched', 'daemon'}


def _is_branch_occupied(branch_path: Path) -> bool:
    """Check if an interactive Claude session is running in this branch directory."""
    resolved = str(branch_path.resolve())
    try:
        result = subprocess.run(
            ['pgrep', '-x', 'claude'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return False
        for pid_str in result.stdout.strip().split('\n'):
            pid_str = pid_str.strip()
            if not pid_str:
                continue
            try:
                if sys.platform != "linux":
                    continue
                cwd = os.readlink(f'/proc/{pid_str}/cwd')
                if str(Path(cwd).resolve()) == resolved:
                    session_type = _read_session_type(pid_str)
                    if session_type not in _NON_BLOCKING_SESSION_TYPES:
                        return True
            except (OSError, PermissionError, ValueError):
                logger.info("[wake] Cannot read cwd for PID %s", pid_str)
                continue
    except (subprocess.SubprocessError, OSError):
        logger.info("[wake] Failed to check branch occupancy")
    return False


def _clean_zombies() -> int:
    """Find and report zombie Claude processes. Returns count found."""
    count = 0
    try:
        result = subprocess.run(
            ['ps', '-eo', 'pid,stat,comm'],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split('\n'):
            parts = line.split()
            if len(parts) >= 3 and parts[2] == 'claude' and 'Z' in parts[1]:
                count += 1
                logger.info("[wake] Found zombie Claude process PID %s", parts[0])
    except (subprocess.SubprocessError, OSError):
        logger.info("[wake] Failed to check for zombie processes")
    return count


def _check_pid_alive(pid: int) -> bool:
    """Check if a process is alive (not zombie)."""
    try:
        os.kill(pid, 0)
        # Also verify not zombie via /proc (Linux only)
        if sys.platform == "linux":
            with open(f'/proc/{pid}/status', 'r') as f:
                for line in f:
                    if line.startswith('State:'):
                        return 'Z' not in line
        return True
    except (ProcessLookupError, FileNotFoundError) as e:
        logger.warning("[wake] PID %s not found: %s", pid, e)
        return False
    except PermissionError as e:
        logger.warning("[wake] PID %s permission denied: %s", pid, e)
        return True  # Exists but can't check — assume alive


# ─── Branch Resolution ──────────────────────────────────

def resolve_branch(branch_email: str) -> Optional[Tuple[Path, str]]:
    """Resolve a branch email to its absolute filesystem path."""
    email = f"@{branch_email.lstrip('@').lower()}"
    registry = _read_json(BRANCH_REGISTRY)
    if registry is None:
        return None
    for branch in registry.get("branches", []):
        if branch.get("email", "").lower() == email:
            path = Path(branch.get("path", ""))
            if not path.is_absolute():
                path = _REPO_ROOT / path
            if path.exists():
                return path, email
            return None
    return None


# ─── Main Wake Function ─────────────────────────────────

def wake_branch(branch_email: str, custom_message: Optional[str] = None,
                fresh: bool = False, auto: bool = False,
                sender: str = "@devpulse") -> Tuple[DispatchStatus, bool]:
    """
    Spawn a Claude agent at the target branch with step-by-step status.

    Returns:
        Tuple of (DispatchStatus with all steps, overall success bool)
    """
    json_handler.log_operation("wake_branch", {"branch": branch_email, "fresh": fresh, "auto": auto})

    status = DispatchStatus()

    # Step 1: Pause check (auto-dispatch only)
    if auto and PAUSE_FILE.exists():
        status.fail("pause", "System paused (autonomous_pause active)")
        logger.warning("[wake] BLOCKED %s — system paused", branch_email)
        return status, False

    # Step 2: Resolve branch
    result = resolve_branch(branch_email)
    if result is None:
        status.fail("resolve", f"Branch not found: {branch_email}")
        return status, False

    branch_path, email = result
    status.ok("resolve", f"{email} → {branch_path}")

    # Step 3: Zombie check (pre-flight)
    zombie_count = _clean_zombies()
    if zombie_count > 0:
        status.warn("zombies", f"{zombie_count} zombie Claude process(es) detected")
    else:
        status.ok("pre-flight", "No zombie processes")

    # Step 4: Lock check
    existing = _check_lock(branch_path)
    if existing is not None:
        pid = existing.get("pid", "?")
        since = existing.get("timestamp", "?")
        if auto:
            status.fail("lock", f"Active agent (PID {pid}, since {since})")
            logger.warning("[wake] BLOCKED %s — active agent PID %s", email, pid)
            return status, False
        else:
            status.info("lock", f"Agent active (PID {pid}) — email routed to inbox")
            status.info("delivery", "Agent will process email during current session")
            return status, True

    status.ok("lock", "No active lock — agent is sleeping")

    # Step 5: Occupancy check
    if _is_branch_occupied(branch_path):
        status.warn("occupancy", f"Interactive Claude session in {branch_path}")
        status.fail("blocked", "Cannot spawn — interactive session running")
        logger.warning("[wake] BLOCKED %s — interactive session", email)
        return status, False

    status.ok("occupancy", "No interactive session")

    # Step 6: Build spawn command
    config = _load_config()
    max_turns = config.get("max_turns_per_wake", 100)

    lock_file_path = str(branch_path / ".ai_mail.local" / ".dispatch.lock")
    if custom_message:
        prompt = f"Hi. {custom_message} "
    else:
        prompt = f"{DEFAULT_PROMPT} "
    # Monitor handles lock cleanup — agent doesn't need to know about it
    prompt += f"IMPORTANT: When finished, delete the dispatch lock file at {lock_file_path}"

    if fresh:
        claude_cmd = [
            "claude", "-p", prompt,
            "--max-turns", str(max_turns),
            "--permission-mode", "bypassPermissions",
            "--output-format", "json"
        ]
    else:
        claude_cmd = [
            "claude", "-c", "-p", prompt,
            "--max-turns", str(max_turns),
            "--permission-mode", "bypassPermissions",
            "--output-format", "json"
        ]

    # Set session name for /resume picker
    branch_name = email.lstrip("@").upper()
    session_label = f"{branch_name}-dispatched"
    if not fresh:
        _set_session_name(branch_path, session_label)

    # Step 7: Spawn via dispatch_monitor
    log_dir = branch_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stderr_log = str(log_dir / "dispatch_stderr.log")

    # Build monitor command
    monitor_cmd = [
        sys.executable, str(MONITOR_SCRIPT),
        email, lock_file_path, sender, stderr_log,
        "--", *claude_cmd
    ]

    # Prepare environment
    spawn_env = os.environ.copy()
    spawn_env["AIPASS_SPAWNED"] = "1"
    spawn_env["AIPASS_SESSION_TYPE"] = "dispatched"
    for key in list(spawn_env.keys()):
        if key.startswith("CLAUDE") or key == "AIPASS_BOT_ID":
            spawn_env.pop(key)

    try:
        process = subprocess.Popen(
            monitor_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(branch_path),
            env=spawn_env
        )

        monitor_pid = process.pid
        status.ok("spawn", f"Monitor started (PID {monitor_pid})")

    except FileNotFoundError as e:
        logger.warning("[wake] Spawn failed — script not found: %s", e)
        status.fail("spawn", "Python or monitor script not found")
        return status, False
    except Exception as e:
        logger.warning("[wake] Spawn failed for %s: %s", branch_email, e)
        status.fail("spawn", f"{type(e).__name__}: {e}")
        return status, False

    # Step 8: Acquire lock (with monitor PID — stays alive as long as agent)
    acquired, lock_msg = _acquire_lock(branch_path, monitor_pid)
    if not acquired:
        status.warn("lock-acquire", f"Lock failed: {lock_msg}")
    else:
        status.ok("lock-acquire", "Dispatch lock acquired")

    # Step 9: Liveness check (brief wait then verify)
    time.sleep(2)
    if _check_pid_alive(monitor_pid):
        status.ok("alive", f"Agent responding (PID {monitor_pid} alive)")
    else:
        status.fail("alive", f"Agent died immediately (PID {monitor_pid})")
        # Clean up lock
        lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
        lock_file.unlink(missing_ok=True)
        return status, False

    # Desktop notification
    notif_body = custom_message[:80] if custom_message else "Manual wake: check inbox"
    try:
        from aipass.ai_mail.apps.handlers.notify import send_notification
        send_notification(f"Wake → {email}", notif_body, source=email.lstrip("@"))
    except Exception:
        logger.info("[wake] Desktop notification unavailable")

    return status, True


# ─── CLI Entry Point ─────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] in ("--help", "-h"):
        print("Usage: wake.py [--fresh] [--auto] [--sender @branch] @branch [\"optional message\"]")
        print("  Manually spawn a Claude agent at a branch (daemon not required)")
        print()
        print("Flags:")
        print("  --fresh          Start fresh session (claude -p) instead of resuming (claude -c -p)")
        print("  --auto           Respect autonomous_pause (used by daemon). Manual wake ignores it.")
        print("  --sender @branch Set return-to-sender for bounce emails (default: @devpulse)")
        print()
        print("Output: Step-by-step status of the dispatch pipeline:")
        print("  ✅ resolve → @branch found at /path/to/branch")
        print("  ✅ lock → No active lock — agent is sleeping")
        print("  ✅ spawn → Monitor started (PID 12345)")
        print("  ✅ alive → Agent responding (PID 12345 alive)")
        print()
        print("On failure, a bounce email is sent to --sender automatically.")
        print()
        print("Examples:")
        print("  wake.py @flow                    # Default: check inbox (resume)")
        print("  wake.py --fresh @flow            # Fresh session, check inbox")
        print("  wake.py @vera \"Review NOTEPAD\"   # Custom prompt (resume)")
        print("  wake.py --fresh --sender @vera @seed  # Fresh, bounce to @vera")
        sys.exit(0)

    # Parse flags
    use_fresh = "--fresh" in args
    use_auto = "--auto" in args
    use_sender = "@devpulse"

    if "--sender" in args:
        idx = args.index("--sender")
        if idx + 1 < len(args):
            use_sender = args[idx + 1]
            args = args[:idx] + args[idx + 2:]

    args = [a for a in args if a not in ("--fresh", "--auto")]

    if not args:
        print("❌ Missing branch argument. Use --help for usage.")
        sys.exit(1)

    branch = args[0]
    message = args[1] if len(args) > 1 else None

    dispatch_status, success = wake_branch(
        branch, message, fresh=use_fresh, auto=use_auto, sender=use_sender
    )
    print(dispatch_status.format())
    sys.exit(0 if success else 1)
