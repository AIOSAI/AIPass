# =================== AIPass ====================
# Name: validator.py
# Description: Plan Validation Handler
# Version: 0.3.0
# Created: 2025-11-30
# Modified: 2026-10-17
# =============================================

"""Plan Validation Handler"""

import re
from typing import Dict, Any, Tuple

from aipass.flow.apps.handlers.json import json_handler

_PREFIX_RE = re.compile(r"^([A-Z]+PLAN)-", re.IGNORECASE)


def normalize_plan_number(plan_num: str) -> str:
    """Normalize plan number to 4-digit format

    Raises ValueError when what remains after the prefix is not an integer.
    """
    if isinstance(plan_num, str):
        upper = plan_num.upper().strip()
        m = _PREFIX_RE.match(upper)
        if m:
            plan_num = plan_num[m.end() :]
        elif upper.startswith("PLAN-"):
            plan_num = plan_num[5:]
        elif upper.startswith("PLAN"):
            plan_num = plan_num[4:]
    normalized = f"{int(plan_num):04d}"
    json_handler.log_operation("plan_number_normalized", {"input": plan_num, "output": normalized})
    return normalized


def validate_plan_exists(plan_key: str, registry: Dict[str, Any]) -> Tuple[bool, str | None]:
    """Validate that a plan exists in the registry"""
    if plan_key not in registry.get("plans", {}):
        return False, f"Plan {plan_key} not found in registry"
    return True, None
