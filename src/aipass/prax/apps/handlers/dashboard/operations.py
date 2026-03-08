# =============================================================================
# EXTRACTED FROM Dev-Pass devpulse on 2026-03-08
# Original location: aipass_os/dev_central/devpulse/apps/handlers/dashboard/operations.py
# These files need adaptation for AIPass before use
# Original imports use aipass_os.dev_central.devpulse — must be converted to aipass.prax
# =============================================================================

#!/home/aipass/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: operations.py - Dashboard Operations Handler
# Date: 2026-02-25
# Version: 0.3.0
# Category: handlers/dashboard
#
# CHANGELOG (Max 5 entries):
#   - v0.3.0 (2026-02-25): FPLAN-0373 Phase 1 - write_section() API, remove bulletin_board,
#       add commons_activity, ISO timestamps, updated schema
#   - v0.2.0 (2026-02-03): Fix empty file handling - treat empty JSON as new dashboard
#   - v0.1.0 (2025-11-24): Initial handler - dashboard load/save/update operations
#
# CODE STANDARDS:
#   - Pure business logic - no CLI imports
#   - Raises exceptions, caller handles logging
#   - Type hints on all functions
# =============================================

"""
Dashboard Operations Handler

Handles loading, saving, and updating dashboard files.
All business logic for dashboard file operations.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict

AIPASS_ROOT = Path.home() / "aipass_core"
sys.path.insert(0, str(AIPASS_ROOT))


def get_dashboard_path(branch_path: Path) -> Path:
    """
    Get DASHBOARD.local.json path for a branch

    Args:
        branch_path: Path to branch root

    Returns:
        Path to dashboard file
    """
    return branch_path / "DASHBOARD.local.json"


def load_dashboard(branch_path: Path, template: Dict) -> Dict:
    """
    Load branch dashboard, creating if needed

    Args:
        branch_path: Path to branch root
        template: Dashboard template to use for new dashboards

    Returns:
        Dashboard data dict
    """
    dashboard_path = get_dashboard_path(branch_path)

    if dashboard_path.exists():
        content = dashboard_path.read_text().strip()
        # Handle empty or whitespace-only files (race condition protection)
        if not content:
            # File exists but is empty - treat as new dashboard
            new_dashboard = template.copy()
            new_dashboard["branch"] = branch_path.name.upper()
            return new_dashboard
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # Corrupted file - recreate from template
            new_dashboard = template.copy()
            new_dashboard["branch"] = branch_path.name.upper()
            return new_dashboard
        # Ensure sections exist
        if "sections" not in data:
            data["sections"] = template["sections"].copy()
        return data

    # Return new dashboard from template
    new_dashboard = template.copy()
    new_dashboard["branch"] = branch_path.name.upper()
    return new_dashboard


def save_dashboard(branch_path: Path, data: Dict) -> bool:
    """
    Save branch dashboard

    Args:
        branch_path: Path to branch root
        data: Dashboard data to save

    Returns:
        True if saved successfully

    Raises:
        OSError: If file write fails
    """
    data["last_updated"] = datetime.now().isoformat()
    dashboard_path = get_dashboard_path(branch_path)
    dashboard_path.write_text(json.dumps(data, indent=2))
    return True


def create_fresh_dashboard(branch_path: Path) -> Dict:
    """
    Create fresh dashboard with clean structure - NO preservation.

    This is the master function for creating/resetting dashboards.
    All services should call this, then populate their section.

    Tries loading from the template file first for schema consistency,
    falls back to hardcoded structure for backward compatibility.

    Args:
        branch_path: Path to branch root

    Returns:
        Fresh dashboard dict with warning and all sections
    """
    # Try loading from template file
    template_file = Path.home() / "aipass_os" / "dev_central" / "devpulse" / "templates" / "DASHBOARD.template.json"
    if template_file.exists():
        try:
            template = json.loads(template_file.read_text())
            now = datetime.now().isoformat()
            # Replace placeholders
            dashboard = json.loads(
                json.dumps(template).replace("{{BRANCHNAME}}", branch_path.name.upper())
            )
            dashboard["last_updated"] = now
            return dashboard
        except (json.JSONDecodeError, OSError):
            pass  # Fall through to hardcoded

    # Fallback: hardcoded (backward compat)
    now = datetime.now().isoformat()
    return {
        "_warning": "AUTO-GENERATED FILE - DO NOT MANUALLY EDIT. This file is 100% automated and will be overwritten. Services update their own sections.",
        "branch": branch_path.name.upper(),
        "last_updated": now,
        "quick_status": {"action_required": False},
        "sections": {
            "ai_mail": {"managed_by": "ai_mail", "new": 0, "opened": 0, "total": 0, "last_updated": ""},
            "flow": {"managed_by": "flow", "active_plans": 0, "recently_closed": [], "last_updated": ""},
            "memory_bank": {"managed_by": "memory_bank", "vectors_stored": 0, "notes": {}, "last_updated": ""},
            "devpulse": {"managed_by": "devpulse", "summary": {}, "last_updated": ""},
            "commons_activity": {"managed_by": "the_commons", "mentions": 0, "new_posts_since_last_visit": 0, "new_comments_since_last_visit": 0, "last_updated": ""}
        }
    }


def ensure_dashboard_structure(branch_path: Path) -> Dict:
    """
    Load dashboard, ensure all sections exist, return data.

    If dashboard doesn't exist, creates with default structure.
    If sections are missing, adds them with defaults.
    This allows services to always find their section ready.

    Args:
        branch_path: Path to the branch directory

    Returns:
        Dict with complete dashboard structure

    Raises:
        json.JSONDecodeError: If dashboard file is corrupted
    """
    dashboard_path = branch_path / "DASHBOARD.local.json"

    # Default structure - quick_status at top, flow at bottom (stacked output)
    now = datetime.now().isoformat()
    default = {
        "branch": branch_path.name.upper(),
        "last_updated": now,
        "quick_status": {"action_required": False},
        "sections": {
            "ai_mail": {"managed_by": "ai_mail", "new": 0, "opened": 0, "total": 0, "last_updated": ""},
            "flow": {"managed_by": "flow", "active_plans": 0, "recently_closed": [], "last_updated": ""},
            "memory_bank": {"managed_by": "memory_bank", "vectors_stored": 0, "notes": {}, "last_updated": ""},
            "devpulse": {"managed_by": "devpulse", "summary": {}, "last_updated": ""},
            "commons_activity": {"managed_by": "the_commons", "mentions": 0, "new_posts_since_last_visit": 0, "new_comments_since_last_visit": 0, "last_updated": ""}
        }
    }

    if dashboard_path.exists():
        try:
            content = dashboard_path.read_text().strip()
            # Handle empty or whitespace-only files (race condition protection)
            if not content:
                return default
            data = json.loads(content)
            # Merge: keep existing data, add missing sections
            if "sections" not in data:
                data["sections"] = {}
            for section, content in default["sections"].items():
                if section not in data["sections"]:
                    data["sections"][section] = content
            return data
        except json.JSONDecodeError:
            # Re-raise to let caller handle
            raise
    else:
        return default


def update_section(
    branch_path: Path,
    section_name: str,
    section_data: Dict,
    template: Dict,
    calculate_status_func
) -> bool:
    """
    Update a specific section in branch dashboard (legacy interface).

    Used by the module-level wrapper that passes template and status func.
    For new integrations, prefer write_section() which is self-contained.

    Args:
        branch_path: Path to branch root
        section_name: Section to update (flow, ai_mail, etc)
        section_data: New data for section
        template: Dashboard template for fallback
        calculate_status_func: Function to calculate quick status

    Returns:
        True if updated successfully

    Raises:
        Exception: If load or save fails
    """
    dashboard = load_dashboard(branch_path, template)

    # Update only the specified section
    if "sections" not in dashboard:
        dashboard["sections"] = {}

    section_data["last_updated"] = datetime.now().isoformat()
    dashboard["sections"][section_name] = section_data

    # Recalculate quick status
    dashboard["quick_status"] = calculate_status_func(dashboard["sections"])

    return save_dashboard(branch_path, dashboard)


def _calculate_quick_status_standalone(sections: Dict) -> Dict:
    """
    Calculate quick_status from live section data.

    Self-contained version used by write_section() so it has no
    external dependencies. Reads directly from section fields.

    Args:
        sections: All dashboard sections dict

    Returns:
        Quick status dict with summary, action flags, and counts
    """
    ai_mail = sections.get("ai_mail", {})
    flow = sections.get("flow", {})
    commons = sections.get("commons_activity", {})

    new_mail = ai_mail.get("new", ai_mail.get("unread", 0))
    opened_mail = ai_mail.get("opened", 0)
    active_plans = flow.get("active_plans", 0)
    mentions = commons.get("mentions", 0)

    # Action required if new mail, active plans, or commons mentions
    action_required = new_mail > 0 or active_plans > 0 or mentions > 0

    parts = []
    if new_mail > 0:
        parts.append(f"{new_mail} new emails")
    if opened_mail > 0:
        parts.append(f"{opened_mail} opened")
    if active_plans > 0:
        parts.append(f"{active_plans} active plans")
    if mentions > 0:
        parts.append(f"{mentions} mentions")

    return {
        "new_mail": new_mail,
        "opened_mail": opened_mail,
        "active_plans": active_plans,
        "commons_mentions": mentions,
        "action_required": action_required,
        "summary": ", ".join(parts) if parts else "All clear"
    }


def write_section(branch_path: Path, section_name: str, section_data: Dict) -> bool:
    """
    Write-through API: update a single section in a branch's dashboard.

    This is THE function all services call to push their data into a
    branch's DASHBOARD.local.json. It is dependency-free (no imports
    from ai_mail, flow, etc.) and safe to call from any branch's code.

    Behavior:
        - Loads the branch's DASHBOARD.local.json (creates from template if missing)
        - Updates ONLY the named section (preserves all other sections)
        - Automatically adds "last_updated" ISO timestamp to section_data
        - Recalculates quick_status from live section data
        - Saves back to disk

    Args:
        branch_path: Path to branch root directory (e.g. Path("/home/aipass/aipass_os/dev_central/devpulse"))
        section_name: Section key (e.g. "ai_mail", "flow", "commons_activity")
        section_data: Dict of data for this section. Will be written as-is
            with an auto-added "last_updated" timestamp.

    Returns:
        True if saved successfully, False on any error

    Example:
        >>> from aipass_os.dev_central.devpulse.apps.modules.dashboard import write_section
        >>> write_section(Path("/home/aipass/aipass_os/flow"), "flow", {"active_plans": 2})
        True
    """
    try:
        branch_path = Path(branch_path)
        dashboard_path = get_dashboard_path(branch_path)

        # Load existing or create from fresh template
        if dashboard_path.exists():
            content = dashboard_path.read_text().strip()
            if content:
                try:
                    dashboard = json.loads(content)
                except json.JSONDecodeError:
                    dashboard = create_fresh_dashboard(branch_path)
            else:
                dashboard = create_fresh_dashboard(branch_path)
        else:
            dashboard = create_fresh_dashboard(branch_path)

        # Ensure sections dict exists
        if "sections" not in dashboard:
            dashboard["sections"] = {}

        # Stamp the section data with ISO timestamp
        section_data["last_updated"] = datetime.now().isoformat()

        # Write ONLY the named section, preserve everything else
        dashboard["sections"][section_name] = section_data

        # Recalculate quick_status from live data
        dashboard["quick_status"] = _calculate_quick_status_standalone(dashboard["sections"])

        # Save
        return save_dashboard(branch_path, dashboard)

    except Exception:
        return False
