# =================== AIPass ====================
# Name: validator.py
# Description: Plan Validation Handler
# Version: 0.3.0
# Created: 2025-11-30
# Modified: 2025-11-30
# =============================================

"""
Plan Validation Handler

Validates and normalizes plan numbers and registry entries.
Plan-type-agnostic: handles FPLAN-, DPLAN-, and future prefixes.
"""

import re
from typing import Dict, Any, Tuple

from aipass.flow.apps.handlers.json import json_handler

# Matches any PREFIX- at the start (e.g. FPLAN-, DPLAN-, XPLAN-)
_PREFIX_RE = re.compile(r"^([A-Z]+PLAN)-", re.IGNORECASE)


def normalize_plan_number(plan_num: str) -> str:
    """
    Normalize plan number to 4-digit format

    Strips any known prefix (FPLAN-, DPLAN-, PLAN-, etc.).

    Args:
        plan_num: Plan number in any format

    Returns:
        Normalized 4-digit plan number (e.g., "0001")

    Raises:
        ValueError: If plan_num cannot be converted to integer

    Examples:
        >>> normalize_plan_number("1")
        "0001"
        >>> normalize_plan_number("FPLAN-0042")
        "0042"
        >>> normalize_plan_number("DPLAN-0004")
        "0004"
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
    """
    Validate that a plan exists in the registry

    Args:
        plan_key: Normalized plan number (e.g., "0001")
        registry: Registry dictionary with 'plans' section

    Returns:
        Tuple of (exists, error_message)
        - exists: True if plan found in registry
        - error_message: None if exists, error string if not found
    """
    if plan_key not in registry.get("plans", {}):
        return False, f"Plan {plan_key} not found in registry"
    return True, None
