# =================== AIPass ====================
# Name: wake.py
# Description: Manual Branch Wake Handler
# Version: 3.4.0
# Created: 2026-03-02
# Modified: 2026-10-17
# =============================================

"""
Manual Branch Wake Handler

Reference: docs/wake_pipeline.md
"""

import json
import os
import shlex
import shutil
import sys
import subprocess
import time
from pathlib import Path
from typing import NamedTuple, Optional, Tuple, List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root
from aipass.ai_mail.apps.handlers.dispatch import session_pointer
from aipass.ai_mail.apps.handlers.dispatch.pid_lock import (
    acquire_lock,
    check_lock,
    check_pid_alive,
    clean_zombies,
    is_branch_occupied,
)
from aipass.ai_mail.apps.handlers.dispatch.wake_dashboard import (
    refresh_recipient_dashboard as _refresh_recipient_dashboard,
)


def _find_claude_bin() -> str:
    """Locate the claude binary, checking known install locations if not on PATH.

    Resolved per wake, not at import, so a binary installed after load is found.
    Raises FileNotFoundError naming what was searched; never the bare name.
    """
    found = shutil.which("claude")
    if found:
        return found
    candidates = [
        Path.home() / ".local" / "bin" / "claude",
        Path("/usr/local/bin/claude"),
        Path("/usr/bin/claude"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    searched = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"claude not found on PATH or at {searched}")


_REPO_ROOT = find_repo_root()
_AI_MAIL_DIR = Path(__file__).resolve().parents[3]  # ai_mail/
# Untracked on purpose: it holds the Fable grant, which the repo must not ship.
CONFIG_FILE = _AI_MAIL_DIR / ".ai_mail.local" / "safety_config.json"
BRANCH_REGISTRY = _REPO_ROOT / "AIPASS_REGISTRY.json"
PAUSE_FILE = _REPO_ROOT / ".aipass" / "autonomous_pause"
MONITOR_SCRIPT = Path(__file__).parent / "dispatch_monitor.py"

DEFAULT_PROMPT = "Hi. Check inbox, process new emails, update memories when done."

KNOWN_MODEL_ALIASES: frozenset = frozenset({"sonnet", "opus", "haiku", "fable"})
# The README names this default; change both together.
DEFAULT_MODEL = "opus"

MANAGER_CLASS = "manager"

# Fable is granted by name, not class. Only the fallback: the live grant is read from CONFIG_FILE.
FABLE_GRANT_DEFAULT: frozenset[str] = frozenset({"@devpulse"})
FABLE_GRANT_KEY = "fable_allowed"

# The marking tmux cannot half-apply: a person deciding whether to kill a window reads it.
DAEMON_SESSION_PREFIX = "AIPASS-DAEMON-WAKE-"

# dispatch.py._orchestrate_dispatch_send bypasses this check.
WAKE_BLOCKLIST: frozenset[str] = frozenset({"@devpulse"})


def is_wake_blocked(target: str) -> bool:
    """Return True if `target` is on the manual-wake blocklist."""
    return f"@{target.lstrip('@').lower()}" in WAKE_BLOCKLIST


class ModelDecision(NamedTuple):
    """What a wake spawns on, and what the caller has to be told about it."""

    model: str
    #: "" when nothing was refused. Never None: callers test it for truth.
    refusal: str


def _is_fable(model: str) -> bool:
    """True for any spelling of Fable — bare alias, full id, any casing.

    Substring on purpose: the CLI also takes full ids like `claude-fable-5`.
    """
    return "fable" in model.lower()


def _normalise_address(target: str) -> str:
    """One leading @, lowercase — the spelling the grant is keyed on.

    A policy keyed on an address must not be escapable by typing it differently.
    """
    return f"@{target.lstrip('@').lower()}"


def fable_allowed() -> frozenset:
    """Which addresses may run Fable.

    Missing, malformed or unreadable config falls back to the default, never to empty;
    an EXPLICIT empty list is honoured (it revokes the grant from everyone).
    """
    try:
        config = _read_json(CONFIG_FILE)
    except JsonUnreadable as e:
        logger.warning("[wake] %s — the Fable grant falls back to the default", e)
        return FABLE_GRANT_DEFAULT
    if not isinstance(config, dict) or FABLE_GRANT_KEY not in config:
        return FABLE_GRANT_DEFAULT
    granted = config[FABLE_GRANT_KEY]
    if not isinstance(granted, list):
        logger.warning(
            "[wake] %s in %s is %s, not a list — falling back to the default grant %s",
            FABLE_GRANT_KEY,
            CONFIG_FILE,
            type(granted).__name__,
            sorted(FABLE_GRANT_DEFAULT),
        )
        return FABLE_GRANT_DEFAULT
    return frozenset(_normalise_address(str(entry)) for entry in granted)


def resolve_wake_model(target_email: str, requested: Optional[str]) -> ModelDecision:
    """The model this wake spawns on.

    A refused Fable request never stalls the wake: it runs on DEFAULT_MODEL and the refusal is
    returned. Nothing requested means DEFAULT_MODEL, granted seats too.
    """
    if not requested:
        return ModelDecision(DEFAULT_MODEL, "")

    if not _is_fable(requested):
        return ModelDecision(requested, "")

    target = _normalise_address(target_email)
    if target in fable_allowed():
        return ModelDecision(requested, "")

    refusal = (
        f"{target} may not run Fable — {requested!r} refused, waking on "
        f"{DEFAULT_MODEL} instead (the owner's ruling 2026-09-08: Fable is "
        f"granted by name and this seat does not hold the grant)"
    )
    logger.warning("[wake] %s", refusal)
    return ModelDecision(DEFAULT_MODEL, refusal)


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

        The success bool cannot say "delivered, deliberately not woken"; read the gate's step.
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


class JsonUnreadable(Exception):
    """A JSON file that exists and cannot be read or parsed."""


def _read_json(filepath: Path) -> Optional[dict]:
    """Read and parse a JSON file; None when it does not exist.

    Raises JsonUnreadable when it exists and cannot be read; each caller gives its own answer.
    """
    if not filepath.exists():
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise JsonUnreadable(f"{filepath.name} could not be read ({filepath}): {e}") from e


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


def prepend_path(spawn_env: dict, directory: str) -> None:
    """Put directory first on PATH once: background launchers (trigger, prax watchdog) run with a restricted one."""
    if directory not in spawn_env.get("PATH", ""):
        spawn_env["PATH"] = directory + os.pathsep + spawn_env.get("PATH", "")


def spawn_in_systemd_scope(monitor_cmd, branch_path, spawn_env, branch_email, lock_file_path, custom_message, status):
    """Spawn monitor in its own systemd unit to survive cgroup cleanup.

    KillMode=control-group would SIGTERM the detached monitor when a oneshot service exits.
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
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("[wake] systemd-run failed: %s", e)
        return False
    finally:
        # EnvironmentFile is read at unit start; the environment copy must not outlive the launch.
        env_file.unlink(missing_ok=True)
    if result.returncode != 0:
        logger.warning("[wake] systemd-run failed (rc=%d): %s", result.returncode, result.stderr.strip())
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


def is_manager(branch_email: str) -> bool:
    """True when `branch_email` is citizen_class=manager, i.e. never woken.

    Lets dispatch promise "you will be MAILED". An unreadable passport fails closed (True),
    matching wake_branch's manager gate; a missing one is False.
    """
    from aipass.ai_mail.apps.handlers.registry.read import RegistryUnreadable

    try:
        resolved = resolve_branch(branch_email)
    except RegistryUnreadable as exc:
        # Fail closed, as for an unreadable passport.
        logger.warning("[wake] %s unresolvable — treated as a manager: %s", branch_email, exc)
        return True
    if not resolved:
        return False
    branch_path, _ = resolved
    try:
        with open(branch_path / ".trinity" / "passport.json", "r", encoding="utf-8") as f:
            passport = json.load(f)
    except FileNotFoundError as exc:
        logger.info("[wake] No passport to classify %s: %s", branch_email, exc)
        return False
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[wake] Passport of %s unreadable — treated as a manager: %s", branch_email, exc)
        return True
    return passport.get("identity", {}).get("citizen_class", "") == "manager"


def _external_citizens(repo_root: Path) -> List[dict]:
    """Every declared-root citizen, straight from @memory's public gateway.

    The one entry for the external tier; lazy, by module, so the branch imports without @memory.
    Never read AIPASS_ROOTS.json here: two readers of one anchor drift.
    """
    from aipass.memory.apps.modules import fleet

    return fleet.external_branches(repo_root=repo_root)


def resolve_branch(branch_email: str, admin: bool = False) -> Optional[Tuple[Path, str]]:
    """Resolve a branch email to its absolute filesystem path.

    Precedence: AIPass registry, caller's project registry, admin-only projects/* sweep, external tier.
    Local always wins, so the external tier is LAST. Raises RegistryUnreadable rather than serve a namesake.
    """
    email = f"@{branch_email.lstrip('@').lower()}"
    from aipass.ai_mail.apps.handlers.registry.read import RegistryUnreadable

    # An unreadable registry refuses: read as absent, steps 2-4 could serve a namesake.
    try:
        registry = _read_json(BRANCH_REGISTRY)
    except JsonUnreadable as e:
        raise RegistryUnreadable(f"{BRANCH_REGISTRY.name} could not be read ({BRANCH_REGISTRY})") from e
    if registry is not None:
        for branch in registry.get("branches", []):
            if branch.get("email", "").lower() == email:
                path = Path(branch.get("path", ""))
                if not path.is_absolute():
                    path = _REPO_ROOT / path
                if path.exists():
                    return path, email
                return None  # Found but path missing — definitive failure

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
        except RegistryUnreadable:
            raise
        except Exception as e:
            logger.warning("[wake] resolve_branch caller registry fallback failed: %s", e)

    # Verified-admin only; the caller already proved the grant.
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
        except RegistryUnreadable:
            raise
        except Exception as e:
            logger.warning("[wake] resolve_branch projects sweep failed: %s", e)

    # A tier that cannot answer returns a miss, never a traceback.
    try:
        candidates = [
            citizen
            for citizen in _external_citizens(_REPO_ROOT)
            if isinstance(citizen.get("email"), str) and citizen["email"].lower() == email
        ]
        if candidates:
            if len(candidates) > 1:
                # [0] is the first-declared root; still an error, two roots claiming one address must be seen.
                logger.error(
                    "[wake] %s is claimed by %d declared roots — resolving to %s by DECLARATION ORDER "
                    "(first-declared root wins, per the fleet ruling). Other claimants: %s",
                    email,
                    len(candidates),
                    candidates[0]["path"],
                    ", ".join(str(citizen["path"]) for citizen in candidates[1:]),
                )
            branch_path = Path(candidates[0]["path"])
            # No exists() check: the gateway only admits a directory with a passport file.
            logger.info("[wake] %s resolved via the declared-roots external tier", email)
            return branch_path, email
    except Exception as e:
        logger.warning("[wake] resolve_branch external tier failed: %s", e)

    return None


def _mark_daemon_session(session: str, email: str, status: "DispatchStatus") -> None:
    """Tag a live tmux session as daemon work, machine-readably.

    Best effort, never fatal; this owns the "mark" step for both outcomes (find_step reads the last).
    Not the dispatch register: this lane has no monitor or timeout to close an entry.
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
    claude_bin: str,
) -> Tuple["DispatchStatus", bool]:
    """Spawn an interactive tmux session for a manager branch.

    Only @daemon self-wakes, so it always runs with bypassPermissions: nobody is there to answer.
    No lock or monitor: the occupancy check is the one-instance guard. `model` is already resolved.
    """
    if shutil.which("tmux") is None:
        status.fail("tmux", "tmux not found — cannot spawn interactive manager session")
        logger.warning("[wake] %s manager wake failed — tmux missing", email)
        return status, False

    # Through a file: survives quoting, debuggable after the fact.
    daemon_dir = branch_path / ".daemon"
    daemon_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = daemon_dir / "last_wake_prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    session = f"{DAEMON_SESSION_PREFIX}{branch_path.name}-{time.strftime('%H%M%S')}"
    claude_line = (
        f"{shlex.quote(claude_bin)} --model {shlex.quote(model)} "
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
        # Before the agent starts: a window is killable from the moment it exists.
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
    wake_back: bool = True,
) -> Tuple[DispatchStatus, bool]:
    """
    Spawn a Claude agent at the target branch with step-by-step status.

    admin is an ALREADY-DECIDED verdict (dispatch.py ran the grant check), never a request.
    True means "did what it should", not "woke an agent": check status.find_step("manager").
    """
    json_handler.log_operation(
        "wake_branch", {"branch": branch_email, "fresh": fresh, "auto": auto, "model": model or DEFAULT_MODEL}
    )

    status = DispatchStatus()

    if auto and PAUSE_FILE.exists():
        status.fail("pause", "System paused (autonomous_pause active)")
        logger.warning("[wake] BLOCKED %s — system paused", branch_email)
        return status, False

    from aipass.ai_mail.apps.handlers.registry.read import RegistryUnreadable

    try:
        result = resolve_branch(branch_email, admin=admin)
    except RegistryUnreadable as exc:
        status.fail("resolve", f"{branch_email} not resolved: {exc}")
        logger.warning("[wake] %s not resolved: %s", branch_email, exc)
        return status, False
    if result is None:
        status.fail("resolve", f"Branch not found: {branch_email}")
        return status, False

    branch_path, email = result
    status.ok("resolve", f"{email} → {branch_path}")

    # Before the passport read: an unreadable passport must never be why @devpulse is spawned.
    if (scheduled or admin) and is_wake_blocked(email):
        lane = "scheduled" if scheduled else "admin"
        status.fail("blocklist", f"{email} is on WAKE_BLOCKLIST — refused in the {lane} lane")
        logger.warning("[wake] BLOCKED %s — %s wake refused by WAKE_BLOCKLIST", email, lane)
        return status, False

    # Managers are mailed, never woken, except: scheduled=True goes headless through the monitor,
    # and sender=@daemon (a self-authored schedule, so the manager's consent) goes to tmux.
    passport_file = branch_path / ".trinity" / "passport.json"
    manager_scheduled = False  # daemon-scheduled manager wake → interactive tmux spawn
    citizen_class = ""
    try:
        with open(passport_file, "r", encoding="utf-8") as f:
            passport = json.load(f)
        citizen_class = passport.get("identity", {}).get("citizen_class", "")
        if citizen_class == MANAGER_CLASS and not (scheduled or admin or sender == "@daemon"):
            # Woken nothing, sent nothing: the caller owns the mail.
            status.info("manager", f"{email} is a manager — wake skipped, caller must mail")
            logger.info("[wake] %s is citizen_class=manager — wake skipped, no mail sent here", email)
            return status, True
        if citizen_class == MANAGER_CLASS:
            if scheduled:
                status.ok("manager", f"{email} manager gate bypassed — scheduled wake")
                status.ok("scheduled", "Headless lane — dispatch_monitor pipeline (context pin applies)")
                logger.info("[wake] %s manager woken headless — scheduled lane", email)
            elif admin:
                status.ok("manager", f"{email} manager gate bypassed — verified admin dispatch")
                status.ok("admin", "Headless lane — dispatch_monitor pipeline (admin grant verified by caller)")
                logger.info("[wake] %s manager woken headless — admin lane", email)
            else:
                manager_scheduled = True
                status.ok("manager", f"{email} manager gate bypassed — daemon-scheduled self-wake")
                logger.info("[wake] %s manager gate bypassed — @daemon scheduled wake", email)
    except FileNotFoundError as exc:
        logger.info("[wake] No passport for %s: %s", email, exc)
    except (json.JSONDecodeError, OSError) as exc:
        # Unknown class may be a manager: fail closed in the lane that never wakes managers.
        if not (scheduled or admin or sender == "@daemon"):
            status.info(
                "manager",
                f"{email} passport unreadable — class unknown, treated as a manager: wake skipped, caller must mail",
            )
            logger.warning("[wake] %s passport unreadable, treated as a manager — wake skipped: %s", email, exc)
            return status, True
        logger.warning("[wake] %s passport unreadable, waking in a lane that wakes managers too: %s", email, exc)

    # Decided ONCE for both spawn lanes; a second site would let the rule drift.
    decision = resolve_wake_model(email, model)
    resolved_model = decision.model
    if decision.refusal:
        # WARN, not fail: the only place the caller learns the model was not honoured.
        status.warn("model", decision.refusal)
    else:
        status.ok("model", resolved_model)

    zombie_count = clean_zombies()
    if zombie_count > 0:
        status.warn("zombies", f"{zombie_count} zombie Claude process(es) detected")
    else:
        status.ok("pre-flight", "No zombie processes")

    existing = check_lock(branch_path)
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

    if is_branch_occupied(branch_path):
        status.warn("occupancy", f"Interactive Claude session in {branch_path}")
        status.fail("blocked", "Cannot spawn — interactive session running")
        logger.warning("[wake] BLOCKED %s — interactive session", email)
        return status, False

    status.ok("occupancy", "No interactive session")

    # The binary, then the dashboard: after every gate that can refuse, before any lock or spawn.
    try:
        claude_bin = _find_claude_bin()
    except FileNotFoundError as e:
        status.fail("claude", str(e))
        logger.warning("[wake] %s not woken: %s", email, e)
        return status, False

    _refresh_recipient_dashboard(branch_path, email, status)

    if manager_scheduled:
        return _spawn_manager_interactive(
            branch_path, email, custom_message or DEFAULT_PROMPT, resolved_model, status, claude_bin
        )

    # An unreadable safety config refuses the wake: its max_turns may be lower than the default.
    try:
        config = _load_config()
    except JsonUnreadable as e:
        status.fail("config", str(e))
        return status, False
    max_turns = config.get("max_turns_per_wake", 100)

    if custom_message:
        prompt = f"Hi. {custom_message} "
    else:
        prompt = f"{DEFAULT_PROMPT} "
    # Never tell the agent to delete its lock: the monitor owns cleanup, and two monitors would race.
    prompt += (
        "Before you build: read the seedgo standards rows for what you touch "
        "(src/aipass/seedgo/docs/aipass_standards.md; drone @seedgo checklist names the "
        "rows for a file) and the test template for tests "
        "(src/aipass/seedgo/templates/test_template_v1.md); build to them; run the "
        "checklist last, to find what you missed. "
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

    # The session comes from session_pointer, not -c's file mtime; -c is the no-pointer fallback.
    if fresh:
        session_id = session_pointer.mint_session_id()
        # Before the spawn, so no crash leaves a live session nobody recorded.
        if not session_pointer.write_pointer(branch_path, session_id, "wake-fresh"):
            logger.warning("[wake] %s pointer write failed for session %s — spawning anyway", email, session_id)
        logger.info("[wake] %s fresh session %s", email, session_id)
        status.ok("session", f"fresh session {session_id[:8]}")
        claude_cmd = [claude_bin, *base_args, "--session-id", session_id]
    else:
        resume_id, reason = session_pointer.resolve_resume_target(branch_path)
        # Verbatim: the only trace left when an agent wakes somewhere unexpected.
        logger.info("[wake] %s session decision: %s", email, reason)
        if resume_id:
            status.ok("session", f"resuming {resume_id[:8]} (pointer)")
            claude_cmd = [claude_bin, "--resume", resume_id, *base_args]
        else:
            status.info("session", "no pointer — continuing newest transcript (-c)")
            claude_cmd = [claude_bin, "-c", *base_args]

    log_dir = branch_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stderr_log = str(log_dir / "dispatch_stderr.log")
    lock_file_path = str(branch_path / ".ai_mail.local" / ".dispatch.lock")

    # wake_back rides argv, never spawn_env, which becomes the agent's own environment.
    from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import NO_WAKE_BACK_FLAG

    monitor_flags = [] if wake_back else [NO_WAKE_BACK_FLAG]
    monitor_cmd = [
        sys.executable,
        str(MONITOR_SCRIPT),
        email,
        lock_file_path,
        sender,
        stderr_log,
        *monitor_flags,
        "--",
        *claude_cmd,
    ]

    spawn_env = os.environ.copy()
    spawn_env["AIPASS_SPAWNED"] = "1"
    spawn_env["AIPASS_SESSION_TYPE"] = "dispatched"
    prepend_path(spawn_env, str(_REPO_ROOT / ".venv" / "bin"))
    prepend_path(spawn_env, str(Path.home() / ".local" / "bin"))
    for key in list(spawn_env.keys()):
        if key.startswith("CLAUDE") or key == "AIPASS_BOT_ID":
            spawn_env.pop(key)

    acquired, lock_msg = acquire_lock(branch_path, os.getpid())
    if not acquired:
        status.fail("lock-acquire", f"Lock failed: {lock_msg}")
        return status, False
    status.ok("lock-acquire", "Dispatch lock acquired")

    # Registered BEFORE the spawn, so a spawn that never starts still leaves the promise.
    from aipass.ai_mail.apps.handlers.dispatch import register
    from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import HARD_TIMEOUT

    # Clear an INHERITED id, or a child's mail would be attributed to the parent's run.
    spawn_env.pop("AIPASS_DISPATCH_ID", None)

    dispatch_id = register.open_dispatch(
        sender=sender,
        target=email,
        subject=subject or "",
        expected_seconds=HARD_TIMEOUT,
        wake_back=wake_back,
    )
    if dispatch_id:
        spawn_env["AIPASS_DISPATCH_ID"] = dispatch_id
        status.ok("register", f"Registered as {dispatch_id[:8]}")
    else:
        status.info("register", "Not registered — completion will be unattributable")

    spawned_via_scope = False
    monitor_pid = 0
    if os.environ.get("INVOCATION_ID") and shutil.which("systemd-run"):
        spawned_via_scope = spawn_in_systemd_scope(
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

            # Best effort: lets a dead monitor show before expected_by.
            if dispatch_id:
                register.record_monitor_pid(dispatch_id, monitor_pid)

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
        if check_pid_alive(monitor_pid):
            status.ok("alive", f"Agent responding (PID {monitor_pid} alive)")
        else:
            status.fail("alive", f"Agent died immediately (PID {monitor_pid})")
            lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
            lock_file.unlink(missing_ok=True)
            return status, False

    notif_body = custom_message[:80] if custom_message else "Manual wake: check inbox"
    try:
        from aipass.ai_mail.apps.handlers.notify import send_notification

        send_notification(f"@{email.lstrip('@')} waking", notif_body, source=email.lstrip("@"), kind="wake")
    except Exception:
        logger.info("[wake] Notification feed unavailable")

    return status, True
