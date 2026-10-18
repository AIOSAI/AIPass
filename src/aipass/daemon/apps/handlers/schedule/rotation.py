# =================== AIPass ====================
# Name: rotation.py
# Description: Rounds roster, pointer state and prompt rendering
# Version: 1.3.0
# Created: 2026-08-12
# Modified: 2026-10-17
# =============================================

"""
Rounds — who gets tonight's maintenance turn (DPLAN-0287 piece 1; switched on as
`rounds` by DPLAN-0337 R2).

Reference: docs/rounds.md
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.schedule.discovery import (
    MANAGER_CLASS,
    active_citizens,
    citizen_class_for,
    framework_root,
)

# Kept apart from the per-job "jobs" map so orphan pruning never touches rotation state.
ROTATION_STATE_KEY = "rotation"

HISTORY_LIMIT = 10

# Never stewarded, knob or no knob: devpulse is on ai_mail's wake blocklist and is the human's own seat.
ALWAYS_EXCLUDED = frozenset({"@devpulse"})

DEFAULT_INCLUDE_MANAGERS = False

# Decided on the branch PATH, never on discovery's _source_label, which is presentation-only.
ROSTER_SCOPE = "framework fleet only — projects and externals excluded by ruling"

OUTCOME_WOKEN = "woken"
OUTCOME_MISSED = "missed"
OUTCOME_FAILED = "failed"
OUTCOME_SKIPPED = "skipped"

ROUNDS_PROMPT_TEMPLATE = (
    "ROUNDS for {branch}. The daemon woke you for your maintenance turn, once every roster cycle. "
    "Fresh start, nothing to resume. "
    "Do, inside your own branch only: inbox to zero (answer what you can, close what is done); "
    "reconcile your .trinity todos against reality (delete done, rescope stale); "
    "refresh and read your dashboard; review your logs for anomalies; run your seedgo self-audit; "
    "do the work that other citizens or devpulse have asked of you by mail IF it sits in your own "
    "domain and fits one session; small fixes in your own branch only, red-first, tests green. "
    "Budget, not negotiable: never dispatch or wake another citizen; at most 2 sub-agents, sonnet "
    "or lower; never edit another branch; no fleet-wide investigations; if you find something "
    "outside your lane or you need another branch, write it down for devpulse and stop, do not chase it. "
    "Report: mail @devpulse (drone @ai_mail email @devpulse) one message with four short parts: "
    "health verdict, what you did, what you noticed, what you need. "
    "Then update your .trinity memories and STOP."
)

BRANCH_PLACEHOLDER = "{branch}"


def in_framework_fleet(branch_path: Path, repo_root: Optional[Path] = None) -> bool:
    """The scope rule: does this branch live under this install's src/aipass/?"""
    return Path(branch_path).resolve().is_relative_to(framework_root(repo_root).resolve())


def roster_key(email: str) -> str:
    """The roster's sort key: build_roster orders by it and next_target walks by it."""
    return email.lower()


def build_roster(include_managers: bool = DEFAULT_INCLUDE_MANAGERS, repo_root: Optional[Path] = None) -> List[dict]:
    """Return the ordered list of citizens eligible for a steward night."""
    roster = []
    for citizen in active_citizens(repo_root):
        email = citizen["email"]
        if email.lower() in ALWAYS_EXCLUDED:
            logger.info("[rotation] %s excluded from roster (always)", email)
            continue

        if not in_framework_fleet(citizen["path"], repo_root):
            logger.info("[rotation] %s excluded from roster (%s: %s)", email, ROSTER_SCOPE, citizen.get("source", "?"))
            continue

        entry = dict(citizen)
        entry["citizen_class"] = citizen_class_for(citizen["path"])

        # An unreadable passport may be a manager's: it sits this night out, knob or no knob.
        if entry["citizen_class"] is None:
            logger.warning("[rotation] %s excluded from roster (passport unreadable)", email)
            continue

        if entry["citizen_class"] == MANAGER_CLASS and not include_managers:
            logger.info("[rotation] %s excluded from roster (manager, include_managers off)", email)
            continue

        roster.append(entry)

    roster.sort(key=lambda c: roster_key(c["email"]))
    logger.info("[rotation] Roster built: %d citizen(s), include_managers=%s", len(roster), include_managers)
    return roster


def next_target(roster: List[dict], last_target: Optional[str]) -> Optional[dict]:
    """Return the roster entry whose turn it is, or None for an empty roster."""
    if not roster:
        logger.warning("[rotation] Empty roster — no steward target available")
        return None

    if not last_target:
        return roster[0]

    emails = [c["email"] for c in roster]
    if last_target in emails:
        return roster[(emails.index(last_target) + 1) % len(roster)]

    missing = roster_key(last_target)
    following = next((c for c in roster if roster_key(c["email"]) > missing), roster[0])
    logger.info(
        "[rotation] Last target %s is no longer on the roster — continuing at %s", last_target, following["email"]
    )
    return following


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
    """Advance the pointer to `target` and append the turn to the history.

    The pointer is an email, not an index, so roster changes never re-serve the front; it advances on every turn.
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
    """Render the steward prompt for one branch.

    Never raises: no text falls back to the built-in, no placeholder passes through untouched.
    """
    text = (template or "").strip()
    if not text:
        logger.warning("[rotation] Rotation job has no prompt text — using built-in rounds template")
        text = ROUNDS_PROMPT_TEMPLATE

    if BRANCH_PLACEHOLDER not in text:
        logger.info("[rotation] Prompt has no %s placeholder — sending as-is to %s", BRANCH_PLACEHOLDER, branch)
        return text

    return text.replace(BRANCH_PLACEHOLDER, branch)
