# =================== AIPass ====================
# Name: wake.py
# Description: Manual Branch Wake Handler
# Version: 2.0.1
# Created: 2026-03-02
# Modified: 2026-07-31
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
import shlex
import shutil
import sys
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple, List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root


def _find_claude_bin() -> str:
    """Locate the claude binary, checking known install locations if not on PATH.

    Background processes (trigger Medic, prax watchdog) may have a restricted
    PATH without ~/.local/bin. This resolves the absolute path directly.
    """
    found = shutil.which("claude")
    if found:
        return found
    for candidate in [
        Path.home() / ".local" / "bin" / "claude",
        Path("/usr/local/bin/claude"),
        Path("/usr/bin/claude"),
    ]:
        if candidate.exists():
            return str(candidate)
    return "claude"  # Last resort — will raise FileNotFoundError if not found


_CLAUDE_BIN = _find_claude_bin()


# Infrastructure paths
_REPO_ROOT = find_repo_root()
_AI_MAIL_DIR = Path(__file__).resolve().parents[3]  # ai_mail/
CONFIG_FILE = _AI_MAIL_DIR / "safety_config.json"
BRANCH_REGISTRY = _REPO_ROOT / "AIPASS_REGISTRY.json"
PAUSE_FILE = _REPO_ROOT / ".aipass" / "autonomous_pause"
MONITOR_SCRIPT = Path(__file__).parent / "dispatch_monitor.py"

# Default prompt when no custom message provided
DEFAULT_PROMPT = "Hi. Check inbox, process new emails, update memories when done."

# Model aliases — passed directly to claude CLI which resolves latest-in-class.
KNOWN_MODEL_ALIASES: frozenset = frozenset({"sonnet", "opus", "haiku"})
DEFAULT_MODEL = "sonnet"

# Branches that cannot be woken manually by cross-branch drone commands.
# Dispatch-send path (dispatch.py._orchestrate_dispatch_send) bypasses this check.
WAKE_BLOCKLIST: frozenset[str] = frozenset({"@devpulse"})


def is_wake_blocked(target: str) -> bool:
    """Return True if `target` is on the manual-wake blocklist."""
    return f"@{target.lstrip('@').lower()}" in WAKE_BLOCKLIST


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
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[wake] Failed to read %s: %s", filepath, e)
        return None


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


