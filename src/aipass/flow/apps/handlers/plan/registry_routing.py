# =================== AIPass ====================
# Name: registry_routing.py
# Description: Plan-type Registry Routing Helpers
# Version: 1.0.0
# Created: 2026-07-28
# Modified: 2026-07-28
# =============================================

"""
Plan-Type Registry Routing

Shared helpers for resolving a raw plan number (which may carry a type
prefix, e.g. "PPLAN-0011") to the correct per-type registry file.

Extracted from close_helpers.py so restore (and any future number-keyed
op) shares the same type-aware routing instead of reimplementing it.
Any op that resolves a *specific* plan by number must use these -- a
bare `load_registry()` silently defaults to fplan_registry.json and
will resolve the wrong plan whenever two types share a number.

Usage:
    from aipass.flow.apps.handlers.plan.registry_routing import (
        _extract_prefix,
        _resolve_registry_file,
        _find_plan_across_registries,
    )
"""

import json
from pathlib import Path
from typing import Any, Dict

from aipass.prax import logger

from aipass.flow.apps.handlers.json import json_handler

MODULE_NAME = "registry_routing"

_PKG_ROOT = Path(__file__).resolve().parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"


def _extract_prefix(plan_num_raw: str) -> str | None:
    """Extract plan-type prefix (e.g. ``"DPLAN"``) from raw input."""
    import re

    m = re.match(r"^([A-Z]+PLAN)-", plan_num_raw.strip(), re.IGNORECASE)
    return m.group(1).upper() if m else None


def _resolve_registry_file(plan_num_raw: str) -> str | None:
    """Resolve registry_file from a raw plan number with prefix.

    Returns registry filename or None if no prefix detected.
    """
    prefix = _extract_prefix(plan_num_raw)
    reg_file = f"{prefix.lower()}_registry.json" if prefix else None
    json_handler.log_operation("registry_file_resolved", {"plan_num_raw": plan_num_raw, "registry_file": reg_file})
    return reg_file


def _load_template_registry() -> Dict[str, Any]:
    """Read template_registry.json directly (avoids cross-handler import)."""
    registry_path = FLOW_ROOT / "flow_json" / "template_registry.json"
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[{MODULE_NAME}] Failed to read template_registry.json: {e}")
        return {"types": {}}


def _find_plan_across_registries(plan_key: str, load_registry_fn: Any) -> str | None:
    """Search all registries for a plan number when no prefix given.

    Returns registry filename where the plan was found, or None.
    """
    try:
        template_reg = _load_template_registry()
        for _type_key, config in template_reg.get("types", {}).items():
            prefix = config.get("prefix", "")
            if not prefix:
                continue
            reg_file = f"{prefix.lower()}_registry.json"
            try:
                registry = load_registry_fn(registry_file=reg_file)
                if plan_key in registry.get("plans", {}):
                    return reg_file
            except Exception as e:
                logger.warning(f"[{MODULE_NAME}] Failed to search registry '{reg_file}' for plan '{plan_key}': {e}")
                continue
    except Exception as e:
        logger.warning(f"[{MODULE_NAME}] Failed to discover plan types while searching for plan '{plan_key}': {e}")
    return None
