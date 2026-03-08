# =============================================================================
# EXTRACTED FROM Dev-Pass devpulse on 2026-03-08
# Original location: aipass_os/dev_central/devpulse/apps/handlers/dashboard/template_pusher.py
# These files need adaptation for AIPass before use
# Original imports use aipass_os.dev_central.devpulse — must be converted to aipass.prax
# PURPOSE: Pushes dashboard template updates to all registered branch dashboards
# =============================================================================

#!/home/aipass/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: template_pusher.py - Dashboard Template Push Handler
# Date: 2026-02-25
# Version: 1.0.0
# Category: devpulse/handlers/dashboard
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-02-25): Initial version
#     * Push v3 dashboard template to all registered branches
#     * Remove deprecated sections (bulletin_board, pending_bulletins)
#     * Add missing sections (commons_activity)
#     * Preserve existing section data (ai_mail counts, flow plans, etc.)
#     * Dry-run mode for safe preview
#
# CODE STANDARDS:
#   - Handler independence: No module imports, no Prax logging
#   - Error handling: Return status dicts (3-tier architecture)
#   - Atomic writes: write to .tmp, rename
#   - File size: <600 lines target
# =============================================

"""
Dashboard Template Push Handler

Pushes dashboard template updates to ALL registered branch dashboards.
Updates structural elements (sections, _warning header, quick_status keys)
without overwriting existing service data (ai_mail counts, flow plans, etc.).

Purpose:
    When the dashboard schema evolves (new sections, deprecated sections,
    schema bumps), this handler propagates those structural changes
    system-wide while preserving each branch's live service data.

Independence:
    Reads template and registry directly. No service or module dependencies.
    Quick status calculation is self-contained (copied logic, not imported).
"""

import json
import copy
import sys
from pathlib import Path
from datetime import datetime
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
VERSION_FILE = TEMPLATE_DIR / ".dashboard_version.json"
BRANCH_REGISTRY = AIPASS_ROOT / "BRANCH_REGISTRY.json"

# Deprecated sections to REMOVE during push
DEPRECATED_SECTIONS = ["bulletin_board"]

# Deprecated quick_status keys to REMOVE during push
DEPRECATED_QUICK_STATUS_KEYS = ["pending_bulletins"]

# Required sections with their default data (must match template)
REQUIRED_SECTIONS = {
    "ai_mail": {
        "managed_by": "ai_mail",
        "new": 0,
        "opened": 0,
        "total": 0,
        "last_updated": ""
    },
    "flow": {
        "managed_by": "flow",
        "active_plans": 0,
        "recently_closed": [],
        "last_updated": ""
    },
    "memory_bank": {
        "managed_by": "memory_bank",
        "vectors_stored": 0,
        "notes": {},
        "last_updated": ""
    },
    "devpulse": {
        "managed_by": "devpulse",
        "summary": {},
        "last_updated": ""
    },
    "commons_activity": {
        "managed_by": "the_commons",
        "mentions": 0,
        "new_posts_since_last_visit": 0,
        "new_comments_since_last_visit": 0,
        "last_updated": ""
    }
}


# =============================================================================
# PLACEHOLDER REPLACEMENT
# =============================================================================

def _replace_placeholders(template: dict, branch_name: str) -> dict:
    """
    Recursively replace {{BRANCHNAME}} with branch_name in all string values.

    Args:
        template: Template dict with placeholder strings
        branch_name: Uppercase branch name to substitute

    Returns:
        New dict with placeholders replaced
    """
    def _walk(val):
        if isinstance(val, str):
            return val.replace("{{BRANCHNAME}}", branch_name)
        elif isinstance(val, list):
            return [_walk(item) for item in val]
        elif isinstance(val, dict):
            return {k: _walk(v) for k, v in val.items()}
        return val

    return _walk(copy.deepcopy(template))


# =============================================================================
# QUICK STATUS CALCULATION (SELF-CONTAINED)
# =============================================================================

