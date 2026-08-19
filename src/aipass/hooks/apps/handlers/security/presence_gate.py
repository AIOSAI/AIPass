# =================== AIPass ====================
# Name: presence_gate.py
# Version: 3.2.0
# Description: Single-session gate — blocks duplicate Claude runtimes per branch
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-06-29
# Modified: 2026-08-18
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
dispatched/daemon session types.

ENFORCING since 2026-08-18 (Patrick: "flip it"). Ruling (a) rides with the
flip: one brain means one INTERACTIVE brain, so a background occupant never
gates — it is a job, not a seat, and there is no per-job bg stop in the CLI, so
blocking on one would be unsatisfiable. _OBSERVE_ONLY remains as the switch
back; when True the gate logs its would-blocks and allows.

Exactly one of two competing seats is refused: the incumbent (older start)
passes and the newer seat is told who holds the branch. Without that tiebreak
each seat sees the other and enforcement refuses BOTH, which bricks the branch
— the blocked prompt is the very thing that would run the remedy.

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

# Flipped 2026-08-18 on Patrick's ruling (DPLAN-0310, "flip it"): enforcement ON.
# Ruling (a) rides with it below — one brain means one INTERACTIVE brain.
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

    CC writes startedAt as epoch milliseconds; older files carry an ISO string.
    A session whose start cannot be read is not guessed at — the caller treats
    an unknown start as "cannot rank", never as "younger".
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

    Without this, two live seats on one branch each see the OTHER as occupant
    (verified: find_occupant returns the first non-self match, and nothing
    breaks the tie), so enforcement refuses BOTH and the branch is bricked with
    no in-band recovery — the blocked prompt is the very thing that would run
    the remedy. Ranking by start time makes the refusal land on exactly one
    side: the seat that arrived second. Unknown start ranks nobody, so an
    unreadable clock can never silently promote us to incumbent.
    """
    if not ours:
        return False
    our_start = _session_start(ours)
    their_start = _session_start(occupant)
    if our_start is None or their_start is None:
        return False
    return our_start < their_start


def _describe_arriver(session: dict | None, pid: int | None) -> str:
    """Name the session the gate is judging — the half the soak log was missing.

    496 would-blocks were recorded over five weeks and every line named only the
    occupant, so "was this a real second brain or our own tooling?" could not be
    answered from the evidence at all. A gate that observes must record BOTH
    sides or the soak cannot rule on itself.
    """
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

        # Ruling (a), DPLAN-0310 (Patrick, 2026-08-18): one brain = one INTERACTIVE
        # brain. A bg session is a job, not a seat — it never gates, because there is
        # no per-job bg stop in the CLI and an unsatisfiable block only teaches
        # routing around the gate. Known seam (owner to close): find_occupant returns
        # the FIRST non-self match, so a bg occupant here can shadow a second
        # interactive occupant behind it.
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

        # bg occupants were skipped above (ruling a) — every occupant that reaches
        # here is a stoppable, attachable seat, so the remedy is always satisfiable.
        remedy = f"  Attach to that session, or run: drone @hooks sessions reclaim @{branch}"

        arriver = _describe_arriver(ours, our_pid)
        reason = (
            f"{branch} is already live: PID {occ_pid} · {occ_sid} · {occ_kind}{age_str}\n"
            f"  You are the newer session ({arriver}).\n"
            f"{remedy}\n"
            f"  To disable this gate: set presence_gate.enabled=false in .aipass/hooks.json"
        )

        if _OBSERVE_ONLY:
            # INFO, and no sound: observe-only is the gate DECLINING to act, which is
            # chosen behavior, not something going wrong — the same call banked in
            # compass #277. Measured before reclassing: 26 would-blocks over 3.6h, all
            # naming ONE occupant PID, so the WARNING was 26 alarms for one situation.
            # INFO is retained on disk (verified in S155), so the evidence survives;
            # it just stops escalating. The sound was worse than the log line — audio
            # for a decision the gate is not making.
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
