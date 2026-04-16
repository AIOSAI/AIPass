# =================== AIPass ====================
# Name: template_differ.py
# Description: Dashboard Template Diff Handler
# Version: 1.0.0
# Created: 2026-02-25
# Modified: 2026-03-09
# =============================================

"""
Dashboard Template Diff Handler

Compares the dashboard template against branch DASHBOARD.local.json files.
Reports structural differences without modifying any files.

Purpose:
    Audit tool to see what would change before pushing templates.
    Shows additions (sections in template not in branch), removals
    (deprecated sections in branch not in template), and modifications
    (quick_status keys that are outdated).

Independence:
    Reads template and registry directly. No service dependencies.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional

from aipass.prax.apps.modules.logger import get_direct_logger

from aipass.prax.apps.handlers.json import json_handler

logger = get_direct_logger()

# =============================================================================
# PATH RESOLUTION
# =============================================================================

_PRAX_ROOT = Path(__file__).resolve().parents[3]  # .../prax/


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


# =============================================================================
# CONSTANTS
# =============================================================================

TEMPLATE_DIR = _PRAX_ROOT / "templates"
TEMPLATE_FILE = TEMPLATE_DIR / "DASHBOARD.template.json"
AIPASS_REGISTRY = _find_repo_root() / "AIPASS_REGISTRY.json"

# Deprecated sections that should be flagged for removal
DEPRECATED_SECTIONS = ["bulletin_board", "devpulse"]

# Deprecated quick_status keys that should be flagged
DEPRECATED_QUICK_STATUS_KEYS = ["pending_bulletins"]

# Required sections (from template)
REQUIRED_SECTIONS = ["ai_mail", "flow", "memory", "commons_activity"]


# =============================================================================
# DIFF LOGIC
# =============================================================================


def _diff_branch(branch_name: str, branch_path: Path, template: dict) -> Dict[str, Any]:
    """
    Compare a single branch's dashboard against the template.

    Args:
        branch_name: Uppercase branch name
        branch_path: Path to branch directory
        template: Loaded template dict

    Returns:
        Dict with branch, path, additions, removals, modifications, status
    """
    result: Dict[str, Any] = {
        "branch": branch_name,
        "path": str(branch_path),
        "additions": [],
        "removals": [],
        "modifications": [],
        "status": "up_to_date",
    }

    dashboard_path = branch_path / "DASHBOARD.local.json"

    if not dashboard_path.exists():
        result["status"] = "missing"
        return result

    content = dashboard_path.read_text().strip()
    if not content:
        result["status"] = "missing"
        result["additions"].append("entire dashboard (file is empty)")
        return result

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON in dashboard for diff: %s", e)
        result["status"] = "invalid_json"
        return result

    # Check _warning header
    if "_warning" not in data:
        result["additions"].append("_warning header")

    # Check sections dict exists
    sections = data.get("sections", {})
    if not isinstance(sections, dict):
        result["additions"].append("sections dict (missing or invalid)")
        result["status"] = "needs_update"
        return result

    # Check for missing required sections
    for section_name in REQUIRED_SECTIONS:
        if section_name not in sections:
            result["additions"].append(f"{section_name} section")

    # Check for deprecated sections still present
    for deprecated in DEPRECATED_SECTIONS:
        if deprecated in sections:
            result["removals"].append(f"{deprecated} section")

    # Check for missing last_updated in sections
    for section_name, section_data in sections.items():
        if isinstance(section_data, dict) and "last_updated" not in section_data:
            result["additions"].append(f"last_updated field in {section_name}")

    # Check quick_status for deprecated keys
    quick_status = data.get("quick_status", {})
    if isinstance(quick_status, dict):
        for dep_key in DEPRECATED_QUICK_STATUS_KEYS:
            if dep_key in quick_status:
                result["modifications"].append(f"quick_status: remove {dep_key}")

        # Check for missing required quick_status keys
        required_qs_keys = ["new_mail", "opened_mail", "active_plans", "commons_mentions", "action_required", "summary"]
        for key in required_qs_keys:
            if key not in quick_status:
                result["additions"].append(f"quick_status.{key}")

    # Determine status
    if result["additions"] or result["removals"] or result["modifications"]:
        result["status"] = "needs_update"

    return result


# =============================================================================
# PUBLIC API
# =============================================================================


def diff_dashboard_template(branch_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Compare dashboard template against branch dashboards.

    If branch_name is provided, only diff that single branch.
    Otherwise, diff all active branches from the registry.

    Args:
        branch_name: Optional uppercase branch name to filter to

    Returns:
        Dict with branches list (per-branch diffs) and summary counts
    """
    result: Dict[str, Any] = {
        "branches": [],
        "summary": {"needs_update": 0, "up_to_date": 0, "missing": 0, "invalid_json": 0},
    }

    # Load template
    if not TEMPLATE_FILE.exists():
        return {"error": f"Template file not found: {TEMPLATE_FILE}", "branches": [], "summary": {}}

    try:
        template = json.loads(TEMPLATE_FILE.read_text())
    except json.JSONDecodeError as e:
        logger.error("Invalid template JSON: %s", e)
        return {"error": f"Invalid template JSON: {e}", "branches": [], "summary": {}}

    # Load AIPASS registry
    if not AIPASS_REGISTRY.exists():
        return {"error": f"AIPASS_REGISTRY.json not found: {AIPASS_REGISTRY}", "branches": [], "summary": {}}

    try:
        registry = json.loads(AIPASS_REGISTRY.read_text())
    except json.JSONDecodeError as e:
        logger.error("Invalid registry JSON: %s", e)
        return {"error": f"Invalid registry JSON: {e}", "branches": [], "summary": {}}

    # Filter to active branches
    branches = [b for b in registry.get("branches", []) if b.get("status") == "active"]

    # If branch_name specified, filter further
    if branch_name:
        target = branch_name.upper()
        branches = [b for b in branches if b.get("name", "").upper() == target]
        if not branches:
            return {"error": f"Branch '{target}' not found in registry", "branches": [], "summary": {}}

    repo_root = _find_repo_root()

    for branch in branches:
        bname = branch.get("name", "UNKNOWN").upper()
        raw_path = Path(branch.get("path", ""))
        bpath = raw_path if raw_path.is_absolute() else repo_root / raw_path

        if not bpath.exists():
            branch_diff = {
                "branch": bname,
                "path": str(bpath),
                "additions": [],
                "removals": [],
                "modifications": [],
                "status": "missing",
            }
        else:
            branch_diff = _diff_branch(bname, bpath, template)

        result["branches"].append(branch_diff)
        status = branch_diff["status"]
        if status in result["summary"]:
            result["summary"][status] += 1

    json_handler.log_operation(
        "template_diffed",
        {
            "branch_filter": branch_name,
            "branches_scanned": len(result["branches"]),
            "needs_update": result["summary"].get("needs_update", 0),
            "up_to_date": result["summary"].get("up_to_date", 0),
        },
    )

    return result


