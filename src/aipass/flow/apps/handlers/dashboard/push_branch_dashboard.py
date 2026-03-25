# =================== AIPass ====================
# Name: push_branch_dashboard.py
# Description: Push flow section to branch dashboards
# Version: 1.1.0
# Created: 2026-03-01
# Modified: 2026-03-01
# =============================================

"""
Push Flow Section to Branch Dashboard

Pushes the "flow" section of a branch's DASHBOARD.local.json via the
DevPulse write_section() write-through API.

Unlike update_local.py (which updates Flow's OWN dashboard), this handler
targets the branch where a plan LIVES. Each branch sees its own active plans
on its own dashboard.

Data Flow:
    1. Read fplan_registry.json (source of truth)
    2. Filter active plans for target branch (by location path)
    3. Get recently closed plans (last 5, within last 7 days)
    4. Get total plan count for this branch
    5. Call write_section(branch_path, "flow", section_data)

Section Structure:
{
    "managed_by": "flow",
    "active_plans": [
        {"id": "FPLAN-0373", "subject": "...", "created": "...", "location": "/path/to/branch"}
    ],
    "active_count": 2,
    "recently_closed": [
        {"id": "FPLAN-0372", "subject": "...", "closed": "..."}
    ],
    "total_plans": 15
}

Usage:
    from aipass.flow.apps.handlers.dashboard.push_branch_dashboard import push_flow_to_branch_dashboard
    success = push_flow_to_branch_dashboard(Path("/path/to/branch"))
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple

from aipass.flow.apps.handlers.json import json_handler
from aipass.prax.apps.modules.logger import system_logger as logger

# INFRASTRUCTURE IMPORT PATTERN
_PKG_ROOT = Path(__file__).resolve().parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"

# Registry location
REGISTRY_FILE = FLOW_ROOT / "flow_json" / "fplan_registry.json"

# Dashboard template path (package-relative)
DASHBOARD_TEMPLATE_FILE = _PKG_ROOT / "devpulse" / "templates" / "DASHBOARD.template.json"


# =============================================
# DASHBOARD WRITE (local — no cross-branch imports)
# =============================================

def _write_dashboard_section(branch_path: Path, section_name: str, section_data: Dict[str, Any]) -> bool:
    """
    Write a single section to a branch's DASHBOARD.local.json.

    Self-contained dashboard write — equivalent to DevPulse write_section()
    but without cross-branch imports. Loads existing dashboard, updates
    the named section, recalculates quick_status, and saves.

    Args:
        branch_path: Path to branch root directory
        section_name: Section key (e.g. "flow")
        section_data: Dict of data for this section

    Returns:
        True if saved successfully, False on any error
    """
    try:
        dashboard_path = branch_path / "DASHBOARD.local.json"

        # Load existing or create fresh
        if dashboard_path.exists():
            content = dashboard_path.read_text().strip()
            if content:
                try:
                    dashboard = json.loads(content)
                except json.JSONDecodeError as exc:
                    logger.warning("Corrupt dashboard JSON at '%s', creating fresh: %s", dashboard_path, exc)
                    dashboard = _create_fresh_dashboard(branch_path)
            else:
                dashboard = _create_fresh_dashboard(branch_path)
        else:
            dashboard = _create_fresh_dashboard(branch_path)

        if "sections" not in dashboard:
            dashboard["sections"] = {}

        section_data["last_updated"] = datetime.now().isoformat()
        dashboard["sections"][section_name] = section_data
        dashboard["quick_status"] = _calculate_quick_status(dashboard["sections"])
        dashboard["last_updated"] = datetime.now().isoformat()

        dashboard_path.write_text(json.dumps(dashboard, indent=2))
        return True

    except Exception as exc:
        logger.error("Failed to write dashboard section '%s' for branch '%s': %s", section_name, branch_path, exc)
        return False


def _create_fresh_dashboard(branch_path: Path) -> Dict[str, Any]:
    """
    Create fresh dashboard structure from template or fallback.

    Args:
        branch_path: Path to branch root

    Returns:
        Fresh dashboard dict
    """
    if DASHBOARD_TEMPLATE_FILE.exists():
        try:
            template = json.loads(DASHBOARD_TEMPLATE_FILE.read_text())
            dashboard = json.loads(
                json.dumps(template).replace("{{BRANCHNAME}}", branch_path.name.upper())
            )
            dashboard["last_updated"] = datetime.now().isoformat()
            return dashboard
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load dashboard template '%s', using fallback: %s", DASHBOARD_TEMPLATE_FILE, exc)

    now = datetime.now().isoformat()
    return {
        "_warning": "AUTO-GENERATED FILE - DO NOT MANUALLY EDIT.",
        "branch": branch_path.name.upper(),
        "last_updated": now,
        "quick_status": {"action_required": False},
        "sections": {
            "ai_mail": {"managed_by": "ai_mail", "new": 0, "opened": 0, "total": 0, "last_updated": ""},
            "flow": {"managed_by": "flow", "active_plans": 0, "recently_closed": [], "last_updated": ""},
            "memory_bank": {"managed_by": "memory_bank", "vectors_stored": 0, "notes": {}, "last_updated": ""},
            "devpulse": {"managed_by": "devpulse", "summary": {}, "last_updated": ""},
            "commons_activity": {"managed_by": "commons", "mentions": 0, "last_updated": ""}
        }
    }


def _calculate_quick_status(sections: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate quick_status from live section data.

    Args:
        sections: All dashboard sections dict

    Returns:
        Quick status dict
    """
    ai_mail = sections.get("ai_mail", {})
    flow = sections.get("flow", {})
    commons = sections.get("commons_activity", {})

    new_mail = ai_mail.get("new", ai_mail.get("unread", 0))
    opened_mail = ai_mail.get("opened", 0)
    active_plans = flow.get("active_plans", 0)
    mentions = commons.get("mentions", 0)

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


