# =================== AIPass ====================
# Name: context_gauge.py
# Version: 1.6.0
# Description: Heads-up to run /prep ($prep on Codex) before auto-compact, and the grounding receipt (UserPromptSubmit)
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-07-20
# Modified: 2026-10-28
# =============================================

"""Heads-up so the model banks memories via /prep before the compact ceiling.
The guard is keyed per context window, not per session: a session id outlives every compaction.
The window is the one Claude Code really runs for the transcript's model; the trigger is its
auto-compact point (window - 33k), and the printed percent is fill over window, as the status line shows."""

import importlib
import os
import tempfile
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

_GUARD_DIR = Path(tempfile.gettempdir())
_NUDGE_THRESHOLD_PCT = 80
_ESCALATE_THRESHOLD_PCT = 95


def _window_key(hook_data: dict) -> str:
    """A tag that changes at every compaction, or 'w0' before the first one."""
    try:
        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        opened_at = cadence.window_opened_at(hook_data)
    except Exception as exc:
        logger.warning("[HOOKS] context_gauge: window stamp unreadable, guarding per session: %s", exc)
        return "w0"
    return f"w{int(opened_at)}" if opened_at else "w0"


def _guard_path(session_id: str, window: str, threshold: str) -> Path | None:
    if not session_id:
        return None
    return _GUARD_DIR / f"aipass-context-gauge-{session_id}-{window}-{threshold}"


def _already_fired(session_id: str, window: str, threshold: str) -> bool:
    path = _guard_path(session_id, window, threshold)
    return path is not None and path.exists()


def _mark_fired(session_id: str, window: str, threshold: str) -> None:
    path = _guard_path(session_id, window, threshold)
    if path is not None:
        try:
            path.touch()
        except OSError as exc:
            logger.info("[HOOKS] context_gauge: guard write failed: %s", exc)


def _reading(hook_data: dict, session_id: str) -> tuple[int, int, int] | None:
    """(fill, window, compact point) for this session, or None when there is nothing to read."""
    context_window = importlib.import_module("aipass.hooks.apps.modules.context_window")
    if hook_data.get("provider") == "opencode":
        fill = context_window.opencode_fill(session_id)
        if fill is None:
            return None
        return (fill, *context_window.opencode_window(session_id, hook_data.get("cwd", "") or str(Path.cwd())))
    transcript_path = hook_data.get("transcript_path", "")
    usage = context_window.read_latest_usage(transcript_path) if transcript_path else None
    if usage is None:
        return None
    cwd = hook_data.get("cwd", "") or str(Path.cwd())
    model = context_window.read_latest_model(transcript_path)
    window_size = context_window.resolve_compact_window(cwd, model, transcript_path)
    trigger = context_window.compact_threshold(window_size, context_window.transcript_provider(transcript_path))
    return (context_window.context_fill_tokens(usage), window_size, trigger) if trigger > 0 else None


def _receipt_line(hook_data: dict) -> str:
    """Write the grounding receipt (modules/grounding_receipt.py); its line when the last call lost grounding."""
    try:
        return importlib.import_module("aipass.hooks.apps.modules.grounding_receipt").observe(hook_data)
    except Exception as exc:
        logger.error("[HOOKS] context_gauge: grounding receipt not written: %s", exc)
        return ""


def handle(hook_data: dict) -> dict:
    """The context-fill nudge, then the grounding receipt's line when there is one."""
    result = _gauge(hook_data)
    line = _receipt_line(hook_data)
    if line:
        result = {**result, "stdout": "\n\n".join(part for part in (result["stdout"], line) if part)}
    return result


def _gauge(hook_data: dict) -> dict:
    """Inject a context-fill nudge once per threshold per session."""
    try:
        session_id = hook_data.get("session_id", "") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
        reading = _reading(hook_data, session_id)
        if reading is None:
            return {"stdout": "", "exit_code": 0}
        fill, window_size, trigger = reading

        pct = fill / trigger * 100
        used = round(fill / window_size * 100)
        head = (
            f"CONTEXT GAUGE: ~{fill // 1000}k of {window_size // 1000}k context "
            f"({used}%, as the status line counts it); auto-compact at ~{trigger // 1000}k."
        )

        window = _window_key(hook_data)
        prep = "$prep" if hook_data.get("provider") == "codex" else "/prep"

        if pct >= _ESCALATE_THRESHOLD_PCT and not _already_fired(session_id, window, "95"):
            _mark_fired(session_id, window, "95")
            _mark_fired(session_id, window, "80")
            logger.info(
                "[HOOKS] context_gauge: escalate fired at %.0f%% session=%s window=%s", pct, session_id[:8], window
            )
            return {
                "stdout": (
                    f"{head} Compact fires soon. "
                    f"Run {prep} now if anything is unbanked (just do it, no need to ask), "
                    "then carry on — recovery injection handles the rest."
                ),
                "exit_code": 0,
                "sound": "context gauge",
            }

        if pct >= _NUDGE_THRESHOLD_PCT and not _already_fired(session_id, window, "80"):
            _mark_fired(session_id, window, "80")
            logger.info(
                "[HOOKS] context_gauge: nudge fired at %.0f%% session=%s window=%s", pct, session_id[:8], window
            )
            return {
                "stdout": (
                    f"{head} Heads up, auto-compact "
                    f"is coming. Run {prep} at the next natural breakpoint (just do it, no need "
                    "to ask). Compact is survivable by design — keep working calmly."
                ),
                "exit_code": 0,
                "sound": "context gauge",
            }

        return {"stdout": "", "exit_code": 0}

    except Exception as exc:
        logger.info("[HOOKS] context_gauge: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}
