# =================== AIPass ====================
# Name: identity.py
# Version: 1.4.0
# Description: Injects branch identity from passport.json (UserPromptSubmit), cadence-gated
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-05-22
# Modified: 2026-11-17
# =============================================

"""Reads .trinity/passport.json and outputs formatted identity for prompt injection."""

from aipass.hooks.apps.handlers.json import json_handler


def load_content(hook_data: dict) -> str:
    """Read + format passport.json identity, unconditionally (no cadence gate)."""
    import importlib

    grounding_content = importlib.import_module("aipass.hooks.apps.modules.grounding_content")
    return grounding_content.load_identity(hook_data)


def handle(hook_data: dict) -> dict:
    """Inject branch identity, cadence-gated; each call leaves one json trail entry."""
    result = _handle(hook_data)
    seat = hook_data.get("cwd", "") if isinstance(hook_data, dict) else ""
    json_handler.log_operation("handle", {"exit_code": result.get("exit_code"), "seat": seat})
    return result


def _handle(hook_data: dict) -> dict:
    """Inject branch identity — cadence-gated (period from cadence_config.json, default 5)."""
    import importlib

    # A cadence that raises withholds this loader: the engine logs the ERROR, the kernel's banner names why.
    cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
    if not cadence.should_fire("identity", hook_data):
        return {"stdout": "", "exit_code": 0}

    content = load_content(hook_data)
    if not content:
        return {"stdout": "", "exit_code": 0}
    return {"stdout": content, "exit_code": 0, "sound": "identity"}
