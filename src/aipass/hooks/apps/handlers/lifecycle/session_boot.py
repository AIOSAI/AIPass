# =================== AIPass ====================
# Name: session_boot.py
# Version: 4.4.3
# Description: Boot wrapper — attach-first menu, resumes by pointer (0448), steps aside while dispatched (0449)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-06-30
# Modified: 2026-10-17
# =============================================

"""Boot wrapper for Claude Code sessions.

Menu order: a live dispatch lock outranks the live-session menu, which outranks no-live.
Interactive launches are tmux-wrapped; inside tmux or headless (-p) it execs claude directly.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

_DEFAULT_ARGS = ["--permission-mode", "bypassPermissions"]
_CHAT_LIMIT = 5

# How long 'r' waits for the dispatch monitor to surrender its lock; resuming before races its cleanup.
_RECLAIM_WAIT_S = 10.0
_RECLAIM_POLL_S = 0.5


def _resolve_claude_binary() -> str:
    """Resolve the REAL claude binary path from PATH."""
    path = shutil.which("claude")
    if path:
        return path
    logger.error("[SESSION_BOOT] claude binary not found on PATH")
    return "claude"


def _find_live_sessions(cwd: str) -> list[dict]:
    """Find live CC sessions for the given cwd via cc_sessions module."""
    import importlib

    cc_sessions = importlib.import_module("aipass.hooks.apps.modules.cc_sessions")
    return cc_sessions.find_live_for_cwd(cwd)


def _find_tmux() -> str | None:
    """Find tmux binary on PATH."""
    return shutil.which("tmux")


def _tmux_session_exists(name: str) -> bool:
    """Check if a tmux session with the given name exists.

    No tmux (Windows, or absent) answers "no session" rather than raising.
    """
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("[SESSION_BOOT] tmux has-session unavailable: %s", exc)
        return False
    return result.returncode == 0


def _tmux_kill_session(name: str) -> bool:
    """Kill a tmux session by name. True when the kill was actually delivered.

    A missing tmux raises out of exec (check=False cannot catch it); the exec failure is the probe,
    since shutil.which would read the real PATH in tests that mock only subprocess.run.
    """
    try:
        subprocess.run(["tmux", "kill-session", "-t", name], check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("[SESSION_BOOT] tmux kill-session unavailable: %s", exc)
        return False
    return True


def _find_tmux_session_for_pid(pid: int) -> str | None:
    """Find which tmux session hosts the given PID (as a descendant of a pane).

    Guarded: the multi-session menu calls it, and a host without tmux must not take the menu down.
    """
    try:
        result = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{pane_pid} #{session_name}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("[SESSION_BOOT] tmux list-panes unavailable: %s", exc)
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.strip().splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pane_pid_str, session_name = parts
        try:
            pane_pid = int(pane_pid_str)
        except ValueError:
            logger.info("[SESSION_BOOT] Non-integer pane PID: %s", pane_pid_str)
            continue
        if _is_descendant(pid, pane_pid):
            return session_name
    return None


def _get_ppid(pid: int) -> int | None:
    """Get parent PID portably (Linux + macOS). Returns None on failure."""
    try:
        result = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        logger.info("[SESSION_BOOT] ppid lookup failed for PID %d: %s", pid, exc)
    return None


def _is_descendant(target_pid: int, ancestor_pid: int) -> bool:
    """Check if target_pid is a descendant of ancestor_pid via process tree walk."""
    pid = target_pid
    for _ in range(20):
        if pid == ancestor_pid:
            return True
        if pid <= 1:
            return False
        ppid = _get_ppid(pid)
        if ppid is None:
            return False
        pid = ppid
    return False


def _format_age(session: dict) -> str:
    """Format session age from its start time."""
    started = session.get("startedAt") or session.get("started", "")
    if not started:
        return ""
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
        logger.info("[SESSION_BOOT] age format error: %s", exc)
        return ""


def _session_short_id(session: dict) -> str:
    """Extract first 8 chars of sessionId."""
    return str(session.get("sessionId", ""))[:8]


def _session_label(session: dict) -> str:
    """Format a session's one-line label: PID · short-id · kind [auto-name] · age."""
    pid = session.get("pid", "?")
    short_id = _session_short_id(session)
    kind = session.get("kind", "unknown")
    auto_name = session.get("name", "")
    name_str = f' "{auto_name}"' if auto_name else ""
    age = _format_age(session)
    age_str = f" · {age} old" if age else ""
    return f"PID {pid} · {short_id} · {kind}{name_str}{age_str}"


