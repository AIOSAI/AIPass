# =================== AIPass ====================
# Name: session_start.py
# Version: 1.1.0
# Description: Resets cadence counter on new chat / clear; injects the culture file (SessionStart)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-07-07
# Modified: 2026-10-24
# =============================================

"""Resets cadence counter on SessionStart so loaders re-fire at turn 0.

Skips resume (context carries grounding) and compact (PreCompact reset already; twice re-arms the regroup token).
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
