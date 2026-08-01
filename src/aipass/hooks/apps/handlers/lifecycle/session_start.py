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

Also skips source=compact: PreCompact (compact.py) already reset for the
same boundary. This was previously treated as a harmless duplicate, but it
is not — it re-arms the PostToolUse regroup token (DPLAN-0276) a second
time per compact, and was the confirmed over-fire mechanism in DPLAN-0278
(one session saw 16 regroup fires with no matching PreCompact reset logged
in between). cadence.reset_counter() also debounces same-boundary re-arms
as defense in depth, but the redundant call itself serves no purpose here.
"""

import importlib

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
