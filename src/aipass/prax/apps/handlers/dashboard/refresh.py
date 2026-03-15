# =================== AIPass ====================
# Name: refresh.py
# Description: Dashboard Refresh Handler
# Version: 0.5.0
# Created: 2026-02-25
# Modified: 2026-03-09
# =============================================

"""
Dashboard Refresh Handler

Reads all .central.json files and writes to branch dashboards.
AIPASS owns all dashboards - services only maintain their central files.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Same-package imports allowed
from .operations import create_fresh_dashboard, save_dashboard

# Cross-handler imports for central reader
from ..central.reader import read_all_centrals

# Sections managed by the refresh path — everything else is write-through only
REFRESH_MANAGED_SECTIONS = {"ai_mail", "flow", "memory_bank", "commons_activity"}


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


# Infrastructure
BRANCH_REGISTRY = _find_repo_root() / "AIPASS_REGISTRY.json"


def _load_branch_paths() -> List[Path]:
    """
    Load all branch paths from registry.

    Returns:
        List of Path objects for each branch

    Raises:
        FileNotFoundError: If registry doesn't exist
    """
    if not BRANCH_REGISTRY.exists():
        raise FileNotFoundError(f"Branch registry not found: {BRANCH_REGISTRY}")

    repo_root = _find_repo_root()
    data = json.loads(BRANCH_REGISTRY.read_text())
    branches = data.get("branches", [])

    paths = []
    for branch in branches:
        path_str = branch.get("path")
        if path_str:
            raw = Path(path_str)
            path = raw if raw.is_absolute() else repo_root / raw
            if path.exists():
                paths.append(path)

    return paths


def _extract_flow_section(centrals: Dict, branch_name: str) -> Dict:
    """Extract flow section from PLANS.central.json"""
    plans_data = centrals.get("plans")
    if not plans_data:
        return {"managed_by": "flow", "active_plans": 0, "recently_closed": []}

    active_plans = plans_data.get("active_plans", [])

    # Count plans for this branch (case-insensitive — centrals use lowercase, refresh uses uppercase)
    branch_plans = [p for p in active_plans if p.get("branch", "").upper() == branch_name]

    # Get recently_closed from top-level (already limited to 5 by push_central)
    recently_closed_raw = plans_data.get("recently_closed", [])
    # Simplify for dashboard display (just id and subject)
    recently_closed = [
        {"plan_id": p.get("plan_id", ""), "subject": p.get("subject", "")}
        for p in recently_closed_raw[:5]
    ]

    return {
        "managed_by": "flow",
        "active_plans": len(branch_plans),
        "recently_closed": recently_closed,
        "last_updated": plans_data.get("generated_at", plans_data.get("last_updated", datetime.now().isoformat()))
    }


def _extract_ai_mail_section(centrals: Dict, branch_name: str) -> Dict:
    """Extract ai_mail section from AI_MAIL.central.json"""
    mail_data = centrals.get("ai_mail")
    if not mail_data:
        return {"managed_by": "ai_mail", "unread": 0, "total": 0}

    branch_stats = mail_data.get("branch_stats", {})
    stats = branch_stats.get(branch_name, {"unread": 0, "total": 0})

    return {
        "managed_by": "ai_mail",
        "unread": stats.get("unread", 0),
        "total": stats.get("total", 0),
        "last_updated": mail_data.get("last_updated", datetime.now().isoformat())
    }


def _extract_memory_bank_section(centrals: Dict, branch_path: Path) -> Dict:
    """
    Extract memory_bank section - LOCAL vectors for this branch.

    Each branch shows its own .chroma/ vector count, not the global count.
    Global stats are in MEMORY_BANK.central.json for reference only.
    """
    local_vectors = 0

    # Check for local .chroma directory
    chroma_dir = branch_path / ".chroma"
    if chroma_dir.exists():
        # Try to count vectors from local ChromaDB
        try:
            sqlite_file = chroma_dir / "chroma.sqlite3"
            if sqlite_file.exists():
                import sqlite3
                conn = sqlite3.connect(str(sqlite_file))
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM embeddings")
                local_vectors = cursor.fetchone()[0]
                conn.close()
        except Exception:
            pass

    # Pull last_updated from central if available
    mb_data = centrals.get("memory_bank", {})
    mb_last_updated = mb_data.get("last_updated", datetime.now().isoformat())

    return {
        "managed_by": "memory_bank",
        "vectors_stored": local_vectors,
        "notes": {},
        "last_updated": mb_last_updated
    }


def _extract_commons_section(centrals: Dict, branch_name: str) -> Optional[Dict]:
    """
    Extract commons_activity section from COMMONS.central.json.

    Returns None if no commons central data exists, signaling the caller
    to preserve existing write-through data instead of overwriting with zeros.

    Args:
        centrals: Dict of all central file data
        branch_name: Uppercase branch name

    Returns:
        Dict with commons activity data, or None if no central data
    """
    commons_data = centrals.get("commons")
    if not commons_data:
        return None

    branch_stats = commons_data.get("branch_stats", {})
    stats = branch_stats.get(branch_name, {})

    return {
        "managed_by": "the_commons",
        "mentions": stats.get("mentions", 0),
        "new_posts_since_last_visit": stats.get("new_posts_since_last_visit", 0),
        "new_comments_since_last_visit": stats.get("new_comments_since_last_visit", 0),
        "last_updated": stats.get("last_updated", "")
    }


def _calculate_quick_status(sections: Dict) -> Dict:
    """
    Calculate quick_status from live section data (v3 schema).

    bulletin_board removed (FPLAN-0373). commons mentions added.

    Args:
        sections: All dashboard sections dict

    Returns:
        Quick status dict with counts, action flag, and summary
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