def _check_lock(branch_path: Path) -> Optional[dict]:
    """Check if branch has an active dispatch lock. Returns lock data or None."""
    lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
    if not lock_file.exists():
        return None
    try:
        with open(lock_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        pid = data.get("pid")
        if pid is not None:
            if _check_pid_alive(pid):
                return data
            logger.info("[wake] Lock PID %s dead — cleaning stale lock", pid)
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


# Session types that should NOT block dispatch (idle/background sessions)
_NON_BLOCKING_SESSION_TYPES = {"dispatched", "daemon"}


def _is_branch_occupied(branch_path: Path) -> bool:
    """Check if an interactive Claude session is running in this branch directory."""
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
    except (subprocess.SubprocessError, OSError):
        logger.info("[wake] Failed to check branch occupancy")
    return False


def _clean_zombies() -> int:
    """Find and report zombie Claude processes. Returns count found."""
    count = 0
    try:
        result = subprocess.run(["ps", "-eo", "pid,stat,comm"], capture_output=True, text=True, timeout=5)
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 3 and parts[2] == "claude" and "Z" in parts[1]:
                count += 1
                logger.info("[wake] Found zombie Claude process PID %s", parts[0])
    except (subprocess.SubprocessError, OSError):
        logger.info("[wake] Failed to check for zombie processes")
    return count


def _check_pid_alive(pid: int) -> bool:
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
        with open(f"/proc/{pid}/status", "r") as f:
            for line in f:
                if line.startswith("State:"):
                    return "Z" in line
    except FileNotFoundError as exc:
        logger.warning("[wake] PID %s /proc not found: %s", pid, exc)
    return False


def _spawn_in_systemd_scope(monitor_cmd, branch_path, spawn_env, branch_email, lock_file_path, custom_message, status):
    """Spawn monitor in its own systemd unit to survive cgroup cleanup (td-48).

    When wake_branch() runs inside a systemd oneshot service (e.g.
    daemon-tick.timer), the default KillMode=control-group sends SIGTERM to
    every process in the cgroup once the main process exits — killing the
    detached monitor and its claude child.  systemd-run --user creates a
    transient service unit with its own cgroup so the monitor survives.

    Returns True on success, False to fall back to direct Popen.
    """
    unit_name = f"dispatch-{branch_email.lstrip('@')}"
    env_file = branch_path / "logs" / ".dispatch_env"

    try:
        with open(env_file, "w", encoding="utf-8") as ef:
            for key, val in spawn_env.items():
                if "\n" not in str(val):
                    ef.write(f"{key}={val}\n")
        env_file.chmod(0o600)
    except OSError as e:
        logger.warning("[wake] Failed to write env file for systemd-run: %s", e)
        return False

    systemd_cmd = [
        "systemd-run",
        "--user",
        "--unit",
        unit_name,
        "--collect",
        "--property",
        f"WorkingDirectory={branch_path}",
        "--property",
        f"EnvironmentFile={env_file}",
        "--property",
        "StandardInput=null",
        "--",
    ] + monitor_cmd

    try:
        result = subprocess.run(systemd_cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            logger.warning("[wake] systemd-run failed (rc=%d): %s", result.returncode, result.stderr.strip())
            return False
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("[wake] systemd-run failed: %s", e)
        return False

    try:
        pid_result = subprocess.run(
            ["systemctl", "--user", "show", f"{unit_name}.service", "-p", "MainPID", "--value"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        monitor_pid = int(pid_result.stdout.strip())
        if monitor_pid > 0:
            lock_data = {
                "pid": monitor_pid,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "branch": str(branch_path),
                "subject": custom_message or "daemon wake",
            }
            with open(lock_file_path, "w", encoding="utf-8") as f:
                json.dump(lock_data, f, indent=2)
    except (subprocess.SubprocessError, ValueError, OSError) as e:
        logger.info("[wake] Could not query systemd unit PID: %s", e)

    status.ok("spawn", f"Monitor started via systemd scope ({unit_name})")
    return True


# ─── Branch Resolution ──────────────────────────────────


def resolve_branch(branch_email: str) -> Optional[Tuple[Path, str]]:
    """Resolve a branch email to its absolute filesystem path.

    Checks the AIPass registry first, then falls back to the caller's
    project registry via AIPASS_CALLER_CWD for cross-project dispatch.
    """
    email = f"@{branch_email.lstrip('@').lower()}"

    # Step 1: AIPass registry (local branches)
    registry = _read_json(BRANCH_REGISTRY)
    if registry is not None:
        for branch in registry.get("branches", []):
            if branch.get("email", "").lower() == email:
                path = Path(branch.get("path", ""))
                if not path.is_absolute():
                    path = _REPO_ROOT / path
                if path.exists():
                    return path, email
                return None  # Found but path missing — definitive failure

    # Step 2: Caller's project registry (cross-project dispatch)
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    if caller_cwd:
        try:
            from aipass.ai_mail.apps.handlers.registry.read import get_caller_project_branches

            caller_branches = get_caller_project_branches(caller_cwd)
            branch_path_str = caller_branches.get(email, "")
            if branch_path_str:
                branch_path = Path(branch_path_str)
                if branch_path.exists():
                    return branch_path, email
        except Exception as e:
            logger.warning("[wake] resolve_branch caller registry fallback failed: %s", e)

    return None


# ─── Interactive Manager Spawn ──────────────────────────


def _spawn_manager_interactive(
    branch_path: Path,
    email: str,
    prompt: str,
    model: Optional[str],
    status: "DispatchStatus",
) -> Tuple["DispatchStatus", bool]:
    """Spawn an interactive tmux session for a manager branch.

    Managers are never headless — they run interactive sessions the user can
    attach to (same pattern as the manual tmux interactive wake). Used only
    for @daemon-scheduled self-wakes that passed the manager gate. No dispatch
    lock or monitor: the occupancy check is the one-instance guard for
    interactive sessions.
    """
    if shutil.which("tmux") is None:
        status.fail("tmux", "tmux not found — cannot spawn interactive manager session")
        logger.warning("[wake] %s manager wake failed — tmux missing", email)
        return status, False

    # Prompt goes through a file — survives quoting, debuggable after the fact.
    daemon_dir = branch_path / ".daemon"
    daemon_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = daemon_dir / "last_wake_prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    session = f"daemon-{branch_path.name}-{time.strftime('%H%M%S')}"
    model_arg = f" --model {shlex.quote(model)}" if model else ""
    claude_line = f'{shlex.quote(_CLAUDE_BIN)}{model_arg} "$(cat {shlex.quote(str(prompt_file))})"'
    try:
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session, "-c", str(branch_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", session, claude_line, "Enter"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        status.fail("tmux", f"Interactive spawn failed: {detail[:200]}")
        logger.error("[wake] %s interactive tmux spawn failed: %s", email, detail)
        return status, False

    status.ok("spawn", f"Interactive tmux session '{session}' started (attach: tmux attach -t {session})")
    logger.info("[wake] %s manager woken interactively in tmux session %s", email, session)
    json_handler.log_operation("wake_manager_interactive", {"branch": email, "session": session})
    return status, True


# ─── Main Wake Function ─────────────────────────────────


def wake_branch(
    branch_email: str,
    custom_message: Optional[str] = None,
    fresh: bool = False,
    auto: bool = False,
    sender: str = "@devpulse",
    model: Optional[str] = None,
) -> Tuple[DispatchStatus, bool]:
    """
    Spawn a Claude agent at the target branch with step-by-step status.

    Args:
        branch_email: Target branch email (e.g. "@flow")
        custom_message: Optional custom prompt (replaces default inbox check)
        fresh: If True, start fresh session instead of resuming
        auto: If True, respect autonomous_pause (used by daemon)
        sender: Return-to-sender for bounce emails
        model: Model shorthand ("sonnet", "opus", "haiku") or full model ID.
               Defaults to sonnet (claude-sonnet-4-6).

    Returns:
        Tuple of (DispatchStatus with all steps, overall success bool)
    """
    json_handler.log_operation(
        "wake_branch", {"branch": branch_email, "fresh": fresh, "auto": auto, "model": model or DEFAULT_MODEL}
    )

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

    # Step 3: Manager check — managers are never woken, mail only.
    # Exception: @daemon scheduler fires. A branch's .daemon/schedule.json is
    # self-authored (the daemon cannot write another branch's files), so a
    # daemon-scheduled wake is the manager waking ITSELF — consent is the
    # schedule's existence. Dispatch/manual wakes remain blocked.
    passport_file = branch_path / ".trinity" / "passport.json"
    manager_scheduled = False  # daemon-scheduled manager wake → interactive tmux spawn
    try:
        with open(passport_file, "r", encoding="utf-8") as f:
            passport = json.load(f)
        citizen_class = passport.get("identity", {}).get("citizen_class", "")
        if citizen_class == "manager":
            if sender == "@daemon":
                manager_scheduled = True
                status.ok("manager", f"{email} manager gate bypassed — daemon-scheduled self-wake")
                logger.info("[wake] %s manager gate bypassed — @daemon scheduled wake", email)
            else:
                status.info("manager", f"{email} is a manager — mail only, wake skipped")
                logger.info("[wake] %s is citizen_class=manager — wake skipped, mail delivered", email)
                return status, True
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.info("[wake] Could not read passport for %s: %s", email, exc)

    # Step 4: Zombie check (pre-flight)
    zombie_count = _clean_zombies()
    if zombie_count > 0:
        status.warn("zombies", f"{zombie_count} zombie Claude process(es) detected")
    else:
        status.ok("pre-flight", "No zombie processes")

    # Step 5: Lock check
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

    # Step 6: Occupancy check
    if _is_branch_occupied(branch_path):
        status.warn("occupancy", f"Interactive Claude session in {branch_path}")
        status.fail("blocked", "Cannot spawn — interactive session running")
        logger.warning("[wake] BLOCKED %s — interactive session", email)
        return status, False

    status.ok("occupancy", "No interactive session")

    # Managers never run headless: a daemon-scheduled manager wake spawns an
    # interactive tmux session instead of the -p/monitor pipeline below.
    if manager_scheduled:
        return _spawn_manager_interactive(branch_path, email, custom_message or DEFAULT_PROMPT, model, status)

    # Step 7: Build spawn command
    config = _load_config()
    max_turns = config.get("max_turns_per_wake", 100)

    # Pass model directly to CLI — aliases resolve latest-in-class automatically
    resolved_model = model or DEFAULT_MODEL

    if custom_message:
        prompt = f"Hi. {custom_message} "
    else:
        prompt = f"{DEFAULT_PROMPT} "
    # Monitor owns lock cleanup end-to-end — telling the agent to delete it
    # too let a second monitor spawn onto a "clear" lock while the first was
    # still alive, then have its own unconditional cleanup steal the second
    # monitor's lock out from under it (lock-theft, observed 2026-07-31).
    prompt += (
        "IMPORTANT: run any sub-agents synchronously (foreground) and wait for them to "
        "finish before ending your turn — headless dispatch kills orphaned background "
        "work after 600s with no reply sent."
    )

    if fresh:
        claude_cmd = [
            _CLAUDE_BIN,
            "-p",
            prompt,
            "--model",
            resolved_model,
            "--max-turns",
            str(max_turns),
            "--permission-mode",
            "bypassPermissions",
            "--output-format",
            "json",
        ]
    else:
        claude_cmd = [
            _CLAUDE_BIN,
            "-c",
            "-p",
            prompt,
            "--model",
            resolved_model,
            "--max-turns",
            str(max_turns),
            "--permission-mode",
            "bypassPermissions",
            "--output-format",
            "json",
        ]

    # Step 7: Spawn via dispatch_monitor
    log_dir = branch_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stderr_log = str(log_dir / "dispatch_stderr.log")
    lock_file_path = str(branch_path / ".ai_mail.local" / ".dispatch.lock")

    # Build monitor command
    monitor_cmd = [sys.executable, str(MONITOR_SCRIPT), email, lock_file_path, sender, stderr_log, "--", *claude_cmd]

    # Prepare environment
    spawn_env = os.environ.copy()
    spawn_env["AIPASS_SPAWNED"] = "1"
    spawn_env["AIPASS_SESSION_TYPE"] = "dispatched"
    # Guarantee venv bin is on PATH so dispatched agents can find drone/claude
    venv_bin = str(_REPO_ROOT / ".venv" / "bin")
    if venv_bin not in spawn_env.get("PATH", ""):
        spawn_env["PATH"] = venv_bin + ":" + spawn_env.get("PATH", "")
    # Guarantee ~/.local/bin is on PATH for pip-installed tools (e.g. claude)
    # Background processes (trigger, prax watchdog) may have restricted PATH.
    local_bin = str(Path.home() / ".local" / "bin")
    if local_bin not in spawn_env.get("PATH", ""):
        spawn_env["PATH"] = local_bin + ":" + spawn_env.get("PATH", "")
    for key in list(spawn_env.keys()):
        if key.startswith("CLAUDE") or key == "AIPASS_BOT_ID":
            spawn_env.pop(key)

    # Acquire lock BEFORE spawn to prevent TOCTOU race (DPLAN-0155 Phase 5).
    acquired, lock_msg = _acquire_lock(branch_path, os.getpid())
    if not acquired:
        status.fail("lock-acquire", f"Lock failed: {lock_msg}")
        return status, False
    status.ok("lock-acquire", "Dispatch lock acquired")

    # When inside a systemd oneshot service (e.g. daemon-tick.timer), the
    # default KillMode=control-group sends SIGTERM to all cgroup members
    # when the service exits — killing the detached monitor.  Escape by
    # launching the monitor in its own transient systemd unit (td-48).
    spawned_via_scope = False
    monitor_pid = 0
    if os.environ.get("INVOCATION_ID") and shutil.which("systemd-run"):
        spawned_via_scope = _spawn_in_systemd_scope(
            monitor_cmd,
            branch_path,
            spawn_env,
            email,
            lock_file_path,
            custom_message,
            status,
        )

    if not spawned_via_scope:
        try:
            _detach_kwargs: dict = {}
            if sys.platform == "win32":
                _detach_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                _detach_kwargs["start_new_session"] = True
            process = subprocess.Popen(
                monitor_cmd,
                stdin=subprocess.DEVNULL,
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
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "branch": str(branch_path),
                "subject": custom_message or "manual wake",
            }
            with open(lock_file, "w", encoding="utf-8") as f:
                json.dump(lock_data, f, indent=2)

            status.ok("spawn", f"Monitor started (PID {monitor_pid})")

        except FileNotFoundError as e:
            lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
            lock_file.unlink(missing_ok=True)
            logger.warning("[wake] Spawn failed — script not found: %s", e)
            status.fail("spawn", "Python or monitor script not found")
            return status, False
        except Exception as e:
            lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
            lock_file.unlink(missing_ok=True)
            logger.warning("[wake] Spawn failed for %s: %s", branch_email, e)
            status.fail("spawn", f"{type(e).__name__}: {e}")
            return status, False

    # Step 9: Liveness check (brief wait then verify)
    time.sleep(2)
    if spawned_via_scope:
        _unit = f"dispatch-{email.lstrip('@')}"
        try:
            check = subprocess.run(
                ["systemctl", "--user", "is-active", f"{_unit}.service"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if check.stdout.strip() == "active":
                status.ok("alive", f"Agent responding (unit {_unit} active)")
            else:
                status.fail("alive", f"Agent died immediately ({check.stdout.strip()})")
                lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
                lock_file.unlink(missing_ok=True)
                return status, False
        except Exception as e:
            logger.info("[wake] Cannot verify systemd unit %s: %s", _unit, e)
            status.warn("alive", "Cannot verify systemd unit status — assuming running")
    else:
        if _check_pid_alive(monitor_pid):
            status.ok("alive", f"Agent responding (PID {monitor_pid} alive)")
        else:
            status.fail("alive", f"Agent died immediately (PID {monitor_pid})")
            lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
            lock_file.unlink(missing_ok=True)
            return status, False

    # Desktop notification
    notif_body = custom_message[:80] if custom_message else "Manual wake: check inbox"
    try:
        from aipass.ai_mail.apps.handlers.notify import send_notification

        send_notification(f"@{email.lstrip('@')} waking", notif_body, source=email.lstrip("@"))
    except Exception:
        logger.info("[wake] Desktop notification unavailable")

    return status, True


# ─── CLI Entry Point ─────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] in ("--help", "-h"):
        print('Usage: wake.py [--fresh] [--auto] [--sender @branch] [--model sonnet|opus] @branch ["optional message"]')
        print("  Manually spawn a Claude agent at a branch (daemon not required)")
        print()
        print("Flags:")
        print("  --fresh          Start fresh session (claude -p) instead of resuming (claude -c -p)")
        print("  --auto           Respect autonomous_pause (used by daemon). Manual wake ignores it.")
        print("  --sender @branch Set return-to-sender for bounce emails (default: @devpulse)")
        print("  --model NAME     Model to use: sonnet (default), opus, haiku, or full model ID")
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
        print('  wake.py @vera "Review NOTEPAD"   # Custom prompt (resume)')
        print("  wake.py --fresh --sender @vera @seedgo  # Fresh, bounce to @vera")
        sys.exit(0)

    # Parse flags
    use_fresh = "--fresh" in args
    use_auto = "--auto" in args
    use_sender = "@devpulse"
    use_model = None

    if "--sender" in args:
        idx = args.index("--sender")
        if idx + 1 < len(args):
            use_sender = args[idx + 1]
            args = args[:idx] + args[idx + 2 :]

    if "--model" in args:
        idx = args.index("--model")
        if idx + 1 < len(args):
            use_model = args[idx + 1]
            args = args[:idx] + args[idx + 2 :]

    args = [a for a in args if a not in ("--fresh", "--auto")]

    if not args:
        print("❌ Missing branch argument. Use --help for usage.")
        sys.exit(1)

    branch = args[0]
    message = args[1] if len(args) > 1 else None

    dispatch_status, success = wake_branch(
        branch, message, fresh=use_fresh, auto=use_auto, sender=use_sender, model=use_model
    )
    print(dispatch_status.format())
    sys.exit(0 if success else 1)
