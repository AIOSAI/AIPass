#!/home/aipass/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: list.py - Plan listing handler
# Date: 2025-12-02
# Version: 2.0.0
# Category: devpulse/handlers/plan
#
# CHANGELOG (Max 5 entries):
#   - v2.0.0 (2026-02-19): Multi-type listing (DPLAN/BPLAN), plan_type field
#   - v1.0.0 (2025-12-02): Extracted from dev_flow.py module
#
# CODE STANDARDS:
#   - Handler independence: NO cross-domain imports
#   - NO Prax logging (per 3-tier: modules log, handlers don't)
#   - Pure business logic only
# ==============================================

"""
List Handler - Plan Listing

Collects and returns plan data for display. Supports multiple plan types.
"""

# INFRASTRUCTURE IMPORT PATTERN
import sys
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple

AIPASS_ROOT = Path.home() / "aipass_core"
sys.path.insert(0, str(AIPASS_ROOT))
sys.path.insert(0, str(Path.home()))

# NOTE: Handlers do NOT import Prax logger (per 3-tier standard)

from .status import extract_status, extract_tag, extract_description

# =============================================================================
# CONFIGURATION
# =============================================================================

DEV_PLANNING_ROOT = Path.home() / "aipass_os" / "dev_central" / "dev_planning"

# Regex matches any plan type: DPLAN-001_topic_2026-02-19.md, BPLAN-001_topic_2026-02-19.md
PLAN_FILENAME_PATTERN = re.compile(r"([A-Z]+PLAN)-(\d+)_(.+)_(\d{4}-\d{2}-\d{2})\.md")


# =============================================================================
# HANDLER FUNCTIONS
# =============================================================================

def list_plans(filter_type: str | None = None) -> Tuple[List[Dict[str, Any]], str]:
    """
    List all plans with their metadata.

    Args:
        filter_type: Optional plan type filter (e.g. "dplan", "bplan").
                     None returns all types.

    Returns:
        Tuple of (plans_list, error_message)
        Each plan has: number, topic, date, status, tag, description, plan_type, prefix, file
    """
    plans = []

    if not DEV_PLANNING_ROOT.exists():
        return [], ""

    for plan_file in DEV_PLANNING_ROOT.glob("*PLAN-*.md"):
        match = PLAN_FILENAME_PATTERN.match(plan_file.name)
        if not match:
            continue

        prefix = match.group(1)
        num = int(match.group(2))
        topic = match.group(3).replace('_', ' ')
        date = match.group(4)
        plan_type = prefix.lower()

        # Apply type filter if specified
        if filter_type and plan_type != filter_type.lower():
            continue

        # Extract metadata from file content
        status = extract_status(plan_file)
        tag = extract_tag(plan_file)
        description = extract_description(plan_file)

        plans.append({
            "number": num,
            "topic": topic,
            "date": date,
            "status": status,
            "tag": tag,
            "description": description,
            "plan_type": plan_type,
            "prefix": prefix,
            "file": plan_file.name
        })

    # Sort by type then number
    plans.sort(key=lambda x: (x["plan_type"], x["number"]))

    return plans, ""
