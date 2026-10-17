# =================== AIPass ====================
# Name: engine.py
# Description: Surfacing governance engine — implementation
# Version: 1.1.0
# Created: 2026-07-16
# Modified: 2026-10-17
# =============================================

"""
Surfacing Governance Engine
"""

from typing import Any, Dict, Tuple

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler


DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "threshold": 0.3,
    "max_surfaces_per_session": 5,
    "min_messages_between": 10,
    "cooldown_seconds": 300,
}


def new_state() -> Dict[str, Any]:
    """Create a fresh governance state dict."""
    return {
        "surfaces_count": 0,
        "messages_since_last": 0,
        "last_surface_time": 0.0,
        "surfaced_ids": [],
    }


def should_surface(
    item_id: str,
    relevance_score: float,
    state: Dict[str, Any],
    config: Dict[str, Any] | None = None,
    *,
    current_time: float | None = None,
    record: bool = True,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Decide whether an item should be surfaced; never mutates *state*.

    record=False returns the same verdict without the governance_surface operation-log line.
    """
    import time

    cfg = {**DEFAULT_CONFIG, **(config or {})}
    now = current_time if current_time is not None else time.time()

    if not cfg.get("enabled", True):
        return False, "Surfacing disabled", state

    threshold = cfg.get("threshold", 0.3)
    if relevance_score < threshold:
        return False, f"Below threshold ({relevance_score:.2f} < {threshold})", state

    max_surfaces = cfg.get("max_surfaces_per_session", 5)
    if state.get("surfaces_count", 0) >= max_surfaces:
        return False, f"Session budget exhausted ({max_surfaces}/{max_surfaces})", state

    min_messages = cfg.get("min_messages_between", 10)
    messages_since = state.get("messages_since_last", 0)
    last_time = state.get("last_surface_time", 0.0)
    if last_time > 0 and messages_since < min_messages:
        return False, f"Spacing not met ({messages_since}/{min_messages} messages)", state

    cooldown = cfg.get("cooldown_seconds", 300)
    elapsed = now - last_time
    if last_time > 0 and elapsed < cooldown:
        remaining = int(cooldown - elapsed)
        return False, f"Cooldown active ({remaining}s remaining)", state

    surfaced_ids = state.get("surfaced_ids", [])
    if item_id in surfaced_ids:
        return False, "Already surfaced this session", state

    updated = {
        "surfaces_count": state.get("surfaces_count", 0) + 1,
        "messages_since_last": 0,
        "last_surface_time": now,
        "surfaced_ids": list(surfaced_ids) + [item_id],
    }
    logger.info(f"[governance] Surfacing {item_id} (score={relevance_score:.2f}, surfaces={updated['surfaces_count']})")
    if record:
        json_handler.log_operation(
            "governance_surface",
            {"item_id": item_id, "relevance_score": relevance_score, "surfaces_count": updated["surfaces_count"]},
        )
    return True, "Ready to surface", updated


def record_message(state: Dict[str, Any]) -> Dict[str, Any]:
    """Record that a message was processed. Pure — returns updated state."""
    return {
        **state,
        "messages_since_last": state.get("messages_since_last", 0) + 1,
    }
