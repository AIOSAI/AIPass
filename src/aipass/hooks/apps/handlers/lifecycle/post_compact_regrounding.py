# =================== AIPass ====================
# Name: post_compact_regrounding.py
# Version: 1.1.0
# Description: Mid-turn grounding backstop after compaction (PostToolUse, DPLAN-0276)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-07-31
# Modified: 2026-08-07
# =============================================

"""Re-grounds the agent after compaction even when no UserPromptSubmit arrives.

Cadence's reset_counter() (called from PreCompact) only takes effect on the
NEXT UserPromptSubmit — but that event does not fire during long autonomous
tool-call loops, only PostToolUse does. PreCompact/PostCompact stdout is never
shown to Claude (debug log only), so neither can inject grounding directly.
PostToolUse's hookSpecificOutput.additionalContext IS shown to Claude, and
fires on every tool call — this consumes the same post-compact signal there
instead of waiting for a UserPromptSubmit that may not come for a long time.
"""

import json

from aipass.prax.apps.modules.logger import system_logger as logger


def handle(hook_data: dict) -> dict:
    """Inject kernel+navmap+branch+identity content once, right after a compact."""
    try:
        import importlib

        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        if not cadence.consume_regroup_pending(hook_data):
            return {"stdout": "", "exit_code": 0}
    except Exception as exc:
        logger.info("[HOOKS] post_compact_regrounding: cadence check failed: %s", exc)
        return {"stdout": "", "exit_code": 0}

    try:
        grounding_content = importlib.import_module("aipass.hooks.apps.modules.grounding_content")

        loaders = (
            ("kernel", grounding_content.load_kernel),
            ("navmap", grounding_content.load_navmap),
            ("branch", grounding_content.load_branch),
            ("identity", grounding_content.load_identity),
        )
        sections = []
        for _label, loader in loaders:
            try:
                content = loader(hook_data)
            except Exception as exc:
                logger.info("[HOOKS] post_compact_regrounding: %s load failed: %s", _label, exc)
                content = ""
            if content:
                sections.append(content)

        if not sections:
            return {"stdout": "", "exit_code": 0}

        header = (
            "[POST-COMPACT RE-GROUND — mid-turn backstop, DPLAN-0276]\n"
            "Compaction happened without a following UserPromptSubmit, so cadence-based "
            "grounding didn't fire yet. Re-grounding now via PostToolUse.\n"
            "Reminder: .trinity sessions[]/key_learnings[] are NEWEST-FIRST — insert new "
            "entries at index 0 with number = max existing + 1, never append at the tail.\n"
            "\n" + grounding_content.STARTUP_REGROUND_INSTRUCTION
        )
        context = header + "\n" + "\n\n".join(sections)

        result = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": context,
            }
        }
        return {"stdout": json.dumps(result), "exit_code": 0, "sound": "post compact reground"}

    except Exception as exc:
        logger.info("[HOOKS] post_compact_regrounding: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}
