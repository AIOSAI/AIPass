# =================== AIPass ====================
# Name: codex_trust.py
# Version: 1.0.0
# Description: Codex's hook approvals: the trusted_hash it records per hooks.json row, and the rows it holds
# Branch: hooks
# Layer: apps/handlers/config
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""Codex runs a hooks.json row only while its approval in config.toml matches (codex-rs `hook_hash`, 0.164)."""

import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

tomllib = importlib.import_module("tomllib" if sys.version_info >= (3, 11) else "tomli")

#: What Codex hashes for a command handler with no timeout: its normalized handler carries 600.
DEFAULT_TIMEOUT_SEC = 600


def event_label(event: str) -> str:
    """Codex's key label for an event: PreToolUse -> pre_tool_use."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()


def hook_hash(event: str, group: dict, handler: dict) -> str:
    """Codex's trusted_hash: sha256 of sorted compact JSON {event_name, matcher, hooks: [handler]}, Nones dropped."""
    normalized = {
        "type": handler.get("type", "command"),
        "command": handler.get("command"),
        "async": bool(handler.get("async", False)),
        "timeout": handler.get("timeout", DEFAULT_TIMEOUT_SEC),
    }
    for key in ("commandWindows", "statusMessage", "additionalContextLimit"):
        if handler.get(key) is not None:
            normalized[key] = handler[key]
    identity = {"event_name": event_label(event), "hooks": [normalized]}
    if group.get("matcher") is not None:
        identity["matcher"] = group["matcher"]
    text = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def hook_state(config: Path) -> dict:
    """The [hooks.state] table of *config*; no file is {} (nothing approved), an unreadable one raises."""
    if not config.is_file():
        return {}
    return tomllib.loads(config.read_text(encoding="utf-8")).get("hooks", {}).get("state", {})
