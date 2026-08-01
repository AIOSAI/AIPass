# =================== AIPass ====================
# Name: navmap.py
# Version: 1.0.0
# Description: Tier 1 navigation map — periodic prompt injection (UserPromptSubmit)
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-06-18
# Modified: 2026-06-18
# =============================================

"""Loads .aipass/tier1_navmap.md — richer navigation map injected periodically."""

from aipass.prax.apps.modules.logger import system_logger as logger


def load_content(hook_data: dict) -> str:
    """Read tier1_navmap.md content, unconditionally (no cadence gate)."""
    import importlib

    grounding_content = importlib.import_module("aipass.hooks.apps.modules.grounding_content")
    return grounding_content.load_navmap(hook_data)


def handle(hook_data: dict) -> dict:
    """Load tier1 navmap — periodic (cadence period 5) + turn 0 + post-compaction."""
    try:
        import importlib

        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        if not cadence.should_fire("navmap", hook_data):
            return {"stdout": "", "exit_code": 0}
    except Exception as exc:
        logger.info("[HOOKS] navmap: cadence check failed, firing anyway: %s", exc)

    try:
        content = load_content(hook_data)
        if not content:
            return {"stdout": "", "exit_code": 0}
        return {"stdout": content, "exit_code": 0, "sound": "navmap"}

    except Exception as exc:
        logger.info("[HOOKS] navmap: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}
