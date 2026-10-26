# =================== AIPass ====================
# Name: cc_sessions.py
# Version: 3.6.0
# Description: CC-native session discovery, listing, and reclaim
# Branch: hooks
# Layer: apps/modules
# Created: 2026-06-30
# Modified: 2026-10-25
# =============================================

"""Read Claude Code native session files (~/.claude/sessions/<pid>.json).

CC keeps them resume- and exit-aware: the authoritative source of which sessions are live for a cwd.
"""

import json
import os
import signal
import sys
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.handlers.config.loader import aipass_home
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console


def _claude_home() -> Path:
    """Home directory for Claude's state, or an unusable sentinel if unknown.

    Path.home() raises when home is unresolvable (Windows without %USERPROFILE%);
    at module scope that is an import crash.
    """
    try:
        return Path.home()
    except RuntimeError as e:
        logger.warning("[%s] Cannot resolve home directory (%s) - treating ~/.claude as absent", __name__, e)
        return Path("<no-home>")


CC_SESSIONS_DIR = _claude_home() / ".claude" / "sessions"

# Seams read at call time, so a test can stand in without replacing os.kill / sys.platform process-wide.
_kill = os.kill
_PLATFORM = sys.platform

HELP_COMMANDS = [
    ("sessions", "List all CC sessions (PID · branch · short-id · kind · age)"),
    ("sessions reclaim [@branch]", "Properly stop sessions — clean slate"),
]


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
        logger.info("[%s] ppid lookup failed for PID %d: %s", __name__, pid, exc)
    return None


def _has_session_file(pid: int) -> bool:
    """Check whether CC holds a session file for this PID.

    Through CC_SESSIONS_DIR, not Path.home(), so an unresolvable home answers False instead of raising.
    """
    return (CC_SESSIONS_DIR / f"{pid}.json").is_file()


def process_args(pid: int) -> list[str] | None:
    """The argv of a process ([] for a kernel thread), or None when it cannot be read."""
    import subprocess as _sp

    if _PLATFORM.startswith("linux"):
        try:
            raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError as exc:
            logger.info("[%s] cmdline read failed for PID %d: %s", __name__, pid, exc)
            return None
        return [arg for arg in raw.decode("utf-8", errors="replace").split("\0") if arg]
    # shortcut: ps joins argv with spaces, so an arg holding one splits; fine for argv0 and flags, upgrade if more is read.
    try:
        result = _sp.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
    except (OSError, _sp.TimeoutExpired) as exc:
        logger.info("[%s] args lookup failed for PID %d: %s", __name__, pid, exc)
        return None
    return result.stdout.split() if result.returncode == 0 else None


def _argv0_name(pid: int) -> str:
    args = process_args(pid)
    return Path(args[0]).name if args else ""


def _ancestors() -> list[int]:
    """This process and up to 11 parents, nearest first; the walk stops at init or a failed lookup."""
    pid = os.getpid()
    chain = [pid]
    while len(chain) < 12:
        ppid = _get_ppid_portable(pid)
        if not ppid or ppid == pid or ppid <= 1:
            break
        chain.append(ppid)
        pid = ppid
    return chain


def cli_ancestor(name: str) -> list[str] | None:
    """The argv of the nearest ancestor whose program is named `name` (e.g. "claude"), or None when none is."""
    for pid in _ancestors():
        if _argv0_name(pid) == name:
            return process_args(pid)
    return None


def resolve_session_pid() -> int | None:
    """Walk the parent process chain to find the persistent claude session PID.

    Matched by session file, not comm: the CC binary is version-named.
    """
    pid = os.getpid()
    ancestors = []
    for _ in range(12):
        ancestors.append(str(pid))
        if _has_session_file(pid):
            logger.info("[%s] Resolved session PID: %d (chain: %s)", __name__, pid, " -> ".join(ancestors))
            return pid
        ppid = _get_ppid_portable(pid)
        if not ppid or ppid == pid or ppid <= 1:
            break
        pid = ppid
    if any(_argv0_name(int(p)) == "codex" for p in ancestors):
        logger.debug("[%s] Codex session, no Claude session file (chain: %s)", __name__, " -> ".join(ancestors))
        return None
    logger.info("[%s] No session-file ancestor found (chain: %s)", __name__, " -> ".join(ancestors))
    return None


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


def _proc_start_ticks(pid: int) -> str | None:
    """Read a live process's start time (field 22 of /proc/<pid>/stat), in
    clock ticks since boot. Linux only — returns None elsewhere or on any
    read failure, so callers can fall back to liveness-only checking.
    """
    if _PLATFORM != "linux":
        return None
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        # comm (field 2) may itself contain ')' or whitespace: split on the last ')'.
        fields_after_comm = raw.rsplit(")", 1)[1].split()
        return fields_after_comm[19]  # field 22 overall, starttime
    except (OSError, IndexError) as exc:
        logger.info("[CC_SESSIONS] Cannot read /proc/%d/stat: %s", pid, exc)
        return None


