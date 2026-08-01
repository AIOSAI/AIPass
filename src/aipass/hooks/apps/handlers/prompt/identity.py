# =================== AIPass ====================
# Name: identity.py
# Version: 1.0.0
# Description: Injects branch identity from passport.json (UserPromptSubmit)
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-05-22
# Modified: 2026-05-22
# =============================================

"""Reads .trinity/passport.json and outputs formatted identity for prompt injection."""

from aipass.prax.apps.modules.logger import system_logger as logger


def load_content(hook_data: dict) -> str:
    """Read + format passport.json identity, unconditionally (no cadence gate)."""
    import importlib

    grounding_content = importlib.import_module("aipass.hooks.apps.modules.grounding_content")
    return grounding_content.load_identity(hook_data)


def handle(hook_data: dict) -> dict:
    """Inject branch identity from passport.json into prompt context."""
    try:
        content = load_content(hook_data)
        if not content:
            return {"stdout": "", "exit_code": 0}
        return {"stdout": content, "exit_code": 0, "sound": "identity"}

    except Exception as exc:
        logger.info("[HOOKS] identity: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}
