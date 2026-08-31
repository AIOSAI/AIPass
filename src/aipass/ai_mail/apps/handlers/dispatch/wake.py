# =================== AIPass ====================
# Name: wake.py
# Description: Manual Branch Wake Handler
# Version: 3.0.0
# Created: 2026-03-02
# Modified: 2026-08-30
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
from aipass.ai_mail.apps.handlers.dispatch import session_pointer


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
KNOWN_MODEL_ALIASES: frozenset = frozenset({"sonnet", "opus", "haiku", "fable"})
# If this default is flipped again, update the README to match (Patrick, 2026-08-01).
DEFAULT_MODEL = "opus"

# The passport value that means "never woken by an ordinary caller".
MANAGER_CLASS = "manager"
# Patrick, 2026-08-30: "managers are fable thats it, only manager run fable".
MANAGER_MODEL = "fable"

# The one marking tmux cannot half-apply. A session either exists under this
# name or new-session failed, so `tmux ls` never shows a daemon wake wearing a
# hand-made name — which is how @vera's first external wake got killed as a
# human's leftover on 2026-08-30. Loud on purpose: it is read by a person who
# is deciding whether to kill a window, not by a parser.
DAEMON_SESSION_PREFIX = "AIPASS-DAEMON-WAKE-"

# Branches that cannot be woken manually by cross-branch drone commands.
# Dispatch-send path (dispatch.py._orchestrate_dispatch_send) bypasses this check.
WAKE_BLOCKLIST: frozenset[str] = frozenset({"@devpulse"})


def is_wake_blocked(target: str) -> bool:
    """Return True if `target` is on the manual-wake blocklist."""
    return f"@{target.lstrip('@').lower()}" in WAKE_BLOCKLIST


def _is_fable(model: str) -> bool:
    """True for any spelling of Fable — bare alias, full id, any casing.

    Substring rather than equality on purpose: the CLI takes both `fable` and
    `claude-fable-5`, so a policy that only knew the alias would let the full
    id walk straight past the non-manager half of the rule.
    """
    return "fable" in model.lower()


def resolve_wake_model(citizen_class: str, requested: Optional[str]) -> str:
    """The model this wake spawns on, per Patrick's ruling of 2026-08-30.

    Two halves, and the second is the one with teeth. A manager ALWAYS gets
    Fable — the requested model is overridden, not merged, because a schedule
    naming a model is a preference and the ruling is a policy. Everyone else
    NEVER gets Fable: their request is honoured as it is today except for that
    one value, which falls back to DEFAULT_MODEL rather than refusing the wake.

    Both overrides are logged. A model silently swapped under a caller is the
    kind of change nobody can find later, and the log line is the only place a
    schedule's author learns their wake.model field was not what ran.

    `citizen_class` comes from the passport wake_branch already opens for the
    manager gate — one read, one source. An unreadable passport arrives here as
    "", i.e. not a manager, which is the same direction is_manager() fails in:
    an invented manager would silently move a branch onto Fable.

    Args:
        citizen_class: identity.citizen_class from the target's passport, or ""
        requested: the caller's model (schedule.json wake.model, --model, None)

    Returns:
        The model string to hand the CLI. Never None — the wake lane names its
        model rather than inheriting whatever the CLI would have defaulted to,
        which is exactly how @vera landed on Fable by accident on 2026-08-30.
    """
    if citizen_class == MANAGER_CLASS:
        if requested and not _is_fable(requested):
            logger.info(
                "[wake] manager policy: requested model %r overridden to %s (Patrick 2026-08-30)",
                requested,
                MANAGER_MODEL,
            )
        return MANAGER_MODEL

    if requested and _is_fable(requested):
        logger.warning(
            "[wake] non-manager policy: %r refused — Fable is managers-only, falling back to %s",
            requested,
            DEFAULT_MODEL,
        )
        return DEFAULT_MODEL

    return requested or DEFAULT_MODEL


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

    def find_step(self, label: str) -> Optional[Tuple[str, str, str]]:
        """Return the last (status, label, detail) recorded under `label`, or None.

        Lets callers read a specific gate's own verdict instead of pattern-matching
        the prose in `summary`. Needed because the overall success bool cannot express
        "delivered, but deliberately not woken" — see the manager gate in wake_branch.
        """
        for step in reversed(self.steps):
            if step[1] == label:
                return step
        return None

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


