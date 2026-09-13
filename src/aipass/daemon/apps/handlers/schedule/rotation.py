# =================== AIPass ====================
# Name: rotation.py
# Description: Rounds roster, pointer state and prompt rendering
# Version: 1.2.0
# Created: 2026-08-12
# Modified: 2026-09-10
# =============================================

"""
Rounds — who gets tonight's maintenance turn (DPLAN-0287 piece 1; switched on as
`rounds` by DPLAN-0337 R2).

Pure roster/pointer logic: builds the ordered roster of citizens eligible for a
steward night, decides whose turn is next, and records the outcome. No waking
happens here — the rotation module owns that, the same detection/policy split
the inbox sweep uses.

The pointer is stored as the LAST target's email rather than an index, so the
rotation survives citizens being added, retired, or filtered by the
include_managers knob without silently re-serving the front of the roster.
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

# THE SCOPE RULE. Patrick, 2026-09-10 21:47 (DPLAN-0337 R2), marked very important:
# the rounds are AIPass maintaining its OWN agents. A citizen is served only when its
# branch lives under this install's src/aipass/. projects/* residents and every
# declared external root are out whatever their citizen_class — Vera keeps her own
# schedule, and the projects are nowhere near a trust stage. Decided on the PATH,
# never on the source label: discovery's _source_label is presentation-only.
ROSTER_SCOPE = "framework fleet only — projects and externals excluded by ruling"

OUTCOME_WOKEN = "woken"
OUTCOME_MISSED = "missed"
OUTCOME_FAILED = "failed"
OUTCOME_SKIPPED = "skipped"

# Fallback used when a rotation job ships without prompt text. The live template
# lives in the job stanza so it can be reworded without a code change.
# No "reply to this dispatch": a rounds wake is a session prompt, not a mail, so
# there is nothing to reply to - the @devpulse mail is the night's one artefact.
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


def build_roster(include_managers: bool = DEFAULT_INCLUDE_MANAGERS, repo_root: Optional[Path] = None) -> List[dict]:
    """
    Return the ordered list of citizens eligible for a steward night.

    Order is alphabetical by email, which is the order the rounds walk. Registry
    order was the walk until 2026-09-10; it made the next citizen depend on which
    registry a branch lives in, and nobody could predict a night from the roster
    alone. Each record carries citizen_class so the caller can route managers
    down the scheduled headless lane.

    ROSTER_SCOPE is applied before the passport is read, so no citizen_class can
    carry a projects/* or external citizen onto the roster.
    """
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

        if entry["citizen_class"] == MANAGER_CLASS and not include_managers:
            logger.info("[rotation] %s excluded from roster (manager, include_managers off)", email)
            continue

        roster.append(entry)

    roster.sort(key=lambda c: c["email"].lower())
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
        logger.warning("[rotation] Rotation job has no prompt text — using built-in rounds template")
        text = ROUNDS_PROMPT_TEMPLATE

    if BRANCH_PLACEHOLDER not in text:
        logger.info("[rotation] Prompt has no %s placeholder — sending as-is to %s", BRANCH_PLACEHOLDER, branch)
        return text

    return text.replace(BRANCH_PLACEHOLDER, branch)
