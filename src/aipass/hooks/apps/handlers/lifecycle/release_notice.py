# =================== AIPass ====================
# Name: release_notice.py
# Version: 1.0.0
# Description: Tells a project manager a newer AIPass is installed (SessionStart, DPLAN-0335)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-09-09
# Modified: 2026-09-09
# =============================================

"""SessionStart door for the manager-only AIPass release notice.

Fires on source=startup (new chat) and source=clear (/clear) — a manager
waking is exactly when the news is actionable. Skips source=resume, whose
restored context already carries the block if it fired, and source=compact,
which is covered by post_compact_regrounding so the two never double up.

All the deciding lives in apps/modules/release_notice.py; this file is the
event wiring. Reads two files, writes none, and never runs the update.
"""

import importlib

from aipass.prax.apps.modules.logger import system_logger as logger

_SKIP_SOURCES = frozenset({"resume", "compact"})


def load_content(hook_data: dict) -> str:
    """Build the notice, unconditionally (no source gate)."""
    release_notice = importlib.import_module("aipass.hooks.apps.modules.release_notice")
    return release_notice.build_notice(hook_data)


def handle(hook_data: dict) -> dict:
    """Inject the release notice when this seat is a manager on a stale scaffold."""
    source = hook_data.get("source", "")
    if source in _SKIP_SOURCES:
        return {"stdout": "", "exit_code": 0}

    try:
        content = load_content(hook_data)
    except Exception as exc:
        logger.info("[HOOKS] release_notice: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}

    if not content:
        return {"stdout": "", "exit_code": 0}
    return {"stdout": content, "exit_code": 0, "sound": "release notice"}
