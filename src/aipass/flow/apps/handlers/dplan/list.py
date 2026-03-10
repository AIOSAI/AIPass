# =================== AIPass ====================
# Name: list.py
# Description: Plan listing handler
# Version: 2.0.0
# Created: 2025-12-02
# Modified: 2025-12-02
# =============================================

"""
List Handler - Plan Listing

Collects and returns plan data for display. Supports multiple plan types.
"""

import re
from pathlib import Path
from typing import List, Dict, Any, Tuple

# NOTE: Handlers do NOT import Prax logger (per 3-tier standard)

from .status import extract_status, extract_tag, extract_description

# =============================================================================
# CONFIGURATION
# =============================================================================

# list.py → dplan/ → handlers/ → apps/ → flow/
FLOW_ROOT = Path(__file__).resolve().parents[3]
DEV_PLANNING_ROOT = FLOW_ROOT / "dev_planning"

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