def is_manager(branch_email: str) -> bool:
    """True when `branch_email` is citizen_class=manager, i.e. never woken.

    Exists so a caller can PROMISE the right thing. Dispatch used to tell every
    sender "you will be woken when X completes"; for a manager that was false, and
    the manager then heard nothing at all (@devpulse P0, 2026-08-21). Managers are
    mailed instead — the promise has to say so.

    Fails toward "not a manager": an unreadable or missing passport keeps the
    ordinary wake path, which is the behaviour that predates this helper. Inventing
    a manager would silently suppress a wake that should happen.

    Args:
        branch_email: Address of the branch to classify (e.g. "@devpulse").

    Returns:
        bool: True only when a readable passport says citizen_class == "manager".
    """
    resolved = resolve_branch(branch_email)
    if not resolved:
        return False
    branch_path, _ = resolved
    try:
        with open(branch_path / ".trinity" / "passport.json", "r", encoding="utf-8") as f:
            passport = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.info("[wake] Could not classify %s: %s", branch_email, exc)
        return False
    return passport.get("identity", {}).get("citizen_class", "") == "manager"


def _external_citizens(repo_root: Path) -> List[dict]:
    """Every declared-root citizen, straight from @memory's public gateway.

    A named seam rather than an inline import, for two reasons. It is the ONE
    place the external tier enters my tree, so a change to @memory's contract
    surfaces here as an AttributeError instead of as a wrong answer three steps
    downstream; and a test can make the tier fail on demand without reaching
    into another branch's module namespace.

    Imported lazily and by MODULE, per @memory's own instruction: the branch
    stays importable on an installation where @memory is absent, and refusals
    logged inside the gateway stay attributable to @memory.

    Never a second implementation. Reading AIPASS_ROOTS.json here would be the
    exact failure the gateway was built to end — two readers of one anchor,
    agreeing until the day they do not.
    """
    from aipass.memory.apps.modules import fleet

    return fleet.external_branches(repo_root=repo_root)