def _read_choice(prompt: str = "> ") -> str:
    """Read a single-line choice from /dev/tty (works even when stdin is piped)."""
    try:
        tty = open("/dev/tty", "r", encoding="utf-8")
        sys.stderr.write(prompt)
        sys.stderr.flush()
        choice = tty.readline().strip().lower()
        tty.close()
        return choice
    except OSError as exc:
        logger.info("[SESSION_BOOT] /dev/tty not available: %s", exc)
        return ""


def _stop_session(session: dict, claude_bin: str) -> str:
    """Stop a session. Returns description of action taken.

    bg sessions: no per-job stop exists in the CLI. Returns an honest
    message — never SIGTERMs bg (daemon respawns it).
    """
    pid = session.get("pid")
    kind = session.get("kind", "unknown")

    if kind in ("bg", "background"):
        logger.info("[SESSION_BOOT] Cannot stop bg PID %s — no per-job stop in CLI", pid)
        return f"PID {pid}: bg session — no per-job stop available"

    tmux_session = _find_tmux_session_for_pid(pid) if pid else None
    if tmux_session and _tmux_kill_session(tmux_session):
        logger.info("[SESSION_BOOT] Killed tmux session '%s' (PID %d)", tmux_session, pid)
        return f"PID {pid}: killed tmux session '{tmux_session}'"

    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("[SESSION_BOOT] Sent SIGTERM to PID %d", pid)
            return f"PID {pid}: sent SIGTERM"
        except ProcessLookupError:
            logger.info("[SESSION_BOOT] PID %d already dead", pid)
            return f"PID {pid}: already dead"
        except OSError as exc:
            logger.warning("[SESSION_BOOT] SIGTERM PID %d failed: %s", pid, exc)
            return f"PID {pid}: SIGTERM failed ({exc})"
    return f"PID {pid}: no action"


def _resume_session(
    session: dict, branch: str, claude_bin: str, defaults: list[str], extra_args: list[str] | None = None
) -> dict:
    """Resume a session — right mechanism per kind."""
    pid = session.get("pid")
    kind = session.get("kind", "unknown")
    ea = list(extra_args or [])

    if kind in ("bg", "background"):
        return _takeover_bg(session, branch, claude_bin, defaults, extra_args)

    tmux_session = _find_tmux_session_for_pid(pid) if pid else None
    if tmux_session:
        logger.info("[SESSION_BOOT] Attaching to tmux session '%s'", tmux_session)
        os.execvp("tmux", ["tmux", "attach-session", "-t", tmux_session])
        return {"exit_code": 0, "action": "attached", "tmux_session": tmux_session}

    logger.info("[SESSION_BOOT] Continuing dead-window session via --continue")
    sid = session.get("sessionId", "")
    nf = _name_flag(branch, sid, extra_args)
    return _exec_in_tmux(branch, "", [claude_bin] + defaults + ["--continue"] + ea + nf)


def _make_session_name(branch: str, session_id: str = "") -> str:
    """Generate tmux session name: branch-shortid."""
    short_id = session_id[:8] if session_id else ""
    if short_id:
        return f"{branch}-{short_id}"
    return branch


def _name_flag(branch: str, session_id: str = "", extra_args: list[str] | None = None) -> list[str]:
    """Build --name args for session stamping, unless user already provided one."""
    if extra_args and ("-n" in extra_args or "--name" in extra_args):
        return []
    return ["--name", _make_session_name(branch, session_id)]


def _exec_in_tmux(branch: str, session_id: str, claude_cmd: list[str]) -> dict:
    """Exec a claude command inside a new tmux session."""
    session_name = _make_session_name(branch, session_id)
    if _tmux_session_exists(session_name):
        _tmux_kill_session(session_name)
    logger.info("[SESSION_BOOT] Launching in tmux '%s': %s", session_name, " ".join(claude_cmd))
    os.execvp("tmux", ["tmux", "new-session", "-s", session_name, "--"] + claude_cmd)
    return {"exit_code": 0, "action": "started", "tmux_session": session_name}


_MANIFEST_RELATIVE = Path(".claude") / "provider_manifest.json"


def _find_manifest() -> Path | None:
    """Walk up from this file to the repo root holding .claude/provider_manifest.json."""
    search = Path(__file__).resolve()
    for parent in search.parents:
        candidate = parent / _MANIFEST_RELATIVE
        if candidate.is_file():
            return candidate
    return None


