# =================== AIPass ====================
# Name: release_notice.py
# Version: 1.1.0
# Description: Tells a project manager a newer AIPass is installed (SessionStart, DPLAN-0335)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-09-09
# Modified: 2026-11-17
# =============================================

"""SessionStart door for the manager-only AIPass release notice.

Skips resume (its context already carries the block) and compact (post_compact_regrounding covers it).
"""

import importlib

from aipass.hooks.apps.handlers.json import json_handler

_SKIP_SOURCES = frozenset({"resume", "compact"})


def load_content(hook_data: dict) -> str:
    """Build the notice, unconditionally (no source gate)."""
    release_notice = importlib.import_module("aipass.hooks.apps.modules.release_notice")
    return release_notice.build_notice(hook_data)


def handle(hook_data: dict) -> dict:
    """Inject the release notice to a stale manager; each call leaves one json trail entry."""
    result = _handle(hook_data)
    seat = hook_data.get("cwd", "") if isinstance(hook_data, dict) else ""
    json_handler.log_operation("handle", {"exit_code": result.get("exit_code"), "seat": seat})
    return result


def _handle(hook_data: dict) -> dict:
    """Inject the release notice when this seat is a manager on a stale scaffold."""
    source = hook_data.get("source", "")
    if source in _SKIP_SOURCES:
        return {"stdout": "", "exit_code": 0}

    content = load_content(hook_data)
    if not content:
        return {"stdout": "", "exit_code": 0}
    return {"stdout": content, "exit_code": 0, "sound": "release notice"}
