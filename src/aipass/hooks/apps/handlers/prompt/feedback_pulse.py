# =================== AIPass ====================
# Name: feedback_pulse.py
# Version: 1.0.0
# Description: Periodic feedback ask — one ignorable line every ~10 turns
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-07-18
# Modified: 2026-07-18
# =============================================

"""Periodic feedback pulse — surfaces a one-line feedback ask every ~10 turns.

Scoped to external user projects (not the AIPass host). Toggle via
drone @hooks feedback on/off. State persists across session restarts
as a .aipass/feedback_off sentinel file per project."""

import json
import os
import tempfile
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.hooks.apps.handlers.json import json_handler

_STATE_DIR = Path(tempfile.gettempdir())
_PERIOD = 10
_FEEDBACK_URL = "https://github.com/AIOSAI/AIPass/issues"
_FEEDBACK_LINE = f"How are we doing? Your feedback is hugely appreciated → {_FEEDBACK_URL}"


def _state_path(hook_data: dict) -> Path | None:
    session_id = hook_data.get("session_id", "")
    if not session_id:
        session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not session_id:
        return None
    return _STATE_DIR / f"aipass-feedback-pulse-{session_id}.json"


def _load_and_increment(path: Path) -> int:
    """Load turn counter, increment, and persist. Returns the new turn number."""
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            turn = data.get("turn", 0) + 1
        else:
            turn = 0
        path.write_text(json.dumps({"turn": turn}), encoding="utf-8")
        return turn
    except (json.JSONDecodeError, OSError) as exc:
        logger.info("[HOOKS] feedback_pulse: state access failed: %s", exc)
        return 0


def _find_aipass_dir(cwd: str | None = None) -> Path | None:
    """Walk up from CWD to find the nearest .aipass/ directory."""
    start = Path(cwd) if cwd else Path.cwd()
    for parent in [start, *start.parents]:
        candidate = parent / ".aipass"
        if candidate.is_dir():
            return candidate
        if parent == parent.parent:
            break
    return None


def _is_disabled(cwd: str | None = None) -> bool:
    """Check if feedback pulse is toggled off for this project."""
    aipass_dir = _find_aipass_dir(cwd)
    if aipass_dir is None:
        return True
    sentinel = aipass_dir / "feedback_off"
    return sentinel.exists()


def handle(hook_data: dict) -> dict:
    """Inject feedback pulse line on cadence (~every 10 turns, skipping early turns)."""
    try:
        path = _state_path(hook_data)
        if path is None:
            return {"stdout": "", "exit_code": 0}

        turn = _load_and_increment(path)

        if turn < _PERIOD or turn % _PERIOD != 0:
            return {"stdout": "", "exit_code": 0}

        cwd = hook_data.get("cwd", "")
        if _is_disabled(cwd or None):
            logger.info("[HOOKS] feedback_pulse: skipped (disabled via .aipass/feedback_off sentinel)")
            return {"stdout": "", "exit_code": 0}

        json_handler.log_operation("feedback_pulse", {"turn": turn})
        return {"stdout": _FEEDBACK_LINE, "exit_code": 0}

    except Exception as exc:
        logger.info("[HOOKS] feedback_pulse: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}
