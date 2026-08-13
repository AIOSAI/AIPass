# =================== AIPass ====================
# Name: refresh.py
# Description: Dashboard Refresh Handler
# Version: 0.6.0
# Created: 2026-02-25
# Modified: 2026-08-13
# =============================================

"""
Dashboard Refresh Handler

Reads all .central.json files and writes to branch dashboards.
AIPASS owns all dashboards - services only maintain their central files.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List

from aipass.prax.apps.modules.logger import get_direct_logger

logger = get_direct_logger()

# Same-package imports allowed
from .operations import create_fresh_dashboard, save_dashboard  # noqa: E402
from .status import calculate_quick_status, merge_quick_status, read_existing_quick_status  # noqa: E402

# Cross-handler imports for central reader
from ..central.reader import read_all_centrals  # noqa: E402

from aipass.prax.apps.handlers.json import json_handler  # noqa: E402
from .template_pusher import DEPRECATED_SECTIONS  # noqa: E402

# Sections managed by the refresh path — everything else is write-through only
REFRESH_MANAGED_SECTIONS = {"ai_mail", "flow", "memory"}


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


# Infrastructure
AIPASS_REGISTRY = _find_repo_root() / "AIPASS_REGISTRY.json"


def _load_branch_paths() -> List[Path]:
    """
    Load all branch paths from registry.

    Returns:
        List of Path objects for each branch

    Raises:
        FileNotFoundError: If registry doesn't exist
    """
    if not AIPASS_REGISTRY.exists():
        raise FileNotFoundError(f"AIPASS_REGISTRY.json not found: {AIPASS_REGISTRY}")

    repo_root = _find_repo_root()
    data = json.loads(AIPASS_REGISTRY.read_text())
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
        {"plan_id": p.get("plan_id", ""), "subject": p.get("subject", "")} for p in recently_closed_raw[:5]
    ]

    return {
        "managed_by": "flow",
        "active_plans": len(branch_plans),
        "recently_closed": recently_closed,
        "last_updated": plans_data.get("generated_at", plans_data.get("last_updated", datetime.now().isoformat())),
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
        "last_updated": mail_data.get("last_updated", datetime.now().isoformat()),
    }


def _extract_memory_section(centrals: Dict, branch_path: Path) -> Dict:
    """
    Extract memory section - LOCAL vectors for this branch.

    Each branch shows its own .chroma/ vector count, not the global count.
    Global stats are in MEMORY.central.json for reference only.
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
        except Exception as e:
            logger.warning("Failed to read ChromaDB vectors from %s: %s", chroma_dir, e)

    # Pull last_updated from central if available
    mb_data = centrals.get("memory", {})
    mb_last_updated = mb_data.get("last_updated", datetime.now().isoformat())

    return {"managed_by": "memory", "vectors_stored": local_vectors, "notes": {}, "last_updated": mb_last_updated}


def _calculate_quick_status(sections: Dict, branch_path: Path) -> Dict:
    """
    Calculate quick_status from branch data sources.

    Thin delegate to the single implementation in status.py. This was a full
    copy until 2026-08-13; the copy never grew status.py's list-shape guard,
    which is how one bug survived in two places (@flow, DPLAN-0290 item 4).

    Args:
        sections: All dashboard sections dict
        branch_path: Path to branch root (for sourcing counts from local files)

    Returns:
        Quick status dict with counts, action flag, and summary
    """
    return calculate_quick_status(sections, branch_path)


def _prune_deprecated_sections(dashboard: Dict) -> None:
    """Remove deprecated sections from dashboard before save."""
    sections = dashboard.get("sections", {})
    for key in DEPRECATED_SECTIONS:
        sections.pop(key, None)


def _preserve_write_through_sections(dashboard: Dict, branch_path: Path, branch_name: str) -> None:
    """Preserve write-through sections not managed by refresh."""
    existing_path = branch_path / "DASHBOARD.local.json"
    if not existing_path.exists():
        return
    try:
        existing = json.loads(existing_path.read_text())
        for key, value in existing.get("sections", {}).items():
            if key not in REFRESH_MANAGED_SECTIONS and key not in dashboard["sections"]:
                dashboard["sections"][key] = value
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to preserve write-through sections for %s: %s", branch_name, e)


def _run_devpulse_plugin(branch_path: Path) -> None:
    """Invoke devpulse dashboard plugin refresh for custom sections."""
    try:
        from aipass.prax.apps.plugins.devpulse_dashboard.refresh import refresh as devpulse_refresh

        devpulse_refresh(branch_path)
    except Exception as e:
        logger.warning("Devpulse plugin refresh failed: %s", e)


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
        logger.error("Failed to load branch paths: %s", e)
        return {"status": "error", "branches_updated": 0, "branches_failed": 0, "errors": [str(e)]}

    # Update each branch
    for branch_path in branch_paths:
        branch_name = branch_path.name.upper()

        try:
            # Create fresh dashboard
            dashboard = create_fresh_dashboard(branch_path)

            # Populate sections from centrals
            dashboard["sections"]["ai_mail"] = _extract_ai_mail_section(centrals, branch_name)
            dashboard["sections"]["flow"] = _extract_flow_section(centrals, branch_name)
            dashboard["sections"]["memory"] = _extract_memory_section(centrals, branch_path)

            _preserve_write_through_sections(dashboard, branch_path, branch_name)
            _prune_deprecated_sections(dashboard)

            # Calculate quick status (ai_mail section still present for counts).
            # Merged over what is already on disk: the dashboard was rebuilt from
            # the template, so other services' keys live only in the old file.
            dashboard["quick_status"] = merge_quick_status(
                read_existing_quick_status(branch_path),
                _calculate_quick_status(dashboard["sections"], branch_path),
            )
            dashboard["sections"].pop("ai_mail", None)

            # Save
            save_dashboard(branch_path, dashboard)

            # Invoke devpulse plugin refresh for custom sections (git, session, dispatch)
            if branch_name == "DEVPULSE":
                _run_devpulse_plugin(branch_path)

            branches_updated += 1

        except Exception as e:
            logger.warning("Dashboard refresh failed for %s: %s", branch_name, e)
            errors.append(f"{branch_name}: {str(e)}")
            branches_failed += 1

    # Determine status
    if branches_failed == 0:
        status = "success"
    elif branches_updated > 0:
        status = "partial"
    else:
        status = "error"

    json_handler.log_operation(
        "dashboard_refreshed",
        {
            "status": status,
            "branches_updated": branches_updated,
            "branches_failed": branches_failed,
        },
    )

    return {
        "status": status,
        "branches_updated": branches_updated,
        "branches_failed": branches_failed,
        "errors": errors,
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
        dashboard["sections"]["memory"] = _extract_memory_section(centrals, branch_path)

        _preserve_write_through_sections(dashboard, branch_path, branch_name)
        _prune_deprecated_sections(dashboard)

        dashboard["quick_status"] = merge_quick_status(
            read_existing_quick_status(branch_path),
            _calculate_quick_status(dashboard["sections"], branch_path),
        )
        dashboard["sections"].pop("ai_mail", None)

        save_dashboard(branch_path, dashboard)

        # Invoke devpulse plugin refresh for custom sections (git, session, dispatch)
        if branch_name == "DEVPULSE":
            _run_devpulse_plugin(branch_path)

        return {"status": "success", "branch": branch_name}

    except Exception as e:
        logger.error("Single dashboard refresh failed for %s: %s", branch_name, e)
        return {"status": "error", "branch": branch_name, "error": str(e)}
