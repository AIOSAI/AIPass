#!/home/aipass/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: status.py - D-PLAN status handler
# Date: 2025-12-02
# Version: 1.1.0
# Category: devpulse/handlers/plan
#
# CHANGELOG (Max 5 entries):
#   - v1.1.0 (2026-02-18): Add VALID_TAGS, extract_tag(), extract_description() per FPLAN-0355
#   - v1.0.0 (2025-12-02): Extracted from dev_flow.py module
#
# CODE STANDARDS:
#   - Handler independence: NO cross-domain imports
#   - NO Prax logging (per 3-tier: modules log, handlers don't)
#   - Pure business logic only
# ==============================================

"""
Status Handler - D-PLAN Status Operations

Extracts status from plan files and provides status summary.
"""

# INFRASTRUCTURE IMPORT PATTERN
import sys
import re
from pathlib import Path
from typing import Dict, Tuple

AIPASS_ROOT = Path.home() / "aipass_core"
sys.path.insert(0, str(AIPASS_ROOT))
sys.path.insert(0, str(Path.home()))

# NOTE: Handlers do NOT import Prax logger (per 3-tier standard)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEV_PLANNING_ROOT = Path.home() / "aipass_os" / "dev_central" / "dev_planning"

VALID_TAGS = ["idea", "upgrade", "proposal", "bug", "research", "seed", "infrastructure"]

STATUS_ICONS = {
    "planning": "📋",
    "in_progress": "🔄",
    "ready": "✅",
    "complete": "✓",
    "abandoned": "❌",
    "unknown": "?"
}


# =============================================================================
# HANDLER FUNCTIONS
# =============================================================================

def extract_status(plan_file: Path) -> str:
    """
    Extract status from plan file by checking checkboxes

    Args:
        plan_file: Path to the plan file

    Returns:
        Status string: planning, in_progress, ready, complete, abandoned, unknown
    """
    try:
        content = plan_file.read_text(encoding='utf-8')

        # Look for checked status items (order matters - check most final states first)
        if re.search(r'- \[x\] Complete', content, re.IGNORECASE):
            return "complete"
        if re.search(r'- \[x\] Abandoned', content, re.IGNORECASE):
            return "abandoned"
        if re.search(r'- \[x\] Ready for Execution', content, re.IGNORECASE):
            return "ready"
        if re.search(r'- \[x\] In Progress', content, re.IGNORECASE):
            return "in_progress"
        if re.search(r'- \[x\] Planning', content, re.IGNORECASE):
            return "planning"

        return "planning"  # Default

    except Exception:
        return "unknown"


def get_status_icon(status: str) -> str:
    """
    Get emoji icon for status

    Args:
        status: Status string

    Returns:
        Emoji icon string
    """
    return STATUS_ICONS.get(status, "?")


def get_status_summary(filter_type: str | None = None) -> Tuple[Dict[str, int], int, str]:
    """
    Get summary of all plans by status, optionally filtered by type.

    Args:
        filter_type: Optional plan type filter (e.g. "dplan", "bplan").
                     None counts all types.

    Returns:
        Tuple of (status_counts, total, error_message)
        status_counts has keys: planning, in_progress, ready, complete, abandoned, unknown
    """
    status_counts = {
        "planning": 0,
        "in_progress": 0,
        "ready": 0,
        "complete": 0,
        "abandoned": 0,
        "unknown": 0
    }

    total = 0

    if not DEV_PLANNING_ROOT.exists():
        return status_counts, 0, ""

    for plan_file in DEV_PLANNING_ROOT.glob("*PLAN-*.md"):
        match = re.match(r"([A-Z]+PLAN)-\d+", plan_file.name)
        if not match:
            continue

        plan_type = match.group(1).lower()

        if filter_type and plan_type != filter_type.lower():
            continue

        total += 1
        status = extract_status(plan_file)

        if status in status_counts:
            status_counts[status] += 1
        else:
            status_counts["unknown"] += 1

    return status_counts, total, ""


def extract_tag(plan_file: Path) -> str:
    """
    Extract tag from plan file Tag: metadata line

    Args:
        plan_file: Path to the plan file

    Returns:
        Tag string (lowercase) or empty string if not found/invalid
    """
    try:
        content = plan_file.read_text(encoding='utf-8')
        match = re.search(r'^Tag:\s*(\S+)', content, re.MULTILINE)
        if match:
            tag = match.group(1).lower().strip()
            if tag in VALID_TAGS:
                return tag
        return ""
    except Exception:
        return ""


def extract_description(plan_file: Path) -> str:
    """
    Extract one-line description from plan file blockquote

    Args:
        plan_file: Path to the plan file

    Returns:
        Description string or empty if not found/placeholder
    """
    try:
        content = plan_file.read_text(encoding='utf-8')
        match = re.search(r'^>\s*(.+)$', content, re.MULTILINE)
        if match:
            desc = match.group(1).strip()
            if desc != "One-line description":
                return desc
        return ""
    except Exception:
        return ""
