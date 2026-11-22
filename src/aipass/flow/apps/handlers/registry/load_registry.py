# =================== AIPass ====================
# Name: load_registry.py
# Description: Load Registry Handler
# Version: 1.5.0
# Created: 2025-11-07
# Modified: 2026-11-21
# =============================================

"""Load Registry Handler"""

import json
from typing import Dict, Any
from pathlib import Path

from aipass.flow.apps.handlers.json import json_handler

_PKG_ROOT = Path(__file__).resolve().parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"

MODULE_NAME = "load_registry"
FLOW_JSON_DIR = FLOW_ROOT / "flow_json"
REGISTRY_FILE = FLOW_JSON_DIR / "fplan_registry.json"


class RegistryUnreadableError(Exception):
    """A plan registry exists on disk but cannot be read as a registry."""


def load_registry(registry_file: str | None = None) -> Dict[str, Any]:
    """Load a plan registry; empty only when absent, since an empty answer lets create overwrite live rows."""
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
    if not isinstance(data.get("plans"), dict):
        raise RegistryUnreadableError(f"Plan registry {target} has no 'plans' object")
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

    Not next_number alone (a self-heal can leave a row there) and not max row + 1
    (one stray high row would drag every later number up): walk past held rows only.
    """
    held = {int(key) for key in registry.get("plans", {}) if str(key).isdigit()}
    number = max(int(registry.get("next_number", 1)), 1)
    while number in held:
        number += 1
    return number
