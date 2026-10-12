# =================== AIPass ====================
# Name: load_registry.py
# Description: Load Registry Handler
# Version: 1.4.0
# Created: 2025-11-07
# Modified: 2026-10-12
# =============================================

"""
Load Registry Handler

Loads the Flow PLAN registry from JSON file with error handling.

Features:
- Loads fplan_registry.json
- Returns default structure if file missing
- Raises RegistryUnreadableError if the file exists but is unreadable
- Reusable across Flow modules

Usage:
    from aipass.flow.apps.handlers.registry.load_registry import load_registry
    registry = load_registry()
"""

import json
from typing import Dict, Any

from aipass.flow.apps.handlers.json import json_handler

# INFRASTRUCTURE IMPORT PATTERN
from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "load_registry"
FLOW_JSON_DIR = FLOW_ROOT / "flow_json"
REGISTRY_FILE = FLOW_JSON_DIR / "fplan_registry.json"


class RegistryUnreadableError(Exception):
    """A plan registry exists on disk but cannot be read as a registry."""


# =============================================
# HANDLER FUNCTION
# =============================================


def load_registry(registry_file: str | None = None) -> Dict[str, Any]:
    """Load PLAN registry

    Args:
        registry_file: Optional filename (e.g. "fplan_registry.json",
            "dplan_registry.json"). When provided, loads from
            ``FLOW_JSON_DIR / registry_file`` instead of the default
            ``fplan_registry.json``.

    Returns:
        Dict containing:
        - plans: Dict of plan_number -> plan_info
        - next_number: Next available plan number

    Returns the default structure only when the file does not exist.

    Raises:
        RegistryUnreadableError: The file exists but cannot be read, is not
            JSON, or is not a JSON object. It answered the empty default
            until leg 6 of fleet green, and that answer is a namesake: create
            reissued 0001 over live plans and saved a one-row registry over
            the unreadable one; a bare-number close fell through to another
            type's registry and closed its plan (flow's decision, leg 6).
    """
    target = FLOW_JSON_DIR / registry_file if registry_file else REGISTRY_FILE

    if not target.exists():
        return {"plans": {}, "next_number": 1}

    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise RegistryUnreadableError(f"Plan registry {target} cannot be read: {e}") from e
    if not isinstance(data, dict):
        raise RegistryUnreadableError(f"Plan registry {target} is not a JSON object: {type(data).__name__}")
    json_handler.log_operation(
        "registry_loaded",
        {
            "target_file": target.name,
            "plan_count": len(data.get("plans", {})),
            "success": True,
        },
    )
    return data


def next_free_number(registry: Dict[str, Any]) -> int:
    """The next plan number no row already holds.

    ``next_number`` alone is not trusted: a self-heal registered a row at
    the stored number without moving it on (DPLAN row 0358 beside
    next_number 358, 2026-10-04), and the next create would have issued
    0358 a second time and written over that row (flow's decision, leg 7).
    The highest row is not the answer either: one stray row far above the
    rest (a test's FPLAN 9990, 2026-05-15) dragged every later number after
    it toward five digits (FPLAN-9994 after 0640, 2026-10-12). So the counter
    walks past held rows and nothing else.

    Returns:
        The first number at or above next_number (at least 1) that no
        numeric row holds.
    """
    held = {int(key) for key in registry.get("plans", {}) if str(key).isdigit()}
    number = max(int(registry.get("next_number", 1)), 1)
    while number in held:
        number += 1
    return number