def resolve_branch(branch_email: str, admin: bool = False) -> Optional[Tuple[Path, str]]:
    """Resolve a branch email to its absolute filesystem path.

    Four sources, in strict precedence: the AIPass registry, the caller's
    project registry via AIPASS_CALLER_CWD, the verified-admin projects/* sweep,
    and finally the declared-roots external tier.

    LOCAL ALWAYS WINS is the fleet ruling, and it is why the external step is
    LAST rather than merely late. Steps 1-3 all resolve inside AIPass home;
    step 4 leaves it. Putting the admin sweep after the external tier would let
    a sibling repo's @baud shadow the one living in our own projects/ — so the
    sweep keeps its position, unchanged and still admin-only. The external step
    carries no admin gate at all: @daemon fires unverified, and the anchor is a
    machine-managed file Patrick blessed, so declaration IS the credential.

    Externals are discoverable through @memory's fleet gateway long before they
    are wakeable through here — that gap is what failed @vera's first supervised
    fire on 2026-08-30 with "Branch not found: @vera" while the same citizen sat
    in @daemon's queue. Discovery and firing must read the same definition.

    Args:
        branch_email: Target address, with or without the leading @.
        admin: Only a VERIFIED admin caller (5 legs, checked by the caller —
            never claimed here) may see step 3, the projects/* sweep. Left
            False, this function behaves exactly as it did before phase 5:
            no widening for anyone unverified.
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

    # Step 3: Hosted projects (verified-admin only — the cross-project bridge).
    # Runs last so a local branch always wins, and runs at all only when the
    # caller already proved the grant. Unverified callers never reach here.
    if admin:
        try:
            from aipass.ai_mail.apps.handlers.registry.read import get_project_tree_branches

            project_branches = get_project_tree_branches(_REPO_ROOT)
            branch_path_str = project_branches.get(email, "")
            if branch_path_str:
                branch_path = Path(branch_path_str)
                if branch_path.exists():
                    logger.info("[wake] %s resolved via projects/ sweep — admin bridge", email)
                    return branch_path, email
        except Exception as e:
            logger.warning("[wake] resolve_branch projects sweep failed: %s", e)

    # Step 4: The declared-roots external tier (FPLAN-0460 phase 5).
    # Last, so every local source has already missed. Contained like the two
    # steps above it: a tier that cannot answer returns a miss, never a
    # traceback — every caller of this function reads None as "not found", and
    # wake_branch turns that into an honest failed step.
    try:
        candidates = [
            citizen
            for citizen in _external_citizens(_REPO_ROOT)
            if isinstance(citizen.get("email"), str) and citizen["email"].lower() == email
        ]
        if candidates:
            if len(candidates) > 1:
                # The ruling's own tie-break, and it now genuinely reaches this
                # door. This used to say the opposite: declared_roots() returned
                # sorted(found), so the winner was alphabetical-by-resolved-path
                # and the tie-break the fleet ruling names was not available
                # here. Rather than re-read the anchor to recover it — a second
                # reader of the file the gateway exists to own — the collision
                # was made loud and the disagreement raised with @memory, who
                # dropped the sort (registry_scope 4.1.0, 2026-08-30). The
                # gateway iterates roots in declaration order and dedups by
                # path, so candidates[0] is the first-declared claimant.
                #
                # Still logged at error. A tie-break being correct does not make
                # a collision expected: two roots claiming one address is a
                # thing someone should know about, and a resolution nobody
                # logged is indistinguishable from a citizen that only lives in
                # one place.
                logger.error(
                    "[wake] %s is claimed by %d declared roots — resolving to %s by DECLARATION ORDER "
                    "(first-declared root wins, per the fleet ruling). Other claimants: %s",
                    email,
                    len(candidates),
                    candidates[0]["path"],
                    ", ".join(str(citizen["path"]) for citizen in candidates[1:]),
                )
            branch_path = Path(candidates[0]["path"])
            # No exists() check: the gateway admits an external citizen only
            # when .trinity/passport.json is a file there, so the directory is
            # already proven. A second check here could never be false, and an
            # assertion that cannot fail hides which layer is load-bearing.
            logger.info("[wake] %s resolved via the declared-roots external tier", email)
            return branch_path, email
    except Exception as e:
        logger.warning("[wake] resolve_branch external tier failed: %s", e)

    return None


# ─── Interactive Manager Spawn ──────────────────────────


def _mark_daemon_session(session: str, email: str, status: "DispatchStatus") -> None:
    """Tag a live tmux session as daemon work, machine-readably.

    Patrick killed @vera's first external wake on 2026-08-30 because nothing in
    the session said a machine had started it — he read `daemon-vera-192848` as
    his own leftover tmux and took it out mid-playbook. The session NAME is the
    guaranteed half of the answer (see DAEMON_SESSION_PREFIX): tmux either
    creates the session under that name or the spawn already failed, so a human
    reading `tmux ls` cannot get a half-marked session.

    This is the queryable half — a user option any tool can read back with
    `tmux show-options -v -t <session> @aipass_daemon_wake` instead of
    string-matching a prefix. It is BEST EFFORT and never fatal: the session is
    already alive by the time it runs, and refusing to start the agent because
    a cosmetic option did not apply would trade real work for a label.

    Owns the "mark" step outright, both outcomes. The first cut recorded the
    warn here and an unconditional ok at the end of the spawn — and find_step
    returns the LAST record under a label, so every failed marking still read
    as marked. A step reported in two places is a step reported by neither.

    Deliberately NOT the dispatch register. open_dispatch() demands an
    expected_seconds taken from the lane's own timeout, and this lane has no
    monitor and no timeout — every entry it wrote would stay outstanding
    forever and go overdue against a number invented here, turning the crash
    detector into a wall of false alarms. The register answers "was this
    dispatch delivered"; this answers "may a human kill this window". Two
    questions, and only one of them has a monitor to close it.
    """
    marker = json.dumps({"branch": email, "sender": "@daemon", "started": time.strftime("%Y-%m-%dT%H:%M:%S")})
    try:
        subprocess.run(
            ["tmux", "set-option", "-t", session, "@aipass_daemon_wake", marker],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        status.warn("mark", f"Session option not set — the name is the only marking: {detail[:120]}")
        logger.warning("[wake] %s could not tag session %s as daemon work: %s", email, session, detail)
        return

    status.ok("mark", f"'{session}' marked as daemon work — do not kill (@aipass_daemon_wake is set)")


def _spawn_manager_interactive(
    branch_path: Path,
    email: str,
    prompt: str,
    model: str,
    status: "DispatchStatus",
) -> Tuple["DispatchStatus", bool]:
    """Spawn an interactive tmux session for a manager branch.

    The attachable path: a session the user CAN attach to (same pattern as the
    manual tmux interactive wake). Used only for @daemon self-wakes that passed
    the manager gate WITHOUT scheduled=True — the scheduled lane goes headless
    instead (DPLAN-0287). No dispatch lock or monitor here: the occupancy check
    is the one-instance guard for interactive sessions, which also means no
    context pin, no bounce email and no lock cleanup.

    Attachable is not attended. Every route into this function comes from
    @daemon, i.e. from a clock rather than a person, so the session launches
    with bypassPermissions unconditionally — Patrick's ruling of 2026-08-30
    after @vera sat on a denied Bash prompt here with nobody present to answer
    it ("always bypass permissions always, claude alone will nvr work"). The
    headless lane has carried the flag for months; this one is the lane that
    was still spawning a bare `claude`.

    `model` arrives already resolved by resolve_wake_model() — the policy lives
    at one site in wake_branch, and this lane naming its own would be a second
    place for the managers-only-Fable rule to drift.
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

    session = f"{DAEMON_SESSION_PREFIX}{branch_path.name}-{time.strftime('%H%M%S')}"
    claude_line = (
        f"{shlex.quote(_CLAUDE_BIN)} --model {shlex.quote(model)} "
        f"--permission-mode bypassPermissions "
        f'"$(cat {shlex.quote(str(prompt_file))})"'
    )
    try:
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session, "-c", str(branch_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        # Marked BEFORE the agent starts: a window is killable from the moment
        # it exists, so a marking that lands after send-keys leaves exactly the
        # gap this exists to close.
        _mark_daemon_session(session, email, status)
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
    logger.info("[wake] %s manager woken interactively in tmux session %s on %s", email, session, model)
    json_handler.log_operation("wake_manager_interactive", {"branch": email, "session": session, "model": model})
    return status, True


# ─── Main Wake Function ─────────────────────────────────


def wake_branch(
    branch_email: str,
    custom_message: Optional[str] = None,
    fresh: bool = False,
    auto: bool = False,
    sender: str = "@devpulse",
    model: Optional[str] = None,
    *,
    scheduled: bool = False,
    admin: bool = False,
    subject: Optional[str] = None,
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
               Defaults to opus (Patrick ruling 2026-08-01: agents run opus).
        scheduled: Keyword-only opt-in for the scheduled lane (DPLAN-0287) —
               an unattended run fired by a clock, not by a person. A manager
               target then wakes HEADLESS through dispatch_monitor (which pins
               CLAUDE_CODE_AUTO_COMPACT_WINDOW) instead of an unattended tmux
               session nobody is watching, and a WAKE_BLOCKLIST target is
               refused outright. Non-manager targets are unaffected apart from
               that refusal. Default False leaves every existing caller's
               behaviour exactly as it was.
        admin: Keyword-only, and an ALREADY-DECIDED verdict — never a request.
               True means a caller holding the caller env ran the full 5-leg
               admin-grant check and it passed (FPLAN-0401 THE CONTRACT;
               dispatch.py owns that call). A manager target then wakes
               headless through dispatch_monitor like any citizen dispatch.
               This function cannot verify the grant itself: leg 1 needs
               AIPASS_CALLER_*, which its in-process callers do not carry.
               WAKE_BLOCKLIST still refuses — admin raises the stakes, not the
               fence. Default False = today's manager gate, untouched.

    Returns:
        Tuple of (DispatchStatus with all steps, overall success bool)

        The bool means "the dispatch did what it should", NOT "an agent was woken".
        A manager target returns True having deliberately woken nothing — mail is
        delivered and the wake is skipped by design (see Step 3). Callers that need
        to know whether a process actually started must check
        status.find_step("manager"): "info" = gate skipped the wake, "ok" = a
        manager spawn went ahead. Which spawn it was is named separately:
        status.find_step("scheduled") is present only for the headless lane, and
        the interactive tmux spawn reports its session in the "spawn" step.
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
    result = resolve_branch(branch_email, admin=admin)
    if result is None:
        status.fail("resolve", f"Branch not found: {branch_email}")
        return status, False

    branch_path, email = result
    status.ok("resolve", f"{email} → {branch_path}")

    # Step 2b: Blocklist — no privileged lane ever spawns a blocked target.
    # Checked BEFORE the passport read on purpose: an unreadable or missing
    # passport must never be the reason @devpulse gets spawned at 5am, and a
    # verified admin grant is permission to wake OTHERS, never to wake the
    # blocked seat. The manual/dispatch paths keep enforcing this in
    # dispatch.py._orchestrate_wake; this is the same rule at the one entry
    # point a scheduler or an admin lane calls directly.
    if (scheduled or admin) and is_wake_blocked(email):
        lane = "scheduled" if scheduled else "admin"
        status.fail("blocklist", f"{email} is on WAKE_BLOCKLIST — refused in the {lane} lane")
        logger.warning("[wake] BLOCKED %s — %s wake refused by WAKE_BLOCKLIST", email, lane)
        return status, False

    # Step 3: Manager check — managers are never woken, mail only.
    # Exceptions, in order:
    #   scheduled=True  → headless through dispatch_monitor. An unattended 5am
    #     run must carry the monitor's guarantees (context pin, bounce, lock
    #     cleanup); a tmux session with no one attached has none of them.
    #   sender=@daemon  → interactive tmux. A branch's .daemon/schedule.json is
    #     self-authored (the daemon cannot write another branch's files), so a
    #     daemon-scheduled wake is the manager waking ITSELF — consent is the
    #     schedule's existence.
    # Dispatch/manual wakes remain blocked.
    passport_file = branch_path / ".trinity" / "passport.json"
    manager_scheduled = False  # daemon-scheduled manager wake → interactive tmux spawn
    # Bound before the try so the model policy below reads a defined value on
    # every path. An unreadable passport means "" — not a manager, the same
    # direction the gate itself already fails in.
    citizen_class = ""
    try:
        with open(passport_file, "r", encoding="utf-8") as f:
            passport = json.load(f)
        citizen_class = passport.get("identity", {}).get("citizen_class", "")
        if citizen_class == MANAGER_CLASS:
            if scheduled:
                status.ok("manager", f"{email} manager gate bypassed — scheduled wake")
                status.ok("scheduled", "Headless lane — dispatch_monitor pipeline (context pin applies)")
                logger.info("[wake] %s manager woken headless — scheduled lane", email)
            elif admin:
                status.ok("manager", f"{email} manager gate bypassed — verified admin dispatch")
                status.ok("admin", "Headless lane — dispatch_monitor pipeline (admin grant verified by caller)")
                logger.info("[wake] %s manager woken headless — admin lane", email)
            elif sender == "@daemon":
                manager_scheduled = True
                status.ok("manager", f"{email} manager gate bypassed — daemon-scheduled self-wake")
                logger.info("[wake] %s manager gate bypassed — @daemon scheduled wake", email)
            else:
                # Returns True having woken nothing and sent nothing. The caller
                # owns the notification: the dispatch pipeline already mailed this
                # manager before calling, and dispatch_monitor's wake-back mails it
                # via _mail_wake_back(). Saying "mail delivered" here asserted a
                # delivery this function never makes, which is how the wake-back's
                # silent drop read as success for months (@devpulse P0, 2026-08-21).
                status.info("manager", f"{email} is a manager — wake skipped, caller must mail")
                logger.info("[wake] %s is citizen_class=manager — wake skipped, no mail sent here", email)
                return status, True
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.info("[wake] Could not read passport for %s: %s", email, exc)

    # Step 3b: Model policy, decided ONCE for both spawn lanes. Resolved here
    # rather than at each spawn site because the passport this gate just read is
    # the ruling's only input — asking the interactive lane to answer it again
    # would put the managers-only-Fable rule in two places, and @vera reached
    # Fable by CLI accident precisely because no site owned the answer.
    resolved_model = resolve_wake_model(citizen_class, model)
    status.ok("model", f"{resolved_model} ({citizen_class or 'unclassified'})")

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

    # A @daemon-sender manager wake spawns an interactive tmux session instead
    # of the -p/monitor pipeline below. The scheduled lane deliberately does not
    # set this flag — an unattended run belongs in the monitored pipeline.
    if manager_scheduled:
        return _spawn_manager_interactive(branch_path, email, custom_message or DEFAULT_PROMPT, resolved_model, status)

    # Step 7: Build spawn command
    config = _load_config()
    max_turns = config.get("max_turns_per_wake", 100)

    if custom_message:
        prompt = f"Hi. {custom_message} "
    else:
        prompt = f"{DEFAULT_PROMPT} "
    # Monitor owns lock cleanup end-to-end, so the prompt no longer tells the
    # agent to delete the lock: an agent deleting it while its own monitor is
    # still alive lets a second monitor spawn onto a "clear" lock, and the two
    # then race over one lock file. Rationale from reading the cleanup paths —
    # not a logged incident; the monitor's PID-verified cleanup is the guard.
    prompt += (
        "IMPORTANT: run any sub-agents synchronously (foreground) and wait for them to "
        "finish before ending your turn — headless dispatch kills orphaned background "
        "work after 600s with no reply sent."
    )

    base_args = [
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

    # Which session this dispatch lands in is decided by a written record, not
    # by a file mtime. `-c` means "continue the most recently MODIFIED transcript
    # in this directory", so a --fresh run, a late-flushing dispatch or a human
    # opening a terminal here silently re-points the NEXT wake into somebody
    # else's thread. session_pointer names the session instead; the -c branch
    # below stays as the fallback for branches that have no usable pointer yet.
    if fresh:
        session_id = session_pointer.mint_session_id()
        # Written BEFORE the spawn on purpose: the CLI accepts the id we hand it
        # and returns that same id, so there is no window in which a crash
        # leaves a live session nobody recorded.
        if not session_pointer.write_pointer(branch_path, session_id, "wake-fresh"):
            # Never fatal. A branch whose pointer cannot be written must still
            # wake — the next non-fresh dispatch simply falls back to -c.
            logger.warning("[wake] %s pointer write failed for session %s — spawning anyway", email, session_id)
        logger.info("[wake] %s fresh session %s", email, session_id)
        status.ok("session", f"fresh session {session_id[:8]}")
        claude_cmd = [_CLAUDE_BIN, *base_args, "--session-id", session_id]
    else:
        resume_id, reason = session_pointer.resolve_resume_target(branch_path)
        # Verbatim: this reason string is the only trace left when an agent
        # wakes somewhere unexpected.
        logger.info("[wake] %s session decision: %s", email, reason)
        if resume_id:
            status.ok("session", f"resuming {resume_id[:8]} (pointer)")
            claude_cmd = [_CLAUDE_BIN, "--resume", resume_id, *base_args]
        else:
            status.info("session", "no pointer — continuing newest transcript (-c)")
            claude_cmd = [_CLAUDE_BIN, "-c", *base_args]

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

    # ─── Register the dispatch BEFORE anything spawns (FPLAN-0452 P0) ───
    # Patrick's rule 1: the watchdog knows what is outstanding because it was
    # TOLD. Written here, above the spawn, so a spawn that never starts still
    # leaves evidence the dispatch was promised — evidence written after a
    # successful spawn only ever records the dispatches that were already fine.
    #
    # expected_by uses the monitor's own HARD_TIMEOUT, never a number invented
    # here. That is what makes "past expected_by with no completion record"
    # mean the monitor DIED: a live one kills the run at HARD_TIMEOUT and
    # reports, so it cannot legitimately overrun.
    from aipass.ai_mail.apps.handlers.dispatch import register
    from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import HARD_TIMEOUT

    # Clear any INHERITED id first. spawn_env is a copy of this process's
    # environment, and a dispatched agent dispatching another agent would
    # otherwise hand the child its OWN dispatch id — every mail the child sent
    # would be attributed to the parent's run. Same class of leak as the
    # AIPASS_CALLER_* strip above, and it fails closed: no id beats a wrong one.
    spawn_env.pop("AIPASS_DISPATCH_ID", None)

    dispatch_id = register.open_dispatch(
        sender=sender,
        target=email,
        subject=subject or "",
        expected_seconds=HARD_TIMEOUT,
    )
    if dispatch_id:
        spawn_env["AIPASS_DISPATCH_ID"] = dispatch_id
        status.ok("register", f"Registered as {dispatch_id[:8]}")
    else:
        # open_dispatch already logged why. The dispatch still goes: a register
        # that cannot record must not also be able to CANCEL work.
        status.info("register", "Not registered — completion will be unattributable")

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

    # Notification feed event
    notif_body = custom_message[:80] if custom_message else "Manual wake: check inbox"
    try:
        from aipass.ai_mail.apps.handlers.notify import send_notification

        send_notification(f"@{email.lstrip('@')} waking", notif_body, source=email.lstrip("@"), kind="wake")
    except Exception:
        logger.info("[wake] Notification feed unavailable")

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
        print("  --sender @branch Set return-to-sender for bounce emails (default: @devpulse).")
        print("                   Privilege-bearing values must match the verified caller.")
        print("  --model NAME     Model to use: opus (default), sonnet, haiku, or full model ID")
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

    # --sender is a CLI string and lands on the privilege-bearing `sender`
    # param, so it goes through the same verified-caller rail the routed
    # commands use (FPLAN-0401). Closed here at @devpulse's request once the
    # admin lane raised the stakes: the script surface no longer differs from
    # the drone surface.
    from aipass.ai_mail.apps.handlers.users.verified_caller import resolve_wake_sender, sender_claim_refusal

    claim_refusal = sender_claim_refusal(use_sender)
    if claim_refusal:
        print(f"❌ Wake refused: {claim_refusal}", file=sys.stderr)
        sys.exit(2)

    dispatch_status, success = wake_branch(
        branch, message, fresh=use_fresh, auto=use_auto, sender=resolve_wake_sender(use_sender), model=use_model
    )
    print(dispatch_status.format())
    sys.exit(0 if success else 1)