def _session_pid_matches(session: dict) -> bool:
    """Verify the live PID is still the same process that wrote this session
    file — not an unrelated process that later reused the same PID number.
    """
    recorded = session.get("procStart")
    if not recorded:
        return True
    pid = session.get("pid")
    if not isinstance(pid, int):
        return True
    live_start = _proc_start_ticks(pid)
    if live_start is None:
        return True
    return str(live_start) == str(recorded)


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID exists."""
    if not isinstance(pid, int) or pid <= 1:
        return False
    if _PLATFORM == "win32":
        try:
            return _pid_alive_windows(pid)
        except Exception as exc:
            logger.info("[CC_SESSIONS] PID %d Windows check failed (assuming alive): %s", pid, exc)
            return True
    try:
        _kill(pid, 0)
        return True
    except ProcessLookupError:
        logger.info("[CC_SESSIONS] PID %d not found (dead)", pid)
        return False
    except PermissionError:
        logger.info("[CC_SESSIONS] PID %d exists but permission denied — treating as alive", pid)
        return True
    except OSError as exc:
        logger.info("[CC_SESSIONS] PID %d os.kill failed: %s — treating as dead", pid, exc)
        return False


def _format_age(session: dict) -> str:
    """Format session age from its start time."""
    started = session.get("startedAt") or session.get("started", "")
    if not started:
        return "?"
    try:
        from datetime import datetime, timezone

        if isinstance(started, (int, float)):
            start_dt = datetime.fromtimestamp(started / 1000, tz=timezone.utc)
        else:
            start_dt = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        delta = datetime.now(tz=timezone.utc) - start_dt
        hours = int(delta.total_seconds() // 3600)
        minutes = int((delta.total_seconds() % 3600) // 60)
        if hours > 0:
            return f"{hours}h{minutes}m"
        return f"{minutes}m"
    except Exception as exc:
        logger.info("[CC_SESSIONS] age format error: %s", exc)
        return "?"


def _session_branch(session: dict) -> str:
    """Extract the branch name from a session's cwd."""
    cwd = session.get("cwd", "")
    return Path(cwd).name if cwd else "?"


def _session_short_id(session: dict) -> str:
    """Extract short session ID (first 8 chars of sessionId)."""
    return str(session.get("sessionId", ""))[:8]


