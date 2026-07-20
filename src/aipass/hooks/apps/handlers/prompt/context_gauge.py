# =================== AIPass ====================
# Name: context_gauge.py
# Version: 1.0.0
# Description: Nudges the model to run /prep before auto-compact fires (UserPromptSubmit, DPLAN-0253)
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-07-20
# Modified: 2026-07-20
# =============================================

"""Early-warning nudge so the model runs /prep before the compact ceiling —
memory should never be at the mercy of an auto-compact firing mid-work.

Reads live transcript usage every prompt (cheap tail read), resolves the
branch's compact trigger (window * 0.9), and injects a hard line once fill
crosses 80%/95% of that trigger. Independent of the cadence system — its own
per-session, per-threshold guard file in tempdir, same idiom as
feedback_pulse.py / auto_process.py, so it isn't gated by turn count."""

import importlib
import os
import tempfile
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

_GUARD_DIR = Path(tempfile.gettempdir())
_TRIGGER_RATIO = 0.9
_NUDGE_THRESHOLD_PCT = 80
_ESCALATE_THRESHOLD_PCT = 95


def _guard_path(session_id: str, threshold: str) -> Path | None:
    if not session_id:
        return None
    return _GUARD_DIR / f"aipass-context-gauge-{session_id}-{threshold}"


def _already_fired(session_id: str, threshold: str) -> bool:
    path = _guard_path(session_id, threshold)
    return path is not None and path.exists()


def _mark_fired(session_id: str, threshold: str) -> None:
    path = _guard_path(session_id, threshold)
    if path is not None:
        try:
            path.touch()
        except OSError as exc:
            logger.info("[HOOKS] context_gauge: guard write failed: %s", exc)


def handle(hook_data: dict) -> dict:
    """Inject a context-fill nudge once per threshold per session."""
    try:
        session_id = hook_data.get("session_id", "") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
        transcript_path = hook_data.get("transcript_path", "")
        if not transcript_path:
            return {"stdout": "", "exit_code": 0}

        context_window = importlib.import_module("aipass.hooks.apps.modules.context_window")
        usage = context_window.read_latest_usage(transcript_path)
        if usage is None:
            return {"stdout": "", "exit_code": 0}

        fill = context_window.context_fill_tokens(usage)
        cwd = hook_data.get("cwd", "") or str(Path.cwd())
        window = context_window.resolve_compact_window(cwd)
        trigger = window * _TRIGGER_RATIO
        if trigger <= 0:
            return {"stdout": "", "exit_code": 0}

        pct = fill / trigger * 100
        fill_k = fill // 1000
        trigger_k = int(trigger) // 1000

        if pct >= _ESCALATE_THRESHOLD_PCT and not _already_fired(session_id, "95"):
            _mark_fired(session_id, "95")
            _mark_fired(session_id, "80")
            logger.info("[HOOKS] context_gauge: escalate fired at %.0f%% session=%s", pct, session_id[:8])
            return {
                "stdout": (
                    f"CONTEXT GAUGE: ~{fill_k}k/{trigger_k}k ({pct:.0f}%) — run /prep NOW "
                    "AND wrap up the current work item. Auto-compact is imminent."
                ),
                "exit_code": 0,
            }

        if pct >= _NUDGE_THRESHOLD_PCT and not _already_fired(session_id, "80"):
            _mark_fired(session_id, "80")
            logger.info("[HOOKS] context_gauge: nudge fired at %.0f%% session=%s", pct, session_id[:8])
            return {
                "stdout": (
                    f"CONTEXT GAUGE: ~{fill_k}k/{trigger_k}k ({pct:.0f}%) — run /prep NOW, "
                    "before auto-compact takes the choice away."
                ),
                "exit_code": 0,
            }

        return {"stdout": "", "exit_code": 0}

    except Exception as exc:
        logger.info("[HOOKS] context_gauge: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}
