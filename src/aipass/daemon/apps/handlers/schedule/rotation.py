# =================== AIPass ====================
# Name: rotation.py
# Description: Steward rotation roster, pointer state and prompt rendering
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-08-12
# =============================================

"""
Steward rotation — who gets tonight's maintenance turn (DPLAN-0287 piece 1).

Pure roster/pointer logic: builds the ordered roster of citizens eligible for a
steward night, decides whose turn is next, and records the outcome. No waking
happens here — the rotation module owns that, the same detection/policy split
the inbox sweep uses.

The pointer is stored as the LAST target's email rather than an index, so the
rotation survives citizens being added, retired, or filtered by the
include_managers knob without silently re-serving the front of the roster.
"""

from datetime import datetime
from typing import List, Optional

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.schedule.discovery import MANAGER_CLASS, active_citizens, citizen_class_for

# Top-level runstate key — rotation state is per rotation job, kept apart from
# the per-job "jobs" map so orphan pruning never touches it.
ROTATION_STATE_KEY = "rotation"

# How many past turns the status surface remembers.
HISTORY_LIMIT = 10

# Never stewarded, knob or no knob — devpulse is on ai_mail's wake blocklist and
# is the human's own collaborator seat.
ALWAYS_EXCLUDED = frozenset({"@devpulse"})

# Managers are dark until ai_mail ships the scheduled headless lane; the knob is
# the switch, the signature check is the safety catch.
DEFAULT_INCLUDE_MANAGERS = False

OUTCOME_WOKEN = "woken"
OUTCOME_MISSED = "missed"
OUTCOME_FAILED = "failed"
OUTCOME_SKIPPED = "skipped"

# Fallback used when a rotation job ships without prompt text. The live template
# lives in the job stanza so it can be reworded without a code change.
STEWARD_PROMPT_TEMPLATE = (
    "STEWARD NIGHT for {branch}. The daemon rotation woke you - tonight is your maintenance turn. "
    "Stay inside your own branch; mail owners about anything cross-branch; never edit other branches. "
    "1) Inbox to zero. "
    "2) Reconcile your .trinity todos against reality - delete done, rescope stale. "
    "3) Review your logs and dashboard for anomalies. "
    "4) Run your seedgo self-audit. "
    "5) Open or create your branch-audit APLAN via drone @flow create . with type aplan - "
    "update Quick Status, Issues Found, What Needs Doing. "
    "6) Small fixes in your own branch only, red-first, tests green. "
    "7) Reply to this dispatch with a steward report: health verdict, fixed, flagged, APLAN id. "
    "Then STOP."
)

BRANCH_PLACEHOLDER = "{branch}"


def build_roster(include_managers: bool = DEFAULT_INCLUDE_MANAGERS) -> List[dict]:
    """
    Return the ordered list of citizens eligible for a steward night.

    Order is registry order (framework citizens, then project citizens), which
    is the order the rotation walks. Each record carries citizen_class so the
    caller can route managers down the scheduled headless lane.
    """
    roster = []
    for citizen in active_citizens():
        email = citizen["email"]
        if email.lower() in ALWAYS_EXCLUDED:
            logger.info("[rotation] %s excluded from roster (always)", email)
            continue

        entry = dict(citizen)
        entry["citizen_class"] = citizen_class_for(citizen["path"])

        if entry["citizen_class"] == MANAGER_CLASS and not include_managers:
            logger.info("[rotation] %s excluded from roster (manager, include_managers off)", email)
            continue

        roster.append(entry)

    logger.info("[rotation] Roster built: %d citizen(s), include_managers=%s", len(roster), include_managers)
    return roster


def next_target(roster: List[dict], last_target: Optional[str]) -> Optional[dict]:
    """
    Return the roster entry whose turn it is, or None for an empty roster.

    Walks one step past `last_target`, wrapping at the end. An unknown or
    missing last_target starts the cycle at the top of the roster.
    """
    if not roster:
        logger.warning("[rotation] Empty roster — no steward target available")
        return None

    if not last_target:
        return roster[0]

    emails = [c["email"] for c in roster]
    if last_target not in emails:
        logger.info("[rotation] Last target %s is no longer on the roster — restarting cycle", last_target)
        return roster[0]

    return roster[(emails.index(last_target) + 1) % len(roster)]


def get_rotation_state(runstate: dict, key: str) -> dict:
    """Get rotation state for a rotation job. Returns empty dict if untracked."""
    return runstate.get(ROTATION_STATE_KEY, {}).get(key, {})


def record_rotation(
    runstate: dict,
    key: str,
    target: str,
    outcome: str,
    detail: str = "",
    timestamp: Optional[str] = None,
) -> None:
    """
    Advance the pointer to `target` and append the turn to the history.

    The pointer advances on every recorded turn, successful or not: a citizen
    that was busy tonight simply gets its next turn in the cycle (DPLAN-0287 —
    no retry logic, no starvation handling).
    """
    if timestamp is None:
        timestamp = datetime.now().isoformat()

    entry = runstate.setdefault(ROTATION_STATE_KEY, {}).setdefault(key, {})
    entry["last_target"] = target
    entry["last_run"] = timestamp

    history = entry.setdefault("history", [])
    history.insert(0, {"at": timestamp, "target": target, "outcome": outcome, "detail": detail[:300]})
    del history[HISTORY_LIMIT:]

    logger.info("[rotation] Recorded %s for %s (%s)", outcome, target, key)
    json_handler.log_operation("record_rotation", {"key": key, "target": target, "outcome": outcome})


def render_prompt(template: str, branch: str) -> str:
    """
    Render the steward prompt for one branch.

    Falls back to the built-in template when the job ships no prompt text, and
    passes a placeholder-free template through untouched (with a log line) so a
    reworded prompt never crashes the night's fire.
    """
    text = (template or "").strip()
    if not text:
        logger.warning("[rotation] Rotation job has no prompt text — using built-in steward template")
        text = STEWARD_PROMPT_TEMPLATE

    if BRANCH_PLACEHOLDER not in text:
        logger.info("[rotation] Prompt has no %s placeholder — sending as-is to %s", BRANCH_PLACEHOLDER, branch)
        return text

    return text.replace(BRANCH_PLACEHOLDER, branch)
