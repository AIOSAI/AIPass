# =================== AIPass ====================
# Name: bulletin_created.py
# Description: Bulletin created event handler for dashboard propagation
# Version: 1.0.0
# Created: 2026-01-31
# Modified: 2026-01-31
# =============================================

"""
Bulletin Created Event Handler

Handles bulletin_created events fired when a new bulletin is created.
Propagates the bulletin to all branch dashboards.

Event data expected:
    - bulletin_id: ID of the created bulletin
    - title: Bulletin title
    - message: Bulletin content
    - priority: Bulletin priority level
    - created_by: Who created it
    - timestamp: When created
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from aipass.trigger.apps.handlers.json import json_handler

def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()

_REPO_ROOT = _find_repo_root()

# Paths
BRANCH_REGISTRY = _REPO_ROOT / "BRANCH_REGISTRY.json"
BULLETINS_PATH = _REPO_ROOT / "BULLETINS.central.json"


def _load_branch_registry() -> List[Dict]:
    """
    Load branch registry silently.

    Returns:
        List of branch dicts with name, path, status.
        Empty list on any error.
    """
    try:
        if not BRANCH_REGISTRY.exists():
            return []
        data = json.loads(BRANCH_REGISTRY.read_text())
        return data.get("branches", [])
    except Exception:
        return []


def _load_bulletins() -> List[Dict]:
    """
    Load bulletins from central storage.

    Returns:
        List of bulletin dicts. Empty list on error.
    """
    try:
        if not BULLETINS_PATH.exists():
            return []
        data = json.loads(BULLETINS_PATH.read_text())
        return data.get("bulletins", [])
    except Exception:
        return []


def _filter_active_bulletins(bulletins: List[Dict]) -> List[Dict]:
    """
    Filter bulletins to only active ones.

    Args:
        bulletins: List of all bulletins

    Returns:
        List of active bulletins only
    """
    return [b for b in bulletins if b.get("active", False)]


def _load_dashboard(branch_path: Path) -> Dict:
    """
    Load existing dashboard or create minimal structure.

    Args:
        branch_path: Path to branch root

    Returns:
        Dashboard data dict (existing or minimal structure)
    """
    dashboard_path = branch_path / "DASHBOARD.local.json"

    if dashboard_path.exists():
        try:
            data = json.loads(dashboard_path.read_text())
            if "sections" not in data:
                data["sections"] = {}
            if "bulletin_board" not in data["sections"]:
                data["sections"]["bulletin_board"] = {
                    "managed_by": "aipass",
                    "active_bulletins": [],
                    "pending_ack": []
                }
            return data
        except Exception:
            pass

    # Create minimal dashboard structure
    return {
        "last_refreshed": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sections": {
            "bulletin_board": {
                "managed_by": "aipass",
                "active_bulletins": [],
                "pending_ack": []
            }
        }
    }


def _save_dashboard(branch_path: Path, dashboard: Dict) -> bool:
    """
    Save dashboard to branch.

    Args:
        branch_path: Path to branch root
        dashboard: Dashboard data to save

    Returns:
        True if saved, False on error
    """
    try:
        dashboard_path = branch_path / "DASHBOARD.local.json"
        dashboard["last_refreshed"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dashboard_path.write_text(json.dumps(dashboard, indent=2))
        return True
    except Exception:
        return False


def _propagate_bulletins_to_branches() -> None:
    """
    Propagate active bulletins to all branch dashboards.

    Loads active bulletins and updates each branch's dashboard
    with the bulletin_board section.

    Silent failure - catches all exceptions.
    """
    try:
        # Load branch registry
        branches = _load_branch_registry()
        if not branches:
            return

        # Load and filter active bulletins
        all_bulletins = _load_bulletins()
        active_bulletins = _filter_active_bulletins(all_bulletins)

        # Update each branch dashboard
        for branch in branches:
            branch_path_str = branch.get("path")
            if not branch_path_str:
                continue

            branch_path = Path(branch_path_str)
            if not branch_path.exists():
                continue

            try:
                # Load dashboard
                dashboard = _load_dashboard(branch_path)

                # Update bulletin_board section ONLY
                if "sections" not in dashboard:
                    dashboard["sections"] = {}

                dashboard["sections"]["bulletin_board"] = {
                    "managed_by": "aipass",
                    "active_bulletins": active_bulletins,
                    "pending_ack": []
                }

                # Save dashboard
                _save_dashboard(branch_path, dashboard)
            except Exception:
                continue

    except Exception:
        pass


def handle_bulletin_created(
    _bulletin_id: str | None = None,
    _title: str | None = None,
    _message: str | None = None,
    _priority: str | None = None,
    _created_by: str | None = None,
    _timestamp: str | None = None,
    **_kwargs: Any
) -> None:
    """
    Handle bulletin_created event - propagate bulletin to all branch dashboards.

    Event parameters are received but not used directly - we reload from
    central storage to ensure consistency with any concurrent updates.

    Args:
        _bulletin_id: ID of the created bulletin (unused - reload from storage)
        _title: Bulletin title (unused - reload from storage)
        _message: Bulletin content (unused - reload from storage)
        _priority: Bulletin priority level (unused - reload from storage)
        _created_by: Who created it (unused - reload from storage)
        _timestamp: When created (unused - reload from storage)
        **_kwargs: Additional event data (ignored)
    """
    try:
        # Propagate bulletins to all branches
        # We reload from central storage to ensure consistency
        # (the newly created bulletin should already be saved there)
        _propagate_bulletins_to_branches()

        json_handler.log_operation("bulletin_event", {"success": True})

    except Exception:
        pass
