# =================== AIPass ====================
# Name: counter.py
# Description: Plan counter management
# Version: 2.0.0
# Created: 2025-12-02
# Modified: 2025-12-02
# =============================================

"""
Counter Handler - Plan Numbering

Manages sequential plan numbers by scanning existing files.
Supports multiple plan types (DPLAN, BPLAN) with separate sequences.
Counter file is a cache, not source of truth.
"""

import json
import re
from pathlib import Path
from typing import Tuple

# NOTE: Handlers do NOT import Prax logger (per 3-tier standard)

# =============================================================================
# CONFIGURATION
# =============================================================================

# counter.py → dplan/ → handlers/ → apps/ → flow/
FLOW_ROOT = Path(__file__).resolve().parents[3]
DEV_PLANNING_ROOT = FLOW_ROOT / "dev_planning"
COUNTER_FILE = DEV_PLANNING_ROOT / "counter.json"

VALID_PLAN_TYPES = {"dplan": "DPLAN", "bplan": "BPLAN"}


# =============================================================================
# HANDLER FUNCTIONS
# =============================================================================

def get_next_plan_number(
    plan_type: str = "DPLAN",
    planning_root: Path | None = None
) -> Tuple[int, str]:
    """
    Get next plan number for a given plan type.

    Strategy: Scan files for highest number with matching prefix, increment by 1.
    Counter file is cache, not source of truth.

    Args:
        plan_type: Plan prefix (DPLAN, BPLAN). Case-insensitive, normalized to upper.
        planning_root: Override directory to scan. Defaults to DEV_PLANNING_ROOT.

    Returns:
        Tuple of (next_number, error_message)
        Error message is empty on success
    """
    plan_type = plan_type.upper()
    root = planning_root or DEV_PLANNING_ROOT

    # Scan existing plans to find highest number for this type
    highest = 0

    if root.exists():
        for plan_file in root.glob(f"{plan_type}-*.md"):
            match = re.match(rf"{plan_type}-(\d+)", plan_file.name)
            if match:
                num = int(match.group(1))
                if num > highest:
                    highest = num

    next_num = highest + 1

    # Update counter cache (best effort, return error for logging by module)
    cache_error = ""
    try:
        counter_file = root / "counter.json"
        counter_file.parent.mkdir(parents=True, exist_ok=True)

        # Load existing counter data
        counter_data = {}
        if counter_file.exists():
            try:
                with open(counter_file, 'r', encoding='utf-8') as f:
                    counter_data = json.load(f)
            except Exception:
                counter_data = {}

        # Update per-type counter
        counter_data[plan_type] = {"next_number": next_num + 1}

        # Backwards compat: also set top-level next_number for DPLAN
        if plan_type == "DPLAN":
            counter_data["next_number"] = next_num + 1

        with open(counter_file, 'w', encoding='utf-8') as f:
            json.dump(counter_data, f, indent=2)
    except Exception as e:
        cache_error = f"Cache update failed: {e}"

    # Return number even if cache failed (cache is not critical)
    return next_num, cache_error