def read_all_sessions() -> list[dict]:
    """Read all CC session PID files. Returns list of session dicts."""
    if not CC_SESSIONS_DIR.is_dir():
        return []
    sessions = []
    for f in CC_SESSIONS_DIR.iterdir():
        if not f.name.endswith(".json") or not f.stem.isdigit():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sessions.append(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.info("[CC_SESSIONS] Failed to read %s: %s", f, exc)
    return sessions


def find_live_for_cwd(cwd: str) -> list[dict]:
    """Find all live CC sessions whose cwd matches the given directory."""
    target = str(Path(cwd).resolve())
    live = []
    for session in read_all_sessions():
        session_cwd = session.get("cwd", "")
        if not session_cwd:
            continue
        if str(Path(session_cwd).resolve()) != target:
            continue
        pid = session.get("pid")
        if not pid or not _is_pid_alive(pid):
            logger.info(
                "[CC_SESSIONS] Stale session file for PID %s at %s",
                pid,
                session_cwd,
            )
            continue
        if not _session_pid_matches(session):
            logger.warning(
                "[CC_SESSIONS] PID %s reused (procStart mismatch) — treating stale session as dead at %s",
                pid,
                session_cwd,
            )
            continue
        live.append(session)
    return live


def session_start(session: dict) -> float | None:
    """Epoch seconds a session began, or None when it cannot be told.

    CC writes startedAt as epoch milliseconds; older files carry an ISO string.
    """
    started = session.get("startedAt") or session.get("started", "")
    if not started:
        return None
    try:
        if isinstance(started, (int, float)):
            return float(started) / 1000
        from datetime import datetime

        return datetime.fromisoformat(str(started).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OSError) as exc:
        logger.info("[CC_SESSIONS] cannot read session start: %s", exc)
        return None


def _occupant_rank(session: dict) -> tuple[int, float]:
    """Order occupants so the one that MATTERS is first: seats before jobs, oldest first.

    Ranking, not filtering: a bg-only branch still answers with its bg session.
    """
    is_job = 1 if session.get("kind") in ("bg", "background") else 0
    started = session_start(session)
    return (is_job, started if started is not None else float("inf"))


def find_occupant(cwd: str, exclude_pid: int | None = None) -> dict | None:
    """Find the live CC session occupying the given cwd, excluding our own PID.

    A caller skipping jobs must never be handed a job while a seat sits behind it.
    """
    candidates = [
        session for session in find_live_for_cwd(cwd) if exclude_pid is None or session.get("pid") != exclude_pid
    ]
    if not candidates:
        return None
    return min(candidates, key=_occupant_rank)


def _stop_session(session: dict) -> str:
    """Stop a session. Returns description of action taken.

    Never SIGTERMs a bg session: the daemon respawns it.
    """
    pid = session.get("pid")
    kind = session.get("kind", "unknown")
    branch = _session_branch(session)

    if kind in ("bg", "background"):
        logger.info("[CC_SESSIONS] Cannot stop bg PID %s — no per-job stop in CLI", pid)
        return f"PID {pid} ({branch}): bg session — no per-job stop available"

    if pid and _is_pid_alive(pid):
        try:
            _kill(pid, signal.SIGTERM)
        except OSError as exc:
            logger.warning("[CC_SESSIONS] Failed to SIGTERM PID %d: %s", pid, exc)
            return f"PID {pid} ({branch}): SIGTERM failed ({exc})"
        return f"PID {pid} ({branch}): sent SIGTERM to {kind} session"
    return f"PID {pid} ({branch}): already dead"


def registered_branch_dir(name: str) -> str | None:
    """The directory AIPASS_REGISTRY.json registers for branch *name*, or None when it names none."""
    home = aipass_home()
    registry = home / "AIPASS_REGISTRY.json" if home is not None else None
    if registry is None or not registry.is_file():
        return None
    branches = json.loads(registry.read_text(encoding="utf-8")).get("branches", [])
    for entry in branches:
        if isinstance(entry, dict) and str(entry.get("name", "")).lower() == name.lower() and entry.get("path"):
            return str(home / entry["path"])
    return None


def reclaim(branch_dir: str | None = None) -> list[str]:
    """Properly stop sessions, optionally only those whose cwd is *branch_dir*. Returns action log.

    The whole directory, never its last name: two projects can each hold a branch called hooks."""
    target = str(Path(branch_dir).resolve()) if branch_dir else None
    actions = []
    for session in read_all_sessions():
        pid = session.get("pid")
        if not pid or not _is_pid_alive(pid) or not _session_pid_matches(session):
            continue
        if target and str(Path(session.get("cwd") or "?").resolve()) != target:
            continue
        action = _stop_session(session)
        actions.append(action)
        logger.info("[CC_SESSIONS] reclaim: %s", action)
    return actions


def _print_sessions_list():
    """Print all CC sessions in P6 format: PID · branch · short-id · kind · age."""
    sessions = read_all_sessions()
    if not sessions:
        CONSOLE.print("  No CC session files found")
        return
    for s in sessions:
        pid = s.get("pid", "?")
        branch = _session_branch(s)
        short_id = _session_short_id(s)
        kind = s.get("kind", "?")
        age = _format_age(s)
        alive = _is_pid_alive(pid) if isinstance(pid, int) else False
        status = "[green]live[/green]" if alive else "[dim]stale[/dim]"
        CONSOLE.print(f"  PID {pid} · {branch} · {short_id} · {kind} · {age}  {status}")


def print_introspection():
    """Print CC session state for drone routing."""
    CONSOLE.print("[bold cyan]sessions[/bold cyan] — CC session listing & reclaim")
    CONSOLE.print(f"  Sessions dir: {CC_SESSIONS_DIR}")
    _print_sessions_list()


def handle_command(command: str, args: list) -> bool:
    """Route sessions/cc_sessions commands from drone @hooks."""
    if command in ("--help", "-h", "help"):
        CONSOLE.print("[bold cyan]sessions[/bold cyan] — CC session listing & reclaim")
        CONSOLE.print()
        CONSOLE.print("  drone @hooks sessions                  List all CC sessions")
        CONSOLE.print("  drone @hooks sessions reclaim          Stop all live sessions")
        CONSOLE.print("  drone @hooks sessions reclaim @branch  Stop sessions for a branch")
        CONSOLE.print()
        CONSOLE.print("  drone @hooks cc_sessions               (legacy alias for sessions)")
        return True

    if command in ("sessions", "cc_sessions"):
        if not args:
            print_introspection()
            return True

        if wants_help(args):
            CONSOLE.print("[bold cyan]sessions[/bold cyan] — CC session listing & reclaim")
            CONSOLE.print()
            CONSOLE.print("  drone @hooks sessions                  List all CC sessions")
            CONSOLE.print("  drone @hooks sessions reclaim          Stop all live sessions")
            CONSOLE.print("  drone @hooks sessions reclaim @branch  Stop sessions for a branch")
            return True

        if args[0] == "reclaim":
            branch_filter = None
            if len(args) > 1:
                branch_filter = args[1].lstrip("@")
            CONSOLE.print(f"[bold cyan]sessions reclaim[/bold cyan]{f' @{branch_filter}' if branch_filter else ''}")
            branch_dir = registered_branch_dir(branch_filter) if branch_filter else None
            if branch_filter and branch_dir is None:
                CONSOLE.print(f"  @{branch_filter} is not a registered branch: nothing reclaimed")
                return True
            actions = reclaim(branch_dir)
            if not actions:
                CONSOLE.print("  No live sessions to reclaim")
            else:
                for action in actions:
                    CONSOLE.print(f"  {action}")
            return True

    return False
