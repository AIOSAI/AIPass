# =================== AIPass ====================
# Name: identity.py
# Version: 1.3.0
# Description: Injects branch identity from passport.json (UserPromptSubmit), cadence-gated
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-05-22
# Modified: 2026-09-16
# =============================================

"""Reads .trinity/passport.json and outputs formatted identity for prompt injection.

Cadence-gated like the kernel and navmap: fires on turn 0 and every Nth turn
(loader "identity" in cadence_config.json, default period 5, offset 0), so the
four grounding parts land together on one beat instead of identity every turn.
"""

from aipass.prax.apps.modules.logger import system_logger as logger


def load_content(hook_data: dict) -> str:
    """Read + format passport.json identity, unconditionally (no cadence gate)."""
    import importlib

    grounding_content = importlib.import_module("aipass.hooks.apps.modules.grounding_content")
    return grounding_content.load_identity(hook_data)


def handle(hook_data: dict) -> dict:
    """Inject branch identity — cadence-gated (period from cadence_config.json, default 5)."""
    try:
        import importlib

        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        if not cadence.should_fire("identity", hook_data):
            return {"stdout": "", "exit_code": 0}
    except Exception as exc:
        # The degraded fail mode (DPLAN-0347): a cadence that cannot answer withholds
        # this loader; the kernel fires alone and its banner names why.
        logger.warning(
            "[HOOKS] identity DEGRADED loader=identity: cadence check raised, so it is WITHHELD and the kernel "
            "fires alone until this is cured: %s",
            exc,
        )
        return {"stdout": "", "exit_code": 0}

    try:
        content = load_content(hook_data)
        if not content:
            return {"stdout": "", "exit_code": 0}
        return {"stdout": content, "exit_code": 0, "sound": "identity"}

    except Exception as exc:
        logger.info("[HOOKS] identity: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}