def refresh_all_dashboards() -> Dict:
    """
    Refresh all branch dashboards from central files.

    This is the main entry point. Reads all .central.json files,
    then writes to all branch DASHBOARD.local.json files.

    Returns:
        Dict with status, branches_updated, branches_failed, errors
    """
    errors = []
    branches_updated = 0
    branches_failed = 0

    # Read all central files
    centrals = read_all_centrals()

    # Get all branch paths
    try:
        branch_paths = _load_branch_paths()
    except Exception as e:
        return {
            "status": "error",
            "branches_updated": 0,
            "branches_failed": 0,
            "errors": [str(e)]
        }

    # Update each branch
    for branch_path in branch_paths:
        branch_name = branch_path.name.upper()

        try:
            # Create fresh dashboard
            dashboard = create_fresh_dashboard(branch_path)

            # Populate sections from centrals
            dashboard["sections"]["ai_mail"] = _extract_ai_mail_section(centrals, branch_name)
            dashboard["sections"]["flow"] = _extract_flow_section(centrals, branch_name)
            dashboard["sections"]["memory_bank"] = _extract_memory_bank_section(centrals, branch_path)

            # Commons: preserve existing write-through data if no central file
            commons_section = _extract_commons_section(centrals, branch_name)
            if commons_section is not None:
                dashboard["sections"]["commons_activity"] = commons_section
            else:
                existing_path = branch_path / "DASHBOARD.local.json"
                if existing_path.exists():
                    try:
                        existing = json.loads(existing_path.read_text())
                        existing_commons = existing.get("sections", {}).get("commons_activity")
                        if existing_commons:
                            dashboard["sections"]["commons_activity"] = existing_commons
                    except (json.JSONDecodeError, OSError):
                        pass

            # Preserve write-through sections not managed by refresh (e.g. agent_status)
            existing_path = branch_path / "DASHBOARD.local.json"
            if existing_path.exists():
                try:
                    existing = json.loads(existing_path.read_text())
                    for key, value in existing.get("sections", {}).items():
                        if key not in REFRESH_MANAGED_SECTIONS and key not in dashboard["sections"]:
                            dashboard["sections"][key] = value
                except (json.JSONDecodeError, OSError):
                    pass

            # Calculate quick status
            dashboard["quick_status"] = _calculate_quick_status(dashboard["sections"])

            # Save
            save_dashboard(branch_path, dashboard)
            branches_updated += 1

        except Exception as e:
            errors.append(f"{branch_name}: {str(e)}")
            branches_failed += 1

    # Determine status
    if branches_failed == 0:
        status = "success"
    elif branches_updated > 0:
        status = "partial"
    else:
        status = "error"

    return {
        "status": status,
        "branches_updated": branches_updated,
        "branches_failed": branches_failed,
        "errors": errors
    }


def refresh_single_dashboard(branch_path: Path) -> Dict:
    """
    Refresh a single branch's dashboard.

    Args:
        branch_path: Path to branch root

    Returns:
        Dict with status and any errors
    """
    centrals = read_all_centrals()
    branch_name = branch_path.name.upper()

    try:
        dashboard = create_fresh_dashboard(branch_path)

        dashboard["sections"]["ai_mail"] = _extract_ai_mail_section(centrals, branch_name)
        dashboard["sections"]["flow"] = _extract_flow_section(centrals, branch_name)
        dashboard["sections"]["memory_bank"] = _extract_memory_bank_section(centrals, branch_path)

        # Commons: preserve existing write-through data if no central file
        commons_section = _extract_commons_section(centrals, branch_name)
        if commons_section is not None:
            dashboard["sections"]["commons_activity"] = commons_section
        else:
            existing_path = branch_path / "DASHBOARD.local.json"
            if existing_path.exists():
                try:
                    existing = json.loads(existing_path.read_text())
                    existing_commons = existing.get("sections", {}).get("commons_activity")
                    if existing_commons:
                        dashboard["sections"]["commons_activity"] = existing_commons
                except (json.JSONDecodeError, OSError):
                    pass

        # Preserve write-through sections not managed by refresh (e.g. agent_status)
        existing_path = branch_path / "DASHBOARD.local.json"
        if existing_path.exists():
            try:
                existing = json.loads(existing_path.read_text())
                for key, value in existing.get("sections", {}).items():
                    if key not in REFRESH_MANAGED_SECTIONS and key not in dashboard["sections"]:
                        dashboard["sections"][key] = value
            except (json.JSONDecodeError, OSError):
                pass

        dashboard["quick_status"] = _calculate_quick_status(dashboard["sections"])

        save_dashboard(branch_path, dashboard)

        return {"status": "success", "branch": branch_name}

    except Exception as e:
        return {"status": "error", "branch": branch_name, "error": str(e)}
