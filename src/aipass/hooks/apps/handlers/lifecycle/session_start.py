# =================== AIPass ====================
# Name: session_start.py
# Version: 1.2.0
# Description: Resets cadence counter on new chat / clear; injects the culture file; writes the session pointer
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-07-07
# Modified: 2026-10-25
# =============================================

"""SessionStart: resets the cadence counter, injects the culture file, writes the session pointer.

The cadence reset re-fires loaders at turn 0. It skips resume (context carries grounding) and
compact (PreCompact reset already; twice re-arms the regroup token).
"""

import importlib
import os
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

_SKIP_SOURCES = frozenset({"resume", "compact"})


def handle(hook_data: dict) -> dict:
    """Reset cadence counter unless this is a resume."""
    source = hook_data.get("source", "")

    if source in _SKIP_SOURCES:
        logger.info("[HOOKS] session_start: skipped cadence reset (source=%s)", source)
        return {"stdout": "", "exit_code": 0}

    try:
        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        cadence.reset_counter(hook_data=hook_data, caller="session_start")
        logger.info("[HOOKS] session_start: cadence reset (source=%s)", source)
    except Exception as exc:
        logger.info("[HOOKS] session_start: cadence reset failed: %s", exc)
        return {"stdout": "", "exit_code": 0}

    return {"stdout": "", "exit_code": 0, "sound": "cadence reset"}


def handle_culture(hook_data: dict) -> dict:
    """Inject .claude/AGENTS.md, the culture file: Codex reads the root AGENTS.md natively, never this one."""
    home = os.environ.get("AIPASS_HOME", "")
    culture = Path(home) / ".claude" / "AGENTS.md" if home else None
    if culture is None or not culture.is_file():
        logger.warning("[HOOKS] session_start: no culture file at %s, none injected", culture or "(AIPASS_HOME unset)")
        return {"stdout": "", "exit_code": 0}
    return {"stdout": culture.read_text(encoding="utf-8"), "exit_code": 0}


def handle_session_pointer(hook_data: dict) -> dict:
    """Record this session as the branch's resume target, with the CLI running it, so a resume reopens that CLI.

    A compact keeps the session, so its pointer is already right. A bridge that names no provider is Claude's.
    """
    session_id = hook_data.get("session_id")
    if hook_data.get("source") == "compact" or not isinstance(session_id, str) or not session_id:
        return {"stdout": "", "exit_code": 0}
    branch = Path(hook_data.get("cwd") or os.getcwd())
    if not (branch / ".trinity" / "passport.json").is_file():
        return {"stdout": "", "exit_code": 0}
    provider = hook_data.get("provider") or "claude"
    try:
        door = importlib.import_module("aipass.ai_mail.apps.modules.door_session_pointer")
        written = door.write_pointer(branch, session_id, "session-start", provider=provider)
    except Exception as exc:  # a missed pointer costs a resume, never the session
        logger.info("[HOOKS] session_start: session pointer not written for %s: %s", branch, exc)
        return {"stdout": "", "exit_code": 0}
    logger.info("[HOOKS] session_start: pointer %s -> %s (%s) written=%s", branch, session_id, provider, written)
    return {"stdout": "", "exit_code": 0}
