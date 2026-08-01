# =================== AIPass ====================
# Name: branch_loader.py
# Version: 1.0.0
# Description: Loads branch-specific prompt + private integrations (UserPromptSubmit)
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-05-22
# Modified: 2026-05-22
# =============================================

"""Loads .aipass/aipass_local_prompt.md and private integration prompts for injection."""

from aipass.prax.apps.modules.logger import system_logger as logger


def load_content(hook_data: dict) -> str:
    """Read branch prompt + private integration prompts, unconditionally (no cadence gate)."""
    import importlib

    grounding_content = importlib.import_module("aipass.hooks.apps.modules.grounding_content")
    return grounding_content.load_branch(hook_data)


def handle(hook_data: dict) -> dict:
    """Load branch prompt and private integration prompts."""
    try:
        import importlib

        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        if not cadence.should_fire("branch", hook_data):
            return {"stdout": "", "exit_code": 0}
    except Exception as exc:
        logger.info("[HOOKS] branch_loader: cadence check failed, firing anyway: %s", exc)

    try:
        content = load_content(hook_data)
        if not content:
            return {"stdout": "", "exit_code": 0}
        return {"stdout": content, "exit_code": 0, "sound": "branch prompt"}

    except Exception as exc:
        logger.info("[HOOKS] branch_loader: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}