# =============================================================================
# CLI INTERFACE
# =============================================================================

if __name__ == "__main__":
    import sys as _sys

    _out = _sys.stdout.write

    args = _sys.argv[1:]
    target_branch = None
    if args:
        target_branch = args[0]

    diff_result = diff_dashboard_template(branch_name=target_branch)

    if "error" in diff_result:
        _out(f"\nError: {diff_result['error']}\n\n")
        _sys.exit(1)

    _out("\n=== Dashboard Template Diff ===\n")
    summary = diff_result.get("summary", {})
    _out(f"Needs update: {summary.get('needs_update', 0)}\n")
    _out(f"Up to date:   {summary.get('up_to_date', 0)}\n")
    _out(f"Missing:      {summary.get('missing', 0)}\n")
    _out(f"Invalid JSON: {summary.get('invalid_json', 0)}\n")

    for branch_diff in diff_result.get("branches", []):
        status = branch_diff["status"]
        if status == "up_to_date":
            continue
        _out(f"\n  {branch_diff['branch']} ({status}):\n")
        for a in branch_diff.get("additions", []):
            _out(f"    + {a}\n")
        for r in branch_diff.get("removals", []):
            _out(f"    - {r}\n")
        for m in branch_diff.get("modifications", []):
            _out(f"    ~ {m}\n")

    _out("\n")
    _sys.exit(0)
