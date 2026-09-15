# =================== AIPass ====================
# Name: compass_recall.py
# Version: 1.1.0
# Description: Ambient compass recall — surfaces rated decisions on relevant prompts
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-07-16
# Modified: 2026-09-14
# =============================================

"""Queries compass FTS against the user's prompt and injects matching decisions
under governance rules. Never blocks the prompt on error.

The governance knobs come from this handler's block in the project hooks.json,
and the surfacing budget is per context window: PreCompact stamps a new window
(compact.py -> cadence.reset_counter), the counts restart, the surfaced ids stay.
"""

import importlib
import json
import os
import tempfile
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.hooks.apps.handlers.config.loader import find_project_config
from aipass.hooks.apps.handlers.json import json_handler

_STATE_DIR = Path(tempfile.gettempdir())

# hooks.json knob -> memory governance config key. The rest of the block
# (enabled, handler, timeout) is the engine's, not governance's.
_GOVERNANCE_KNOBS = {
    "max_per_session": "max_surfaces_per_session",
    "threshold": "threshold",
    "min_messages_between": "min_messages_between",
    "cooldown_seconds": "cooldown_seconds",
}

# The refusals that silenced recall with nothing in any log (FPLAN-0588).
# Below-threshold and already-surfaced are recall working, not the budget.
_LOGGED_REFUSALS = ("Session budget exhausted", "Spacing not met", "Cooldown active")


def _state_path(hook_data: dict | None = None) -> Path | None:
    session_id = ""
    if hook_data:
        session_id = hook_data.get("session_id", "")
    if not session_id:
        session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not session_id:
        return None
    return _STATE_DIR / f"aipass-compass-recall-{session_id}.json"


def _load_state(hook_data: dict | None = None) -> dict:
    path = _state_path(hook_data)
    if path is None or not path.exists():
        return _fresh_state()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.info("[HOOKS] compass_recall: state read failed: %s", exc)
        return _fresh_state()


def _fresh_state() -> dict:
    try:
        from aipass.memory.apps.modules.governance import new_state

        return new_state()
    except Exception as exc:
        logger.info("[HOOKS] compass_recall: governance import failed: %s", exc)
        return {"surfaces_count": 0, "messages_since_last": 0, "last_surface_time": 0.0, "surfaced_ids": []}


def _save_state(state: dict, hook_data: dict | None = None) -> None:
    path = _state_path(hook_data)
    if path is None:
        return
    try:
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError as exc:
        logger.info("[HOOKS] compass_recall: state write failed: %s", exc)


def _governance_config() -> dict:
    """This handler's hooks.json knobs, renamed for memory's governance engine.

    The bridge hands the block to the engine's budget and never to the handler,
    so max_per_session reached the engine and governance's default of 5 decided.
    Missing, unknown or non-numeric knobs fall to governance's defaults.
    """
    block = ((find_project_config() or {}).get("UserPromptSubmit") or {}).get("compass_recall") or {}
    config = {}
    for knob, key in _GOVERNANCE_KNOBS.items():
        value = block.get(knob)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            config[key] = value
    return config


def _open_window(state: dict, hook_data: dict) -> dict:
    """Restart the counts when a new context window has opened; keep the surfaced ids.

    The state file is keyed by session id, which survives every compaction, so
    a budget spent by lunch held recall silent all day. last_surface_time goes
    with the counts: kept, it would hold the new window's first
    min_messages_between prompts silent on spacing.
    """
    cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
    window = cadence.window_opened_at(hook_data)
    if window is None or state.get("window") == window:
        return state
    if state.get("surfaces_count"):
        logger.info(
            "[HOOKS] compass_recall: new context window, budget reset (%d surfaced, %d ids kept)",
            state["surfaces_count"],
            len(state.get("surfaced_ids", [])),
        )
    return {**_fresh_state(), "surfaced_ids": list(state.get("surfaced_ids", [])), "window": window}


def handle(hook_data: dict) -> dict:
    """Surface relevant compass decisions into the prompt context."""
    try:
        if not _state_path(hook_data):
            return {"stdout": "", "exit_code": 0}

        state = _open_window(_load_state(hook_data), hook_data)

        from aipass.memory.apps.modules.governance import should_surface, record_message

        state = record_message(state)

        prompt_text = hook_data.get("prompt", "")
        if not prompt_text or len(prompt_text) < 10:
            _save_state(state, hook_data)
            return {"stdout": "", "exit_code": 0}

        from aipass.devpulse.apps.modules.compass import recall_decisions, mark_surfaced

        candidates = recall_decisions(prompt_text, limit=3)
        if not candidates:
            _save_state(state, hook_data)
            return {"stdout": "", "exit_code": 0}

        config = _governance_config()
        approved = []
        for c in candidates:
            item_id = str(c["id"])
            relevance = c.get("relevance", 0.0)
            surface, reason, new_st = should_surface(item_id, relevance, state, config)
            if surface:
                approved.append(c)
                # Governance answers its own four keys. Merged, the window stamp
                # rides along; replaced, the next prompt reads a new window.
                state = {**state, **new_st}
            elif reason.startswith(_LOGGED_REFUSALS):
                logger.info("[HOOKS] compass_recall: refused #%s: %s", item_id, reason)

        _save_state(state, hook_data)

        if not approved:
            return {"stdout": "", "exit_code": 0}

        lines = []
        for c in approved:
            rating = c.get("rating", "good").upper()
            lines.append(f"[{rating}] #{c['id']}: {c['decision']}")

        mark_surfaced([c["id"] for c in approved])
        json_handler.log_operation("compass_recall", {"count": len(approved)})

        return {"stdout": "\n".join(lines), "exit_code": 0, "sound": "compass recall"}

    except Exception as exc:
        logger.info("[HOOKS] compass_recall_unreachable: %s", exc)
        return {"stdout": "", "exit_code": 0}
