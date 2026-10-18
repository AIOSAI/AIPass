# =================== AIPass ====================
# Name: registry_routing.py
# Description: Plan-type Registry Routing Helpers
# Version: 1.2.0
# Created: 2026-07-28
# Modified: 2026-10-17
# =============================================

"""Plan-Type Registry Routing

Any op resolving a specific plan by number must route here: a bare load_registry() defaults to fplan.
"""

import json
from pathlib import Path
from typing import Any, Dict

from aipass.prax import logger

from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.repo_root import module_file

MODULE_NAME = "registry_routing"

_PKG_ROOT = module_file(__file__).parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"


def _extract_prefix(plan_num_raw: str) -> str | None:
    """Extract plan-type prefix (e.g. ``"DPLAN"``) from raw input."""
    import re

    m = re.match(r"^([A-Z]+PLAN)-", plan_num_raw.strip(), re.IGNORECASE)
    return m.group(1).upper() if m else None


def canonical_plan_id(plan_num: str, plan_info: Dict[str, Any]) -> str | None:
    """Build the typed plan ID (e.g. ``"DPLAN-0300"``) for a registry row.
    None when file_path (the only typed field) has no prefix: callers must refuse, never guess."""
    prefix = _extract_prefix(Path(plan_info.get("file_path", "") or "").stem)
    return f"{prefix}-{plan_num}" if prefix else None


def _resolve_registry_file(plan_num_raw: str) -> str | None:
    """Resolve registry_file from a raw plan number with prefix."""
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
    Re-raises a registry load failure: a skipped registry could hide the real plan behind a namesake."""
    template_reg = _load_template_registry()
    for _type_key, config in template_reg.get("types", {}).items():
        prefix = config.get("prefix", "")
        if not prefix:
            continue
        reg_file = f"{prefix.lower()}_registry.json"
        registry = load_registry_fn(registry_file=reg_file)
        if plan_key in registry.get("plans", {}):
            return reg_file
    return None
