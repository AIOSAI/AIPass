# =================== AIPass ====================
# Name: session_start.py
# Version: 1.0.0
# Description: Resets cadence counter on new chat / clear (SessionStart)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-07-07
# Modified: 2026-07-07
# =============================================

"""Resets cadence counter on SessionStart so loaders re-fire at turn 0.

Fires on source=startup (new chat) and source=clear (/clear).
Skips source=resume — restored context already carries grounding.
source=compact is already handled by PreCompact; a duplicate reset is
harmless (idempotent), so we allow it rather than adding a fragile gate.
"""

import importlib

from aipass.prax.apps.modules.logger import system_logger as logger

_SKIP_SOURCES = frozenset({"resume"})


def handle(hook_data: dict) -> dict:
    """Reset cadence counter unless this is a resume."""
    source = hook_data.get("source", "")

    if source in _SKIP_SOURCES:
        logger.info("[HOOKS] session_start: skipped cadence reset (source=%s)", source)
        return {"stdout": "", "exit_code": 0}

    try:
        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        cadence.reset_counter(hook_data=hook_data)
        logger.info("[HOOKS] session_start: cadence reset (source=%s)", source)
    except Exception as exc:
        logger.info("[HOOKS] session_start: cadence reset failed: %s", exc)
        return {"stdout": "", "exit_code": 0}

    return {"stdout": "", "exit_code": 0, "sound": "cadence reset"}
