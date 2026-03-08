#!/home/aipass/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: counter.py - Plan counter management
# Date: 2025-12-02
# Version: 2.0.0
# Category: devpulse/handlers/plan
#
# CHANGELOG (Max 5 entries):
#   - v2.0.0 (2026-02-19): Multi-type support (DPLAN/BPLAN), configurable root
#   - v1.0.0 (2025-12-02): Extracted from dev_flow.py module
#
# CODE STANDARDS:
#   - Handler independence: NO cross-domain imports
#   - NO Prax logging (per 3-tier: modules log, handlers don't)
#   - Pure business logic only
# ==============================================

"""
Counter Handler - Plan Numbering

Manages sequential plan numbers by scanning existing files.
Supports multiple plan types (DPLAN, BPLAN) with separate sequences.
Counter file is a cache, not source of truth.
"""

# INFRASTRUCTURE IMPORT PATTERN
import sys
import json
import re
from pathlib import Path
from typing import Tuple

AIPASS_ROOT = Path.home() / "aipass_core"
sys.path.insert(0, str(AIPASS_ROOT))
sys.path.insert(0, str(Path.home()))

# NOTE: Handlers do NOT import Prax logger (per 3-tier standard)
# Modules do the logging, handlers return errors

# =============================================================================
# CONFIGURATION
# =============================================================================

DEV_PLANNING_ROOT = Path.home() / "aipass_os" / "dev_central" / "dev_planning"
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