def _calculate_quick_status(sections: Dict) -> Dict:
    """
    Calculate quick_status from live section data.

    Self-contained version (same logic as operations.py but independent).
    Reads directly from section fields. No external imports.

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
    active_plans_raw = flow.get("active_plans", 0)
    # Handle active_plans being a list (some branches store plan list) or int
    active_plans = len(active_plans_raw) if isinstance(active_plans_raw, list) else int(active_plans_raw or 0)
    mentions = commons.get("mentions", 0)

    # Ensure numeric types for comparisons
    new_mail = int(new_mail or 0)
    opened_mail = int(opened_mail or 0)
    mentions = int(mentions or 0)

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


# =============================================================================
# MAIN PUSH FUNCTION
# =============================================================================

def push_dashboard_template(dry_run: bool = False) -> Dict[str, Any]:
    """
    Push dashboard template to all registered branches.

    Updates structural elements (sections, _warning, quick_status keys)
    without overwriting existing service data. Removes deprecated sections.
    Adds missing required sections with defaults.

    Args:
        dry_run: If True, report what would change without writing files

    Returns:
        Dict with success, dry_run, branches_scanned, branches_updated,
        branches_created, branches_skipped, changes list, and errors list
    """
    result: Dict[str, Any] = {
        "success": True,
        "dry_run": dry_run,
        "branches_scanned": 0,
        "branches_updated": 0,
        "branches_created": 0,
        "branches_skipped": 0,
        "changes": [],
        "errors": [],
    }

    # Load template
    if not TEMPLATE_FILE.exists():
        result["success"] = False
        result["errors"].append(f"Template file not found: {TEMPLATE_FILE}")
        return result

    try:
        template = json.loads(TEMPLATE_FILE.read_text())
    except json.JSONDecodeError as e:
        result["success"] = False
        result["errors"].append(f"Invalid template JSON: {e}")
        return result

    # Load branch registry
    if not BRANCH_REGISTRY.exists():
        result["success"] = False
        result["errors"].append(f"Branch registry not found: {BRANCH_REGISTRY}")
        return result

    try:
        registry = json.loads(BRANCH_REGISTRY.read_text())
    except json.JSONDecodeError as e:
        result["success"] = False
        result["errors"].append(f"Invalid registry JSON: {e}")
        return result

    # Filter to active branches only
    branches = [b for b in registry.get("branches", []) if b.get("status") == "active"]
    branches_updated_list: List[str] = []

    for branch in branches:
        branch_name = branch.get("name", "UNKNOWN").upper()
        branch_path = Path(branch.get("path", ""))
        result["branches_scanned"] += 1

        if not branch_path.exists():
            result["branches_skipped"] += 1
            result["errors"].append(f"{branch_name}: branch path does not exist: {branch_path}")
            continue

        dashboard_path = branch_path / "DASHBOARD.local.json"
        branch_actions: List[str] = []

        if not dashboard_path.exists():
            # Create from template
            new_dashboard = _replace_placeholders(template, branch_name)
            new_dashboard["last_updated"] = datetime.now().isoformat()
            # Recalculate quick_status for the new dashboard
            new_dashboard["quick_status"] = _calculate_quick_status(
                new_dashboard.get("sections", {})
            )

            if not dry_run:
                try:
                    tmp_path = dashboard_path.with_suffix(".tmp")
                    tmp_path.write_text(json.dumps(new_dashboard, indent=2))
                    tmp_path.rename(dashboard_path)
                except OSError as e:
                    result["errors"].append(f"{branch_name}: failed to create dashboard: {e}")
                    result["branches_skipped"] += 1
                    continue

            branch_actions.append("created from template")
            result["branches_created"] += 1
            branches_updated_list.append(branch_name)
            result["changes"].append({"branch": branch_name, "actions": branch_actions})
            continue

        # File exists -- load and update
        content = dashboard_path.read_text().strip()
        if not content:
            # Empty file -- treat as new
            new_dashboard = _replace_placeholders(template, branch_name)
            new_dashboard["last_updated"] = datetime.now().isoformat()
            new_dashboard["quick_status"] = _calculate_quick_status(
                new_dashboard.get("sections", {})
            )

            if not dry_run:
                try:
                    tmp_path = dashboard_path.with_suffix(".tmp")
                    tmp_path.write_text(json.dumps(new_dashboard, indent=2))
                    tmp_path.rename(dashboard_path)
                except OSError as e:
                    result["errors"].append(f"{branch_name}: failed to write dashboard: {e}")
                    result["branches_skipped"] += 1
                    continue

            branch_actions.append("created from template (was empty)")
            result["branches_created"] += 1
            branches_updated_list.append(branch_name)
            result["changes"].append({"branch": branch_name, "actions": branch_actions})
            continue

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            result["branches_skipped"] += 1
            result["errors"].append(f"{branch_name}: invalid JSON in dashboard, skipped")
            continue

        # --- Structural updates (preserve existing data) ---
        changed = False

        # Ensure _warning header exists
        if "_warning" not in data:
            data["_warning"] = template.get("_warning", "")
            branch_actions.append("added _warning header")
            changed = True

        # Ensure sections dict exists
        if "sections" not in data:
            data["sections"] = {}
            branch_actions.append("added sections dict")
            changed = True

        # Add missing required sections (with defaults)
        for section_name, section_defaults in REQUIRED_SECTIONS.items():
            if section_name not in data["sections"]:
                data["sections"][section_name] = copy.deepcopy(section_defaults)
                branch_actions.append(f"added {section_name} section")
                changed = True

        # Remove deprecated sections
        for deprecated in DEPRECATED_SECTIONS:
            if deprecated in data.get("sections", {}):
                del data["sections"][deprecated]
                branch_actions.append(f"removed {deprecated} section")
                changed = True

        # Ensure last_updated field on every section
        for section_name, section_data in data.get("sections", {}).items():
            if isinstance(section_data, dict) and "last_updated" not in section_data:
                section_data["last_updated"] = ""
                branch_actions.append(f"added last_updated to {section_name}")
                changed = True

        # Remove deprecated quick_status keys
        quick_status = data.get("quick_status", {})
        if isinstance(quick_status, dict):
            for dep_key in DEPRECATED_QUICK_STATUS_KEYS:
                if dep_key in quick_status:
                    del quick_status[dep_key]
                    branch_actions.append(f"removed quick_status.{dep_key}")
                    changed = True

        # Recalculate quick_status from live section data
        new_quick_status = _calculate_quick_status(data.get("sections", {}))
        if data.get("quick_status") != new_quick_status:
            data["quick_status"] = new_quick_status
            if not changed:
                # Only note if no other changes triggered this
                branch_actions.append("recalculated quick_status")
            changed = True

        if changed:
            data["last_updated"] = datetime.now().isoformat()

            if not dry_run:
                try:
                    tmp_path = dashboard_path.with_suffix(".tmp")
                    tmp_path.write_text(json.dumps(data, indent=2))
                    tmp_path.rename(dashboard_path)
                except OSError as e:
                    result["errors"].append(f"{branch_name}: failed to write dashboard: {e}")
                    result["branches_skipped"] += 1
                    continue

            result["branches_updated"] += 1
            branches_updated_list.append(branch_name)
            result["changes"].append({"branch": branch_name, "actions": branch_actions})

    # Update version file if any branches were modified
    if not dry_run and branches_updated_list:
        _update_version_file(branches_updated_list)

    return result


# =============================================================================
# VERSION TRACKING
# =============================================================================

def _update_version_file(branches_pushed: List[str]) -> bool:
    """
    Update .dashboard_version.json with push timestamp and branch list.

    Args:
        branches_pushed: List of branch names that were updated

    Returns:
        True if version file updated successfully, False on error
    """
    try:
        version_data: Dict[str, Any] = {}
        if VERSION_FILE.exists():
            version_data = json.loads(VERSION_FILE.read_text())

        version_data["last_push"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        version_data["last_push_branches"] = branches_pushed

        VERSION_FILE.write_text(json.dumps(version_data, indent=2) + "\n")
        return True
    except (json.JSONDecodeError, OSError):
        return False


def get_template_status() -> Dict[str, Any]:
    """
    Get current template version and push status.

    Reads the .dashboard_version.json file and returns its contents
    along with template file existence checks.

    Returns:
        Dict with version info, last push timestamp, template existence
    """
    status: Dict[str, Any] = {
        "version_file": str(VERSION_FILE),
        "templates_dir": str(TEMPLATE_DIR),
        "template_exists": TEMPLATE_FILE.exists(),
        "version": None,
        "last_updated": None,
        "updated_by": None,
        "changes": [],
        "last_push": None,
        "last_push_branches": []
    }

    if VERSION_FILE.exists():
        try:
            data = json.loads(VERSION_FILE.read_text())
            status["version"] = data.get("version")
            status["last_updated"] = data.get("last_updated")
            status["updated_by"] = data.get("updated_by")
            status["changes"] = data.get("changes", [])
            status["last_push"] = data.get("last_push")
            status["last_push_branches"] = data.get("last_push_branches", [])
        except (json.JSONDecodeError, OSError):
            status["version"] = "error reading version file"

    return status


# =============================================================================
# CLI INTERFACE
# =============================================================================

if __name__ == '__main__':
    import sys as _sys
    _out = _sys.stdout.write

    args = _sys.argv[1:]
    if not args:
        _out("Usage: python3 template_pusher.py [push|push --dry-run|status]\n\n")
        _out("Commands:\n")
        _out("  push           Push template updates to all branches\n")
        _out("  push --dry-run Preview changes without writing\n")
        _out("  status         Show template version and last push info\n")
        _sys.exit(1)

    command = args[0]

    if command == "push":
        dry_run = "--dry-run" in args
        push_result = push_dashboard_template(dry_run=dry_run)
        mode = "DRY RUN" if push_result.get("dry_run") else "PUSH"
        _out(f"\n=== Dashboard Template {mode} Results ===\n")
        _out(f"Branches scanned:  {push_result['branches_scanned']}\n")
        _out(f"Branches updated:  {push_result['branches_updated']}\n")
        _out(f"Branches created:  {push_result['branches_created']}\n")
        _out(f"Branches skipped:  {push_result['branches_skipped']}\n")
        if push_result["changes"]:
            _out(f"\nChanges ({len(push_result['changes'])} branches):\n")
            for entry in push_result["changes"]:
                _out(f"\n  {entry['branch']}:\n")
                for action in entry["actions"]:
                    _out(f"    - {action}\n")
        if push_result["errors"]:
            _out(f"\nErrors ({len(push_result['errors'])}):\n")
            for err in push_result["errors"]:
                _out(f"  ! {err}\n")
        if not push_result["changes"] and not push_result["errors"]:
            _out("\nAll branches are up to date with template.\n")
        _out("\n")
        _sys.exit(0 if push_result["success"] else 1)

    elif command == "status":
        tmpl_status = get_template_status()
        _out("\n=== Dashboard Template Status ===\n")
        _out(f"Templates dir:     {tmpl_status['templates_dir']}\n")
        _out(f"Template file:     {'found' if tmpl_status['template_exists'] else 'MISSING'}\n")
        _out(f"Schema version:    {tmpl_status.get('version', 'unknown')}\n")
        _out(f"Last push:         {tmpl_status.get('last_push', 'never')}\n")
        pushed = tmpl_status.get("last_push_branches", [])
        if pushed:
            preview = ', '.join(pushed[:5])
            suffix = '...' if len(pushed) > 5 else ''
            _out(f"Branches pushed:   {len(pushed)} ({preview}{suffix})\n")
        _out("\n")
        _sys.exit(0)

    else:
        _out(f"Unknown command: {command}\n")
        _out("Usage: python3 template_pusher.py [push|push --dry-run|status]\n")
        _sys.exit(1)