def _pinned_cli_version() -> str:
    """The CLI version this repo is pinned to, or "" when nothing is pinned.

    The pin lives in the tracked provider_manifest.json so it ships with a clone and doctor reads it.
    """
    manifest = _find_manifest()
    if manifest is None:
        return ""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return str(data.get("cli", {}).get("claude", {}).get("pinned_version", ""))
    except (OSError, json.JSONDecodeError, AttributeError, TypeError) as exc:
        logger.info("[SESSION_BOOT] cannot read pinned version: %s", exc)
        return ""


def _running_cli_version(claude_bin: str) -> str:
    """Ask the binary what it is. Empty string when it cannot say."""
    try:
        result = subprocess.run(
            [claude_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("[SESSION_BOOT] cannot read running version: %s", exc)
        return ""
    return (result.stdout or "").strip().split(" ")[0]


def _warn_on_version_drift(claude_bin: str) -> str:
    """One loud line per boot when the running CLI is not the pinned one.

    CLI versions change the session lifecycle rules this file depends on, and drift is silent.
    """
    pinned = _pinned_cli_version()
    if not pinned:
        return ""
    running = _running_cli_version(claude_bin)
    if not running or running == pinned:
        return ""
    message = (
        f"  !! CLI VERSION DRIFT: running {running}, pinned {pinned}\n"
        f"     The session lifecycle rules differ between versions. Re-pin with:\n"
        f'     ln -sfn ~/.local/share/claude/versions/{pinned} "$(dirname "$(readlink -f "$(command -v claude)")")"\n'
    )
    logger.warning("[SESSION_BOOT] CLI version drift: running %s, pinned %s", running, pinned)
    sys.stderr.write(message)
    return running


def boot(cwd: str | None = None, extra_args: list[str] | None = None) -> dict:
    """Boot Claude Code — present menu when sessions exist."""
    cwd = cwd or str(Path.cwd().resolve())
    branch = Path(cwd).name
    claude_bin = _resolve_claude_binary()

    defaults = _DEFAULT_ARGS if not (extra_args and "--permission-mode" in extra_args) else []

    if extra_args and "-p" in extra_args:
        logger.info("[SESSION_BOOT] Headless mode (-p) — running claude directly, no tmux")
        claude_cmd = [claude_bin] + defaults
        claude_cmd.extend(extra_args)
        os.execvp(claude_bin, claude_cmd)
        return {"exit_code": 0, "action": "direct", "reason": "headless -p mode"}

    if os.environ.get("TMUX"):
        logger.info("[SESSION_BOOT] Already inside tmux — running claude directly")
        claude_cmd = [claude_bin] + defaults + _name_flag(branch, extra_args=extra_args)
        if extra_args:
            claude_cmd.extend(extra_args)
        os.execvp(claude_bin, claude_cmd)
        return {"exit_code": 0, "action": "direct", "reason": "already in tmux"}

    tmux = _find_tmux()
    if not tmux:
        logger.error("[SESSION_BOOT] tmux not found on PATH")
        return {"exit_code": 1, "error": "tmux not found — required for session hosting"}

    _warn_on_version_drift(claude_bin)

    # A live dispatch lock outranks both menus, else Enter walks into the job's session. After the
    # -p exit on purpose: the dispatch itself boots through -p and must not be gated by its own lock.
    lock = _dispatch_lock(cwd)
    if lock is not None:
        return _menu_dispatched(lock, branch, claude_bin, defaults, extra_args, cwd)

    live = _find_live_sessions(cwd)

    if live:
        return _menu_live(live, branch, claude_bin, defaults, extra_args, cwd)
    return _menu_no_live(branch, claude_bin, defaults, extra_args, cwd)


def _has_bg(sessions: list[dict]) -> bool:
    """Check if any session is a background session."""
    return any(s.get("kind") in ("bg", "background") for s in sessions)


def _get_collateral_bg(branch: str) -> list[dict]:
    """Find live bg sessions outside the given branch (blast-radius check)."""
    import importlib

    cc_sessions = importlib.import_module("aipass.hooks.apps.modules.cc_sessions")
    collateral = []
    for s in cc_sessions.read_all_sessions():
        if s.get("kind") not in ("bg", "background"):
            continue
        s_branch = Path(s.get("cwd", "")).name
        if s_branch != branch and s.get("pid") and cc_sessions._is_pid_alive(s["pid"]):
            collateral.append(s)
    return collateral


def _daemon_stop(claude_bin: str, branch: str, pid: int | None) -> dict:
    """Run daemon stop --any with blast-radius confirmation."""
    collateral = _get_collateral_bg(branch)
    if collateral:
        sys.stderr.write("  Other branches have live bg sessions that will also stop:\n")
        for s in collateral:
            coll_branch = Path(s.get("cwd", "")).name
            sys.stderr.write(f"    PID {s.get('pid')} · {coll_branch} · {_session_short_id(s)}\n")
        sys.stderr.write("  Continue? [y/N] ")
        confirm = _read_choice("")
        if confirm != "y":
            return {"ok": False, "error": "cancelled by user"}

    sys.stderr.write("  Stopping background sessions (daemon stop --any)...\n")
    try:
        result = subprocess.run(
            [claude_bin, "daemon", "stop", "--any"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            stderr_msg = result.stderr.strip()
            logger.warning("[SESSION_BOOT] daemon stop exit %d: %s", result.returncode, stderr_msg)
            sys.stderr.write(f"  daemon stop failed (exit {result.returncode}): {stderr_msg}\n")
            return {"ok": False, "error": f"daemon stop exit {result.returncode}: {stderr_msg}"}
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("[SESSION_BOOT] daemon stop failed: %s", exc)
        sys.stderr.write(f"  daemon stop failed: {exc}\n")
        return {"ok": False, "error": f"daemon stop failed: {exc}"}

    import time

    for _ in range(10):
        time.sleep(1)
        if not _is_session_file_present(pid):
            break
    else:
        logger.warning("[SESSION_BOOT] Session file for PID %s did not clear after daemon stop", pid)

    return {"ok": True}


def _takeover_bg(
    session: dict, branch: str, claude_bin: str, defaults: list[str], extra_args: list[str] | None = None
) -> dict:
    """Take over a bg session: daemon stop --any, poll, then --resume in tmux."""
    session_id = session.get("sessionId", "")
    pid = session.get("pid")
    ea = list(extra_args or [])
    nf = _name_flag(branch, session_id, extra_args)

    stop_result = _daemon_stop(claude_bin, branch, pid)
    if not stop_result["ok"]:
        return {"exit_code": 1, "error": stop_result["error"]}

    if session_id:
        logger.info("[SESSION_BOOT] Resuming session %s after takeover", session_id[:8])
        return _exec_in_tmux(branch, session_id, [claude_bin] + defaults + ["--resume", session_id] + ea + nf)

    logger.info("[SESSION_BOOT] No sessionId for takeover — continuing last")
    return _exec_in_tmux(branch, "", [claude_bin] + defaults + ["--continue"] + ea + nf)


def _is_session_file_present(pid: int | None) -> bool:
    """Check if a CC session file exists for the given PID.

    Via cc_sessions._claude_home(), live: Path.home() raises with no %USERPROFILE%, and redirects must move it.
    """
    if pid is None:
        return False
    import importlib

    cc_sessions = importlib.import_module("aipass.hooks.apps.modules.cc_sessions")
    session_file = cc_sessions._claude_home() / ".claude" / "sessions" / f"{pid}.json"
    return session_file.exists()


def _menu_single_session(
    session: dict,
    branch: str,
    claude_bin: str,
    defaults: list[str],
    extra_args: list[str] | None,
    cwd: str | None = None,
) -> dict:
    """Handle menu for a single live session."""
    label = _session_label(session)
    is_bg = session.get("kind") in ("bg", "background")
    sys.stderr.write(f"\n{branch} — live chat: {label}\n")
    if is_bg:
        sys.stderr.write("  [Enter]  resume this chat   (stops bg, reopens as normal chat)\n")
        sys.stderr.write("  [n]      start new chat   (stops bg first)\n")
        sys.stderr.write("  [c]      close it and exit   (stops bg)\n\n")
    else:
        sys.stderr.write("  [Enter]  resume this chat\n")
        sys.stderr.write("  [n]      start new chat   (closes the one above first)\n")
        sys.stderr.write("  [c]      close it and exit\n\n")

    choice = _read_choice()

    if choice in ("", "r"):
        return _resume_session(session, branch, claude_bin, defaults, extra_args)
    if choice == "n":
        return _menu_single_new(session, is_bg, branch, claude_bin, defaults, extra_args, cwd=cwd)
    if choice == "c":
        return _menu_single_close(session, is_bg, branch, claude_bin)
    if choice in ("exit", "q", "quit"):
        return {"exit_code": 0, "action": "quit"}
    sys.stderr.write("  Unknown choice. Exiting.\n")
    return {"exit_code": 1, "error": "unknown choice"}


def _menu_single_new(
    session: dict,
    is_bg: bool,
    branch: str,
    claude_bin: str,
    defaults: list[str],
    extra_args: list[str] | None,
    cwd: str | None = None,
) -> dict:
    """Handle 'n' choice for single session — stop current, start fresh."""
    if is_bg:
        stop = _daemon_stop(claude_bin, branch, session.get("pid"))
        if not stop["ok"]:
            return {"exit_code": 1, "error": stop["error"]}
    else:
        _stop_session(session, claude_bin)
    return _start_fresh(branch, claude_bin, defaults, extra_args, cwd=cwd)


def _menu_single_close(session: dict, is_bg: bool, branch: str, claude_bin: str) -> dict:
    """Handle 'c' choice for single session — close and exit."""
    if is_bg:
        stop = _daemon_stop(claude_bin, branch, session.get("pid"))
        if not stop["ok"]:
            return {"exit_code": 1, "error": stop["error"]}
        sys.stderr.write(f"  Stopped bg session PID {session.get('pid')}.\n")
    else:
        result = _stop_session(session, claude_bin)
        sys.stderr.write(f"  {result}\n")
    return {"exit_code": 0, "action": "closed"}


def _transcripts():
    """The CC transcript reader, imported on use.

    A top-level module import would make this handler unloadable wherever that module is absent.
    """
    import importlib

    return importlib.import_module("aipass.hooks.apps.modules.cc_transcripts")


def _session_pointer():
    """The dispatch session-pointer store, imported on use (same rule as above).

    The only record that reaches a dispatched session (-c refuses headless transcripts); never hand-edit it.
    """
    import importlib

    return importlib.import_module("aipass.ai_mail.apps.modules.door_session_pointer")


def _chat_age(modified: float) -> str:
    """Human age of a transcript's last write."""
    try:
        delta = time.time() - modified
    except (TypeError, ValueError) as exc:
        logger.info("[SESSION_BOOT] unreadable transcript timestamp %r: %s", modified, exc)
        return ""
    minutes = int(delta // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h{minutes % 60:02d}m ago"
    return f"{hours // 24}d ago"


def _chat_line(chat: dict) -> str:
    """One chat, described the way the user thinks of it."""
    title = chat.get("title") or "(untitled)"
    return f"{title} · {chat.get('messages', 0)} msgs · {_chat_age(chat.get('modified', 0))}"


def _live_by_session(live: list[dict]) -> dict[str, dict]:
    """Index live processes by the sessionId they hold."""
    return {str(s.get("sessionId", "")): s for s in live if s.get("sessionId")}


def _open_chat(
    chat: dict,
    live: list[dict],
    branch: str,
    claude_bin: str,
    defaults: list[str],
    extra_args: list[str] | None,
    cwd: str | None = None,
) -> dict:
    """Open a chosen chat — ATTACH when a brain already holds it, never spawn a second."""
    holder = _live_by_session(live).get(chat.get("session_id", ""))
    if holder is not None:
        logger.info(
            "[SESSION_BOOT] Chat %s is held by PID %s — attaching", chat.get("session_id", "")[:8], holder.get("pid")
        )
        return _resume_session(holder, branch, claude_bin, defaults, extra_args)

    session_id = chat.get("session_id", "")
    logger.info("[SESSION_BOOT] Resuming transcript %s (no live holder)", session_id[:8])
    # The opened chat is the seat now; the attach path records nothing, joining changes no seat.
    _session_pointer().write_pointer(Path(cwd or Path.cwd()), session_id, "session_boot")
    nf = _name_flag(branch, session_id, extra_args)
    cmd = [claude_bin] + defaults + ["--resume", session_id] + list(extra_args or []) + nf
    return _exec_in_tmux(branch, session_id, cmd)


def _describe_process(session: dict) -> str:
    """Name a live process for what it is — a seat or a leftover, never 'a chat'."""
    pid = session.get("pid")
    kind = session.get("kind", "unknown")
    short = _session_short_id(session)
    age = _format_age(session)
    parts = [f"PID {pid}", short, age]
    detail = " · ".join(p for p in parts if p)
    if kind in ("bg", "background"):
        return f"bg leftover  {detail}"
    tmux_session = _find_tmux_session_for_pid(pid) if pid else None
    where = f" (tmux {tmux_session})" if tmux_session else " (no tmux — orphaned window)"
    return f"seat         {detail}{where}"


def _menu_live(
    live: list[dict],
    branch: str,
    claude_bin: str,
    defaults: list[str],
    extra_args: list[str] | None,
    cwd: str | None = None,
) -> dict:
    """Display menu when live session(s) exist."""
    if len(live) == 1:
        return _menu_single_session(live[0], branch, claude_bin, defaults, extra_args, cwd=cwd)

    return _menu_multi(live, branch, claude_bin, defaults, extra_args, cwd)


def _menu_multi(
    live: list[dict],
    branch: str,
    claude_bin: str,
    defaults: list[str],
    extra_args: list[str] | None,
    cwd: str | None = None,
) -> dict:
    """Two or more live processes — offer the CHATS, and name the processes separately.

    A Ctrl+C'd chat has no session file, so a PID list cannot contain the chat the user wants.
    """
    branch_cwd = cwd or str(Path.cwd())
    transcripts = _transcripts().recent_chats(branch_cwd, limit=_CHAT_LIMIT)

    # A live seat may hold a chat older than the listed ones; list its door too.
    listed = {c.get("session_id") for c in transcripts}
    for session in live:
        sid = str(session.get("sessionId", ""))
        if sid and sid not in listed:
            held = _transcripts().chat_for(branch_cwd, sid)
            if held:
                transcripts.append(held)
                listed.add(sid)

    # Enter follows the session pointer, not newest-by-mtime; no trustworthy pointer → transcripts[0].
    default_chat = None
    ptr_sid, ptr_reason = _session_pointer().resolve_resume_target(Path(branch_cwd))
    if ptr_sid:
        default_chat = next((c for c in transcripts if c.get("session_id") == ptr_sid), None)
        if default_chat is None:
            pointed = _transcripts().chat_for(branch_cwd, ptr_sid)
            if pointed:
                transcripts.append(pointed)
                listed.add(ptr_sid)
                default_chat = pointed
    if default_chat is None:
        logger.info("[SESSION_BOOT] No pointer default for Enter: %s", ptr_reason)
        default_chat = transcripts[0] if transcripts else None

    sys.stderr.write(f"\n{branch} — recent chats:\n")
    if default_chat is not None:
        sys.stderr.write(f"  [Enter]  continue last chat  ({_chat_line(default_chat)})\n")
        for i, chat in enumerate(transcripts, 1):
            sys.stderr.write(f"  [{i}]      {_chat_line(chat)}\n")
    else:
        sys.stderr.write("  [Enter]  continue last chat\n")
        sys.stderr.write("  (no transcripts found for this branch)\n")

    sys.stderr.write(f"\n  {len(live)} live process(es) in this branch — not chats:\n")
    for session in live:
        sys.stderr.write(f"    {_describe_process(session)}\n")

    sys.stderr.write("\n  [n]  start new chat\n")
    sys.stderr.write("  [c]  close all live processes and exit\n\n")

    choice = _read_choice()

    if choice in ("", "r"):
        if default_chat is not None:
            return _open_chat(default_chat, live, branch, claude_bin, defaults, extra_args, cwd=branch_cwd)
        logger.info("[SESSION_BOOT] Continuing last chat via --continue (no transcripts listed)")
        nf = _name_flag(branch, extra_args=extra_args)
        cmd = [claude_bin] + defaults + ["--continue"] + list(extra_args or []) + nf
        return _exec_in_tmux(branch, "", cmd)

    if choice == "c":
        return _close_all(live, branch, claude_bin)

    if choice == "n":
        return _new_over_all(live, branch, claude_bin, defaults, extra_args, cwd=branch_cwd)

    if choice in ("exit", "q", "quit"):
        return {"exit_code": 0, "action": "quit"}

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(transcripts):
            return _open_chat(transcripts[idx], live, branch, claude_bin, defaults, extra_args, cwd=branch_cwd)
    except (ValueError, IndexError):
        logger.info("[SESSION_BOOT] Invalid menu choice: %r", choice)

    sys.stderr.write("  Pick a number, Enter, 'n', or 'c'. Exiting.\n")
    return {"exit_code": 1, "error": "unknown choice"}


def _close_all(live: list[dict], branch: str, claude_bin: str) -> dict:
    """Close all sessions — stop what's stoppable, honest about bg."""
    non_bg = [s for s in live if s.get("kind") not in ("bg", "background")]
    bg = [s for s in live if s.get("kind") in ("bg", "background")]
    for s in non_bg:
        result = _stop_session(s, claude_bin)
        sys.stderr.write(f"  {result}\n")
    if bg:
        stop = _daemon_stop(claude_bin, branch, bg[0].get("pid"))
        if stop["ok"]:
            sys.stderr.write(f"  Stopped {len(bg)} bg session(s) via daemon stop.\n")
        else:
            for s in bg:
                sys.stderr.write(f"  PID {s.get('pid')}: bg session remains — daemon stop failed\n")
    return {"exit_code": 0, "action": "closed_all"}


def _new_over_all(
    live: list[dict],
    branch: str,
    claude_bin: str,
    defaults: list[str],
    extra_args: list[str] | None,
    cwd: str | None = None,
) -> dict:
    """Start new chat, stopping what's stoppable first."""
    non_bg = [s for s in live if s.get("kind") not in ("bg", "background")]
    bg = [s for s in live if s.get("kind") in ("bg", "background")]
    for s in non_bg:
        result = _stop_session(s, claude_bin)
        sys.stderr.write(f"  {result}\n")
    if bg:
        stop = _daemon_stop(claude_bin, branch, bg[0].get("pid"))
        if not stop["ok"]:
            sys.stderr.write("  Cannot start new — bg session(s) still running.\n")
            return {"exit_code": 1, "error": "daemon stop failed, aborting to preserve one-brain"}
    return _start_fresh(branch, claude_bin, defaults, extra_args, cwd=cwd)


def _menu_no_live(
    branch: str,
    claude_bin: str,
    defaults: list[str],
    extra_args: list[str] | None,
    cwd: str | None = None,
) -> dict:
    """Display menu when no live session exists."""
    branch_cwd = cwd or str(Path.cwd())
    sid, reason = _session_pointer().resolve_resume_target(Path(branch_cwd))

    sys.stderr.write(f"\n{branch} — no live chat\n")
    seat = f"  (seat {sid[:8]})" if sid else ""
    sys.stderr.write(f"  [Enter]  continue last chat{seat}\n")
    sys.stderr.write("  [n]      new chat\n\n")

    choice = _read_choice()

    if choice in ("", "r"):
        return _continue_by_pointer(branch, claude_bin, defaults, extra_args, branch_cwd)
    elif choice == "n":
        return _start_fresh(branch, claude_bin, defaults, extra_args, cwd=branch_cwd)
    elif choice in ("exit", "q", "quit"):
        return {"exit_code": 0, "action": "quit"}
    else:
        sys.stderr.write("  Unknown choice. Exiting.\n")
        return {"exit_code": 1, "error": "unknown choice"}


def _continue_by_pointer(
    branch: str,
    claude_bin: str,
    defaults: list[str],
    extra_args: list[str] | None,
    branch_cwd: str,
) -> dict:
    """Open the branch's recorded seat — `--resume <pointer>` when trustworthy,
    else `--continue`."""
    sid, reason = _session_pointer().resolve_resume_target(Path(branch_cwd))
    if sid:
        logger.info("[SESSION_BOOT] Continuing via session pointer: %s", reason)
        nf = _name_flag(branch, sid, extra_args)
        cmd = [claude_bin] + defaults + ["--resume", sid] + list(extra_args or []) + nf
        return _exec_in_tmux(branch, sid, cmd)
    logger.info("[SESSION_BOOT] Continuing last chat via --continue (%s)", reason)
    nf = _name_flag(branch, extra_args=extra_args)
    cmd = [claude_bin] + defaults + ["--continue"] + list(extra_args or []) + nf
    return _exec_in_tmux(branch, "", cmd)


def _dispatch_lock(cwd: str) -> dict | None:
    """The branch's live dispatch lock, or None. READ-ONLY — never unlinks.

    ai_mail's wake owns the lock lifecycle and its format {pid, timestamp, branch}.
    """
    import importlib

    lock_file = Path(cwd) / ".ai_mail.local" / ".dispatch.lock"
    if not lock_file.exists():
        return None
    try:
        data = json.loads(lock_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.info("[SESSION_BOOT] Unreadable dispatch lock %s: %s", lock_file, exc)
        return None
    pid = data.get("pid")
    if not pid:
        return None
    cc_sessions = importlib.import_module("aipass.hooks.apps.modules.cc_sessions")
    if not cc_sessions._is_pid_alive(pid):
        logger.info("[SESSION_BOOT] Dispatch lock PID %s dead — not gating (cleanup is ai_mail's)", pid)
        return None
    return data


def _menu_dispatched(
    lock: dict,
    branch: str,
    claude_bin: str,
    defaults: list[str],
    extra_args: list[str] | None,
    cwd: str | None = None,
) -> dict:
    """An agent is WORKING in this branch — resume steps aside (FPLAN-0449).

    A second claude on one session id takes its background-task state and the job dies; the presence gate cannot stop that.
    """
    branch_cwd = cwd or str(Path.cwd())
    age = ""
    ts = lock.get("timestamp", "")
    if ts:
        try:
            from datetime import datetime

            age = f" · {_chat_age(datetime.fromisoformat(ts).timestamp())}"
        except (ValueError, TypeError) as exc:
            logger.info("[SESSION_BOOT] Unparseable dispatch lock timestamp %r: %s", ts, exc)

    sys.stderr.write(f"\n{branch} — agent is WORKING here (dispatched · lock PID {lock.get('pid')}{age})\n")
    sys.stderr.write("  Resume is takeover, not spectate: a second claude on the same session\n")
    sys.stderr.write("  steals its background-task state and the job dies mid-run (DPLAN-0310).\n\n")
    sys.stderr.write("  [Enter]  leave it working and exit\n")
    sys.stderr.write(f"  [w]      spectate (read-only):  drone @prax monitor run {branch}\n")
    sys.stderr.write("  [r]      reclaim the seat — STOPS THE JOB, then resumes its chat\n")
    sys.stderr.write("  [n]      new chat  (separate session — steals nothing)\n\n")

    choice = _read_choice()

    if choice in ("", "q", "quit", "exit"):
        return {"exit_code": 0, "action": "left_working"}
    if choice == "w":
        os.execvp("drone", ["drone", "@prax", "monitor", "run", branch])
        return {"exit_code": 0, "action": "spectate"}
    if choice == "n":
        return _start_fresh(branch, claude_bin, defaults, extra_args, cwd=branch_cwd)
    if choice == "r":
        return _reclaim_dispatched(branch, claude_bin, defaults, extra_args, branch_cwd)
    sys.stderr.write("  Unknown choice. Exiting.\n")
    return {"exit_code": 1, "error": "unknown choice"}


def _reclaim_dispatched(
    branch: str,
    claude_bin: str,
    defaults: list[str],
    extra_args: list[str] | None,
    branch_cwd: str,
) -> dict:
    """Deliberate takeover: stop the job, wait for its lock, resume its chat."""
    import importlib

    cc_sessions = importlib.import_module("aipass.hooks.apps.modules.cc_sessions")
    for action in cc_sessions.reclaim(branch):
        sys.stderr.write(f"  {action}\n")

    lock_file = Path(branch_cwd) / ".ai_mail.local" / ".dispatch.lock"
    deadline = time.monotonic() + _RECLAIM_WAIT_S
    while lock_file.exists() and time.monotonic() < deadline:
        time.sleep(_RECLAIM_POLL_S)
    if lock_file.exists():
        sys.stderr.write("  Dispatch lock did not clear — the monitor may still be finishing. Try again shortly.\n")
        return {"exit_code": 1, "error": "dispatch lock did not clear after reclaim"}

    return _continue_by_pointer(branch, claude_bin, defaults, extra_args, branch_cwd)


def _start_fresh(
    branch: str,
    claude_bin: str,
    defaults: list[str],
    extra_args: list[str] | None,
    cwd: str | None = None,
) -> dict:
    """Start a fresh Claude session in a new tmux session.

    The id is minted and the pointer written BEFORE claude starts; a never-born session fails transcript-exists later.
    """
    session_name = _make_session_name(branch)

    if _tmux_session_exists(session_name):
        logger.info("[SESSION_BOOT] Killing stale tmux session '%s'", session_name)
        _tmux_kill_session(session_name)

    sp = _session_pointer()
    session_id = sp.mint_session_id()
    branch_cwd = cwd or str(Path.cwd())
    sp.write_pointer(Path(branch_cwd), session_id, "session_boot")

    claude_cmd = [claude_bin] + defaults + ["--session-id", session_id] + _name_flag(branch, session_id, extra_args)
    if extra_args:
        claude_cmd.extend(extra_args)

    logger.info("[SESSION_BOOT] Starting fresh in tmux session '%s': %s", session_name, " ".join(claude_cmd))
    os.execvp("tmux", ["tmux", "new-session", "-s", session_name, "--"] + claude_cmd)
    return {"exit_code": 0, "action": "started", "tmux_session": session_name}


def main() -> None:
    """CLI entry point for the boot wrapper."""
    result = boot(extra_args=sys.argv[1:] if len(sys.argv) > 1 else None)
    if result.get("exit_code", 0) != 0:
        sys.stderr.write(f"{result.get('error', 'boot failed')}\n")
        sys.exit(result["exit_code"])


if __name__ == "__main__":
    main()
