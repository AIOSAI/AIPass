# =================== AIPass ====================
# Name: presence_gate.py
# Version: 3.3.1
# Description: Single-session gate — blocks duplicate Claude runtimes per branch
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-06-29
# Modified: 2026-10-17
# =============================================

"""Single-session gate — blocks duplicate Claude runtimes per branch.

Failure mode: OPEN, by decision — a broken presence gate would refuse every prompt in every
seat, the owner's included, and the prompt it refuses is the one that would fix it.
One brain means one INTERACTIVE brain: a bg occupant never gates, and of two seats the newer is refused.
"""

import importlib
import json
import os
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

_ALLOW = {"exit_code": 0, "stdout": ""}
_NON_BLOCKING_SESSION_TYPES = frozenset({"dispatched", "daemon"})

# True logs would-blocks and allows: the switch back from enforcement.
_OBSERVE_ONLY = False

_SUB_AGENT_TYPES = frozenset(
    {
        "general-purpose",
        "Explore",
        "Plan",
        "code-reviewer",
        "statusline-setup",
        "Task",
    }
)


def _resolve_branch(hook_data: dict) -> str:
    """Resolve the branch name from hook_data's cwd (session dir, not process cwd)."""
    cwd = hook_data.get("cwd", "") or str(Path.cwd())
    search = Path(cwd).resolve()
    while search.parent != search:
        if (search / ".trinity").is_dir() or (search / "apps").is_dir():
            return search.name
        if (search / "pyproject.toml").exists() or (search / ".git").is_dir():
            break
        search = search.parent
    return Path(cwd).name


def _format_session_age(session: dict) -> str:
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
        logger.info("[presence_gate] age format error: %s", exc)
        return ""


def _session_start(session: dict) -> float | None:
    """Epoch seconds this session began, or None when it cannot be told.

    An unreadable start means "cannot rank", never "younger".
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
        logger.info("[presence_gate] cannot read session start: %s", exc)
        return None


def _we_are_the_incumbent(ours: dict | None, occupant: dict) -> bool:
    """True when OUR session predates the occupant — so we are not the intruder.

    Without the tiebreak both seats refuse each other and brick the branch; an unknown start ranks nobody.
    """
    if not ours:
        return False
    our_start = _session_start(ours)
    their_start = _session_start(occupant)
    if our_start is None or their_start is None:
        return False
    return our_start < their_start


def _describe_arriver(session: dict | None, pid: int | None) -> str:
    """Name the session the gate is judging — the half the soak log was missing."""
    if not session:
        return f"PID {pid}" if pid else "unknown arriver"
    age = _format_session_age(session)
    parts = [
        f"PID {session.get('pid', pid)}",
        str(session.get("sessionId", ""))[:8],
        str(session.get("kind", "")),
        f"{age} old" if age else "",
    ]
    return " · ".join(p for p in parts if p)


def handle(hook_data: dict) -> dict:
    """UserPromptSubmit gate — enforce one live session per branch."""
    try:
        agent_type = hook_data.get("agent_type", "")
        if agent_type in _SUB_AGENT_TYPES:
            return _ALLOW

        session_type = os.environ.get("AIPASS_SESSION_TYPE", "interactive")
        if session_type in _NON_BLOCKING_SESSION_TYPES:
            return _ALLOW

        branch = _resolve_branch(hook_data)
        branch_cwd = hook_data.get("cwd", "") or str(Path.cwd())

        cc_sessions = importlib.import_module("aipass.hooks.apps.modules.cc_sessions")
        our_pid = cc_sessions.resolve_session_pid()
        occupant = cc_sessions.find_occupant(branch_cwd, exclude_pid=our_pid)

        if occupant is None:
            return _ALLOW

        # A bg session is a job, not a seat: there is no per-job bg stop, so a block would be unsatisfiable.
        # Known seam: find_occupant returns the FIRST non-self match, so a bg occupant can shadow an interactive one.
        if occupant.get("kind") in ("bg", "background"):
            logger.info(
                "[presence_gate] %s: occupant PID %s is bg — a job, not a seat (ruling a, DPLAN-0310)",
                branch,
                occupant.get("pid"),
            )
            return _ALLOW

        ours = next((s for s in cc_sessions.read_all_sessions() if s.get("pid") == our_pid), None)
        if _we_are_the_incumbent(ours, occupant):
            logger.info(
                "[presence_gate] %s: we are the incumbent (PID %s) — the newer seat PID %s is the one to refuse",
                branch,
                our_pid,
                occupant.get("pid"),
            )
            return _ALLOW

        occ_pid = occupant.get("pid", "?")
        occ_kind = occupant.get("kind", "unknown")
        occ_sid = str(occupant.get("sessionId", ""))[:8]
        age = _format_session_age(occupant)
        age_str = f" · {age} old" if age else ""

        remedy = f"  Attach to that session, or run: drone @hooks sessions reclaim @{branch}"

        arriver = _describe_arriver(ours, our_pid)
        reason = (
            f"{branch} is already live: PID {occ_pid} · {occ_sid} · {occ_kind}{age_str}\n"
            f"  You are the newer session ({arriver}).\n"
            f"{remedy}\n"
            f"  To disable this gate: set presence_gate.enabled=false in .aipass/hooks.json"
        )

        if _OBSERVE_ONLY:
            # INFO, no sound: observe-only is the gate declining to act, chosen behavior, not a fault.
            logger.info("[presence_gate] OBSERVE-ONLY would-block: %s | arriver: %s", reason, arriver)
            return _ALLOW

        logger.warning("[presence_gate] BLOCKED: %s", reason)
        return {
            "exit_code": 2,
            "stdout": json.dumps({"decision": "block", "reason": reason}),
            "sound": "presence gate",
        }
    except Exception as exc:
        logger.warning("[presence_gate] gate error (allowing): %s", exc)
        return _ALLOW


def handle_stop(hook_data: dict) -> dict:
    """No-op on Stop. CC-native session files handle cleanup on exit."""
    return _ALLOW
