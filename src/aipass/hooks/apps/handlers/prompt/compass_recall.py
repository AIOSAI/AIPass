# =================== AIPass ====================
# Name: compass_recall.py
# Version: 1.0.0
# Description: Ambient compass recall — surfaces rated decisions on relevant prompts
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-07-16
# Modified: 2026-07-16
# =============================================

"""Queries compass FTS against the user's prompt and injects matching decisions
under governance rules. Never blocks the prompt on error."""

import json
import os
import tempfile
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.hooks.apps.handlers.json import json_handler

_STATE_DIR = Path(tempfile.gettempdir())


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


def handle(hook_data: dict) -> dict:
    """Surface relevant compass decisions into the prompt context."""
    try:
        if not _state_path(hook_data):
            return {"stdout": "", "exit_code": 0}

        state = _load_state(hook_data)

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

        approved = []
        for c in candidates:
            item_id = str(c["id"])
            relevance = c.get("relevance", 0.0)
            surface, reason, new_st = should_surface(item_id, relevance, state)
            if surface:
                approved.append(c)
                state = new_st

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