# =============================================
# HELPER FUNCTIONS
# =============================================

def _load_registry() -> Dict[str, Any]:
    """
    Load fplan_registry.json.

    Returns:
        Registry dict or empty structure if unavailable
    """
    try:
        if not REGISTRY_FILE.exists():
            return {"plans": {}, "next_number": 1}
        with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Failed to load fplan registry '%s': %s", REGISTRY_FILE, exc)
        return {"plans": {}, "next_number": 1}


def _filter_branch_plans(
    registry: Dict[str, Any],
    branch_path: Path
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """
    Filter plans for a specific branch from the registry.

    Args:
        registry: Full fplan_registry.json data
        branch_path: Absolute path to the branch directory

    Returns:
        Tuple of (active_plans, recently_closed_plans, total_branch_plans)
    """
    plans = registry.get("plans", {})
    branch_path_str = str(branch_path)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)

    active_plans = []
    closed_plans = []
    branch_total = 0

    for plan_num, plan_data in plans.items():
        location = plan_data.get("location", "")

        # Match plans whose location is this branch
        if location != branch_path_str:
            continue

        branch_total += 1
        plan_id = f"FPLAN-{plan_num.zfill(4)}"

        if plan_data.get("status") == "open":
            active_plans.append({
                "id": plan_id,
                "subject": plan_data.get("subject", ""),
                "created": plan_data.get("created", ""),
                "location": location
            })
        elif plan_data.get("status") == "closed":
            closed_ts = plan_data.get("closed", "")
            # Only include recently closed (within 7 days)
            if closed_ts:
                try:
                    closed_dt = datetime.fromisoformat(closed_ts)
                    if closed_dt >= cutoff:
                        closed_plans.append({
                            "id": plan_id,
                            "subject": plan_data.get("subject", ""),
                            "closed": closed_ts
                        })
                except (ValueError, TypeError) as exc:
                    # If we can't parse the timestamp, include it anyway
                    logger.warning("Unparseable closed timestamp '%s' for plan %s, including anyway: %s", closed_ts, plan_id, exc)
                    closed_plans.append({
                        "id": plan_id,
                        "subject": plan_data.get("subject", ""),
                        "closed": closed_ts
                    })

    # Sort active by created date (newest first)
    active_plans.sort(key=lambda x: x.get("created", ""), reverse=True)

    # Sort closed by closed date (newest first), limit to 5
    closed_plans.sort(key=lambda x: x.get("closed", ""), reverse=True)
    recent_closed = closed_plans[:5]

    return active_plans, recent_closed, branch_total


def _build_section_data(
    active_plans: List[Dict[str, Any]],
    recently_closed: List[Dict[str, Any]],
    total_plans: int
) -> Dict[str, Any]:
    """
    Build the flow section data for write_section().

    Args:
        active_plans: List of active plan dicts
        recently_closed: List of recently closed plan dicts
        total_plans: Total plan count for this branch

    Returns:
        Section data dict ready for write_section()
    """
    return {
        "managed_by": "flow",
        "active_plans": active_plans,
        "active_count": len(active_plans),
        "recently_closed": recently_closed,
        "total_plans": total_plans
    }


# =============================================
# HANDLER FUNCTION
# =============================================

def push_flow_to_branch_dashboard(branch_path: Path) -> bool:
    """
    Push flow section to a branch's DASHBOARD.local.json via write_section().

    Reads the flow registry, filters plans for the target branch,
    and writes the flow section to the branch's dashboard.

    Dashboard write failures are silent (returns False, never raises).

    Args:
        branch_path: Absolute path to the branch directory
            (e.g. Path("/repo/src/aipass/devpulse"))

    Returns:
        True if successfully written, False on any error
    """
    try:
        branch_path = Path(branch_path)

        # Guard: only push to paths that already have a dashboard (real branches)
        dashboard_file = branch_path / "DASHBOARD.local.json"
        if not dashboard_file.exists():
            return False

        # 1. Load the registry
        registry = _load_registry()

        # 2. Filter plans for this branch
        active_plans, recently_closed, total_plans = _filter_branch_plans(registry, branch_path)

        # 3. Build section data
        section_data = _build_section_data(active_plans, recently_closed, total_plans)

        # 4. Write flow section to branch dashboard
        result = _write_dashboard_section(branch_path, "flow", section_data)

        if result:
            json_handler.log_operation("branch_dashboard_pushed", {
                "branch": branch_path.name,
                "active_plans": len(active_plans),
                "recently_closed": len(recently_closed),
                "total_plans": total_plans,
                "success": True,
            })

        return result

    except Exception as exc:
        logger.error("Failed to push flow section to branch dashboard '%s': %s", branch_path, exc)
        return False
