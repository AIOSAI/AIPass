# =============================================================================
# EXTRACTED FROM Dev-Pass devpulse on 2026-03-08
# Original location: aipass_os/dev_central/devpulse/apps/handlers/dashboard/template_differ.py
# These files need adaptation for AIPass before use
# Original imports use aipass_os.dev_central.devpulse — must be converted to aipass.prax
# PURPOSE: Compares dashboard template against branch dashboards to report diffs
# =============================================================================

#!/home/aipass/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: template_differ.py - Dashboard Template Diff Handler
# Date: 2026-02-25
# Version: 1.0.0
# Category: devpulse/handlers/dashboard
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-02-25): Initial version
#     * Compare dashboard template against branch dashboards
#     * Report additions, removals, and modifications per branch
#     * Support single-branch and all-branch diffing
#
# CODE STANDARDS:
#   - Handler independence: No module imports, no Prax logging
#   - Error handling: Return status dicts (3-tier architecture)
#   - File size: <300 lines target
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
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

# Infrastructure setup
AIPASS_ROOT = Path.home()
sys.path.insert(0, str(AIPASS_ROOT))

# =============================================================================
# CONSTANTS
# =============================================================================

DEVPULSE_ROOT = AIPASS_ROOT / "aipass_os" / "dev_central" / "devpulse"
TEMPLATE_DIR = DEVPULSE_ROOT / "templates"
TEMPLATE_FILE = TEMPLATE_DIR / "DASHBOARD.template.json"
BRANCH_REGISTRY = AIPASS_ROOT / "BRANCH_REGISTRY.json"

# Deprecated sections that should be flagged for removal
DEPRECATED_SECTIONS = ["bulletin_board"]

# Deprecated quick_status keys that should be flagged
DEPRECATED_QUICK_STATUS_KEYS = ["pending_bulletins"]

# Required sections (from template)
REQUIRED_SECTIONS = [
    "ai_mail", "flow", "memory_bank", "devpulse", "commons_activity"
]


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
        "status": "up_to_date"
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
    except json.JSONDecodeError:
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
    template_sections = template.get("sections", {})
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
        required_qs_keys = ["new_mail", "opened_mail", "active_plans",
                            "commons_mentions", "action_required", "summary"]
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
        "summary": {
            "needs_update": 0,
            "up_to_date": 0,
            "missing": 0,
            "invalid_json": 0
        }
    }

    # Load template
    if not TEMPLATE_FILE.exists():
        return {"error": f"Template file not found: {TEMPLATE_FILE}", "branches": [], "summary": {}}

    try:
        template = json.loads(TEMPLATE_FILE.read_text())
    except json.JSONDecodeError as e:
        return {"error": f"Invalid template JSON: {e}", "branches": [], "summary": {}}

    # Load branch registry
    if not BRANCH_REGISTRY.exists():
        return {"error": f"Branch registry not found: {BRANCH_REGISTRY}", "branches": [], "summary": {}}

    try:
        registry = json.loads(BRANCH_REGISTRY.read_text())
    except json.JSONDecodeError as e:
        return {"error": f"Invalid registry JSON: {e}", "branches": [], "summary": {}}

    # Filter to active branches
    branches = [b for b in registry.get("branches", []) if b.get("status") == "active"]

    # If branch_name specified, filter further
    if branch_name:
        target = branch_name.upper()
        branches = [b for b in branches if b.get("name", "").upper() == target]
        if not branches:
            return {
                "error": f"Branch '{target}' not found in registry",
                "branches": [],
                "summary": {}
            }

    for branch in branches:
        bname = branch.get("name", "UNKNOWN").upper()
        bpath = Path(branch.get("path", ""))

        if not bpath.exists():
            branch_diff = {
                "branch": bname,
                "path": str(bpath),
                "additions": [],
                "removals": [],
                "modifications": [],
                "status": "missing"
            }
        else:
            branch_diff = _diff_branch(bname, bpath, template)

        result["branches"].append(branch_diff)
        status = branch_diff["status"]
        if status in result["summary"]:
            result["summary"][status] += 1

    return result


# =============================================================================
# CLI INTERFACE
# =============================================================================

if __name__ == '__main__':
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
