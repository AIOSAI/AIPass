#!/home/aipass/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: close.py - D-PLAN close handler
# Date: 2026-02-18
# Version: 1.0.0
# Category: devpulse/handlers/plan
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-02-18): Initial version - close/archive DPLAN files
#
# CODE STANDARDS:
#   - Handler independence: NO cross-domain imports
#   - NO Prax logging (per 3-tier: modules log, handlers don't)
#   - Pure business logic only
# ==============================================

"""
Close Handler - D-PLAN Close Operations

Validates, marks as closed, and archives DPLAN files.
Adapted from Flow's close system for single-user DPLANs.
"""

# INFRASTRUCTURE IMPORT PATTERN
import sys
import re
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List

AIPASS_ROOT = Path.home() / "aipass_core"
sys.path.insert(0, str(AIPASS_ROOT))
sys.path.insert(0, str(Path.home()))

# NOTE: Handlers do NOT import Prax logger (per 3-tier standard)

from .status import extract_status

# =============================================================================
# CONFIGURATION
# =============================================================================

DEV_PLANNING_ROOT = Path.home() / "aipass_os" / "dev_central" / "dev_planning"
PROCESSED_PLANS_DIR = Path.home() / "aipass_core" / "backup_system" / "processed_plans"


# =============================================================================
# PLAN RESOLUTION
# =============================================================================

def normalize_plan_number(plan_input: str) -> Tuple[int, str]:
    """
    Normalize plan number from various input formats.

    Accepts: "1", "001", "42", "DPLAN-001", "DPLAN-42"

    Args:
        plan_input: User-provided plan identifier

    Returns:
        Tuple of (plan_number_int, error_message)
        Error is empty string on success.
    """
    cleaned = plan_input.strip()

    # Strip DPLAN- prefix if present
    if cleaned.upper().startswith("DPLAN-"):
        cleaned = cleaned[6:]

    # Extract numeric portion
    try:
        num = int(cleaned)
        return (num, "")
    except ValueError:
        return (0, f"Invalid plan number: '{plan_input}'. Expected a number or DPLAN-XXX format.")


def find_plan_file(plan_num: int) -> Optional[Path]:
    """
    Find a DPLAN file by its number.

    Scans dev_planning/ root for matching DPLAN-XXX files.

    Args:
        plan_num: Plan number to find

    Returns:
        Path to plan file or None if not found
    """
    if not DEV_PLANNING_ROOT.exists():
        return None

    # Match DPLAN-XXX where XXX matches plan_num (any zero-padding)
    for plan_file in DEV_PLANNING_ROOT.glob("DPLAN-*.md"):
        match = re.match(r"DPLAN-(\d+)", plan_file.name)
        if match and int(match.group(1)) == plan_num:
            return plan_file

    return None


def get_open_plans() -> List[Dict[str, Any]]:
    """
    Get all plans that are not complete or abandoned.

    Returns:
        List of dicts with keys: number, file, topic, status
    """
    plans = []

    if not DEV_PLANNING_ROOT.exists():
        return plans

    for plan_file in DEV_PLANNING_ROOT.glob("DPLAN-*.md"):
        match = re.match(r"DPLAN-(\d+)_(.+)_(\d{4}-\d{2}-\d{2})\.md", plan_file.name)
        if match:
            num = int(match.group(1))
            topic = match.group(2).replace('_', ' ')
            status = extract_status(plan_file)

            if status not in ("complete", "abandoned"):
                plans.append({
                    "number": num,
                    "file": plan_file,
                    "topic": topic,
                    "status": status
                })

    plans.sort(key=lambda x: x["number"])
    return plans


# =============================================================================
# CLOSE OPERATIONS
# =============================================================================

def mark_as_closed(plan_file: Path) -> Tuple[bool, str]:
    """
    Update the status checkbox in the plan file to Complete.

    Changes:
      - [x] Planning/In Progress/Ready → unchecks
      - [ ] Complete → [x] Complete

    Args:
        plan_file: Path to the plan file

    Returns:
        Tuple of (success, error_message)
    """
    try:
        content = plan_file.read_text(encoding='utf-8')

        # Uncheck all currently checked statuses
        content = re.sub(r'- \[x\] (Planning)', r'- [ ] \1', content, flags=re.IGNORECASE)
        content = re.sub(r'- \[x\] (In Progress)', r'- [ ] \1', content, flags=re.IGNORECASE)
        content = re.sub(r'- \[x\] (Ready for Execution)', r'- [ ] \1', content, flags=re.IGNORECASE)

        # Check Complete
        content = re.sub(r'- \[ \] (Complete)', r'- [x] \1', content, flags=re.IGNORECASE)

        plan_file.write_text(content, encoding='utf-8')
        return (True, "")

    except Exception as e:
        return (False, f"Failed to update status checkbox: {e}")


def archive_plan(plan_file: Path) -> Tuple[bool, str]:
    """
    Move closed plan file to processed_plans/ directory.

    Verification: Returns True ONLY if file successfully moved AND verified.

    Args:
        plan_file: Path to the plan file

    Returns:
        Tuple of (success, error_message)
    """
    try:
        PROCESSED_PLANS_DIR.mkdir(parents=True, exist_ok=True)

        destination = PROCESSED_PLANS_DIR / plan_file.name

        # Handle duplicate names by appending timestamp
        if destination.exists():
            from datetime import datetime
            timestamp = datetime.now().strftime("%H%M%S")
            stem = destination.stem
            suffix = destination.suffix
            destination = PROCESSED_PLANS_DIR / f"{stem}_{timestamp}{suffix}"

        source_path = Path(plan_file)
        plan_file.rename(destination)

        # Verification
        if not destination.exists():
            return (False, "Move verification failed: destination not found")
        if source_path.exists():
            return (False, "Move verification failed: source still exists")

        return (True, "")

    except Exception as e:
        return (False, f"Failed to archive plan: {e}")


def close_plan(plan_num: int) -> Tuple[bool, Dict[str, Any], str]:
    """
    Close a single DPLAN: validate, mark status, return info for archival.

    Does NOT archive or process Memory Bank — that's done by post_close_runner.
    This function marks the plan as closed so the background runner can pick it up.

    Args:
        plan_num: Plan number to close

    Returns:
        Tuple of (success, result_data, error_message)
        result_data has keys: plan_file, plan_num, topic, old_status
    """
    # Find plan file
    plan_file = find_plan_file(plan_num)
    if plan_file is None:
        return (False, {}, f"DPLAN-{plan_num:03d} not found in {DEV_PLANNING_ROOT}")

    # Check current status
    current_status = extract_status(plan_file)
    if current_status == "complete":
        return (False, {}, f"DPLAN-{plan_num:03d} is already marked as complete")
    if current_status == "abandoned":
        return (False, {}, f"DPLAN-{plan_num:03d} is already abandoned")

    # Extract topic from filename
    match = re.match(r"DPLAN-\d+_(.+)_\d{4}-\d{2}-\d{2}\.md", plan_file.name)
    topic = match.group(1).replace('_', ' ') if match else plan_file.stem

    # Mark as closed (update checkbox)
    ok, err = mark_as_closed(plan_file)
    if not ok:
        return (False, {}, err)

    return (True, {
        "plan_file": plan_file,
        "plan_num": plan_num,
        "topic": topic,
        "old_status": current_status
    }, "")
