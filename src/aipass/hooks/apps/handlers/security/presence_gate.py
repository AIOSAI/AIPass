# =================== AIPass ====================
# Name: presence_gate.py
# Version: 3.0.1
# Description: Single-session gate — blocks duplicate Claude runtimes per branch
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-06-29
# Modified: 2026-07-21
# =============================================

"""Single-session gate — blocks duplicate Claude runtimes per branch.

Sources truth from CC-native ~/.claude/sessions/<pid>.json (resume-aware,
exit-aware) instead of PRESENCE.central.json. Resume-aware because /resume
keeps the same PID; exit-aware because CC deletes the file on clean exit.

Fires on UserPromptSubmit: checks CC sessions for another live brain in the
same branch. If occupied by a different PID, blocks. If free, allows.

handle_stop is a no-op (Stop fires every turn, not just session end; CC-native
session files handle cleanup on exit).

Skips true sub-agents (Explore/general-purpose/Plan/etc.) and
dispatched/daemon session types. Gates main sessions of every kind
including background sessions with agent_type "claude".

Ships in OBSERVE-ONLY mode: logs would-block decisions to engine.jsonl
but never actually blocks. Flip _OBSERVE_ONLY to False after soak period
confirms zero false positives.

Occupant PID claims are identity-checked, not just liveness-checked:
cc_sessions.find_live_for_cwd() cross-verifies each session's recorded
procStart against the live process's actual start time before treating
a PID as a genuine occupant, so a PID recycled after the original
session died can never satisfy a stale claim.
"""

import importlib
import json
import os
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

_ALLOW = {"exit_code": 0, "stdout": ""}
_NON_BLOCKING_SESSION_TYPES = frozenset({"dispatched", "daemon"})

_OBSERVE_ONLY = True

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


def handle(hook_data: dict) -> dict:
    """UserPromptSubmit gate — enforce one live session per branch.

    Sources truth from CC-native ~/.claude/sessions/<pid>.json.
    Resume-aware: /resume keeps the same PID, so exclude_pid correctly
    identifies re-entry. Exit-aware: CC deletes the file on clean exit.
    """
    try:
        agent_type = hook_data.get("agent_type", "")
        if agent_type in _SUB_AGENT_TYPES:
            return _ALLOW

        session_type = os.environ.get("AIPASS_SESSION_TYPE", "interactive")
        if session_type in _NON_BLOCKING_SESSION_TYPES:
            return _ALLOW

        branch = _resolve_branch(hook_data)
        branch_cwd = hook_data.get("cwd", "") or str(Path.cwd())

        presence = importlib.import_module("aipass.hooks.apps.modules.presence")
        our_pid = presence._resolve_session_pid()

        cc_sessions = importlib.import_module("aipass.hooks.apps.modules.cc_sessions")
        occupant = cc_sessions.find_occupant(branch_cwd, exclude_pid=our_pid)

        if occupant is None:
            return _ALLOW

        occ_pid = occupant.get("pid", "?")
        occ_kind = occupant.get("kind", "unknown")
        occ_sid = str(occupant.get("sessionId", ""))[:8]
        age = _format_session_age(occupant)
        age_str = f" · {age} old" if age else ""

        reason = (
            f"{branch} is already live: PID {occ_pid} · {occ_sid} · {occ_kind}{age_str}\n"
            f"  Attach to that session, or run: drone @hooks sessions reclaim @{branch}\n"
            f"  To disable this gate: set presence_gate.enabled=false in .aipass/hooks.json"
        )

        if _OBSERVE_ONLY:
            logger.warning("[presence_gate] OBSERVE-ONLY would-block: %s", reason)
            return {**_ALLOW, "sound": "presence gate"}

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
