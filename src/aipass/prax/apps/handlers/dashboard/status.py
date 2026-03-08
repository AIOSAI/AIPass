# =============================================================================
# EXTRACTED FROM Dev-Pass devpulse on 2026-03-08
# Original location: aipass_os/dev_central/devpulse/apps/handlers/dashboard/status.py
# These files need adaptation for AIPass before use
# Original imports use aipass_os.dev_central.devpulse — must be converted to aipass.prax
# =============================================================================

#!/home/aipass/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: status.py - Dashboard Status Calculation Handler
# Date: 2026-02-25
# Version: 0.2.0
# Category: handlers/dashboard
#
# CHANGELOG (Max 5 entries):
#   - v0.2.0 (2026-02-25): FPLAN-0373 - live section data, remove bulletin_board,
#       add commons mentions, updated action_required logic
#   - v0.1.0 (2025-11-24): Initial handler - status calculation and branch paths
#
# CODE STANDARDS:
#   - Pure business logic - no CLI imports
#   - Raises exceptions, caller handles logging
#   - Type hints on all functions
# =============================================

"""
Dashboard Status Handler

Handles status calculations and branch path resolution.
All business logic for dashboard status operations.
"""

import json
from pathlib import Path
from typing import Dict, List

AIPASS_ROOT = Path.home()
BRANCH_REGISTRY = AIPASS_ROOT / "BRANCH_REGISTRY.json"


def calculate_quick_status(sections: Dict) -> Dict:
    """
    Calculate quick status from live section data.

    Reads directly from section fields pushed by each service.
    bulletin_board is dropped (FPLAN-0373); commons mentions added.

    Args:
        sections: All dashboard sections

    Returns:
        Quick status dict with summary data
    """
    ai_mail = sections.get("ai_mail", {})
    flow = sections.get("flow", {})
    commons = sections.get("commons_activity", {})

    # v2 schema: read "new" first, fall back to "unread" for backward compat
    new_mail = ai_mail.get("new", ai_mail.get("unread", 0))
    opened_mail = ai_mail.get("opened", 0)
    active_plans = flow.get("active_plans", 0)
    mentions = commons.get("mentions", 0)

    # Action required if new mail, active plans, or commons mentions
    action_required = new_mail > 0 or active_plans > 0 or mentions > 0

    summary_parts = []
    if new_mail:
        summary_parts.append(f"{new_mail} new emails")
    if opened_mail:
        summary_parts.append(f"{opened_mail} opened")
    if active_plans:
        summary_parts.append(f"{active_plans} active plans")
    if mentions:
        summary_parts.append(f"{mentions} mentions")

    return {
        "new_mail": new_mail,
        "opened_mail": opened_mail,
        "active_plans": active_plans,
        "commons_mentions": mentions,
        "action_required": action_required,
        "summary": ", ".join(summary_parts) if summary_parts else "All clear"
    }


def get_branch_paths() -> List[Path]:
    """
    Get all branch paths from registry

    Returns:
        List of branch paths

    Raises:
        FileNotFoundError: If branch registry doesn't exist
        json.JSONDecodeError: If registry is corrupted
    """
    if not BRANCH_REGISTRY.exists():
        raise FileNotFoundError(f"Branch registry not found: {BRANCH_REGISTRY}")

    data = json.loads(BRANCH_REGISTRY.read_text())
    return [Path(b.get("path", "")) for b in data.get("branches", [])]
