# =================== AIPass ====================
# Name: release_notice.py
# Version: 1.0.2
# Description: Tells a project manager a newer AIPass is installed (SessionStart, DPLAN-0335)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-09-09
# Modified: 2026-11-16
# =============================================

"""SessionStart door for the manager-only AIPass release notice.

Skips resume (its context already carries the block) and compact (post_compact_regrounding covers it).
"""

import importlib

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

    content = load_content(hook_data)
    if not content:
        return {"stdout": "", "exit_code": 0}
    return {"stdout": content, "exit_code": 0, "sound": "release notice"}
