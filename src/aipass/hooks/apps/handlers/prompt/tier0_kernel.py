# =================== AIPass ====================
# Name: tier0_kernel.py
# Version: 1.0.0
# Description: Tier 0 kernel — always-on minimal prompt injection (UserPromptSubmit)
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-06-18
# Modified: 2026-06-18
# =============================================

"""Loads .aipass/tier0_kernel.md — tiny always-on identity + reflex block."""

from aipass.prax.apps.modules.logger import system_logger as logger


def load_content(hook_data: dict) -> str:
    """Read tier0_kernel.md content, unconditionally (no cadence gate)."""
    import importlib

    grounding_content = importlib.import_module("aipass.hooks.apps.modules.grounding_content")
    return grounding_content.load_kernel(hook_data)


def handle(hook_data: dict) -> dict:
    """Load tier0 kernel — cadence-gated (period from cadence_config.json, default 5)."""
    try:
        import importlib

        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        if not cadence.should_fire("tier0", hook_data):
            return {"stdout": "", "exit_code": 0}
    except Exception as exc:
        logger.info("[HOOKS] tier0_kernel: cadence check failed, firing anyway: %s", exc)

    try:
        content = load_content(hook_data)
        if not content:
            return {"stdout": "", "exit_code": 0}
        return {"stdout": content, "exit_code": 0, "sound": "tier0 kernel"}

    except Exception as exc:
        logger.info("[HOOKS] tier0_kernel: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}
