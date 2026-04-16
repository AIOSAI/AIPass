# =================== AIPass ====================
# Name: template_pusher.py
# Description: Dashboard Template Push Handler
# Version: 1.0.0
# Created: 2026-02-25
# Modified: 2026-03-09
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
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from aipass.prax.apps.modules.logger import get_direct_logger

logger = get_direct_logger()

from aipass.prax.apps.handlers.json import json_handler

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
VERSION_FILE = TEMPLATE_DIR / ".dashboard_version.json"
AIPASS_REGISTRY = _find_repo_root() / "AIPASS_REGISTRY.json"

# Deprecated sections to REMOVE during push
DEPRECATED_SECTIONS = ["bulletin_board", "devpulse"]

# Deprecated quick_status keys to REMOVE during push
DEPRECATED_QUICK_STATUS_KEYS = ["pending_bulletins"]

# Required sections with their default data (must match template)
REQUIRED_SECTIONS = {
    "ai_mail": {"managed_by": "ai_mail", "new": 0, "opened": 0, "total": 0, "last_updated": ""},
    "flow": {"managed_by": "flow", "active_plans": 0, "recently_closed": [], "last_updated": ""},
    "memory": {"managed_by": "memory", "vectors_stored": 0, "notes": {}, "last_updated": ""},
    "commons_activity": {
        "managed_by": "the_commons",
        "mentions": 0,
        "new_posts_since_last_visit": 0,
        "new_comments_since_last_visit": 0,
        "last_updated": "",
    },
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

    def _walk(val: Any) -> Any:
        if isinstance(val, str):
            return val.replace("{{BRANCHNAME}}", branch_name)
        elif isinstance(val, list):
            return [_walk(item) for item in val]
        elif isinstance(val, dict):
            return {k: _walk(v) for k, v in val.items()}
        return val

    result = _walk(copy.deepcopy(template))
    assert isinstance(result, dict)
    return result


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
        "summary": ", ".join(parts) if parts else "All clear",
    }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _create_from_template(template: dict, branch_name: str) -> dict:
    """Create a new dashboard from template with placeholders replaced."""
    return _replace_placeholders(template, branch_name)


def _safe_write_dashboard(
    dashboard_path: Path, data: Any, branch_name: str, dry_run: bool, result: Dict[str, Any]
) -> bool:
    """Write dashboard JSON to disk. Returns True on success, False on error."""
    if dry_run:
        return True
    try:
        content = data if isinstance(data, str) else json.dumps(data, indent=2) + "\n"
        dashboard_path.write_text(content)
        return True
    except OSError as e:
        logger.error("Failed to write dashboard for %s: %s", branch_name, e)
        result["errors"].append(f"{branch_name}: write failed: {e}")
        result["branches_skipped"] += 1
        return False


def _apply_structural_updates(data: dict, template: dict, branch_actions: List[str]) -> tuple:
    """Apply structural updates from template to existing dashboard data.

    Returns (changed: bool, branch_actions: list).
    """
    changed = False

    # Remove deprecated sections
    for section in DEPRECATED_SECTIONS:
        if section in data.get("sections", {}):
            del data["sections"][section]
            branch_actions.append(f"removed deprecated section: {section}")
            changed = True

    # Remove deprecated quick_status keys
    qs = data.get("quick_status", {})
    for key in DEPRECATED_QUICK_STATUS_KEYS:
        if key in qs:
            del qs[key]
            branch_actions.append(f"removed deprecated quick_status key: {key}")
            changed = True

    # Add missing required sections with defaults
    sections = data.setdefault("sections", {})
    for section_name, defaults in REQUIRED_SECTIONS.items():
        if section_name not in sections:
            sections[section_name] = copy.deepcopy(defaults)
            branch_actions.append(f"added missing section: {section_name}")
            changed = True

    # Update _warning header from template
    template_warning = template.get("_warning")
    if template_warning and data.get("_warning") != template_warning:
        data["_warning"] = template_warning
        branch_actions.append("updated _warning header")
        changed = True

    # Recalculate quick_status from live data
    if "sections" in data:
        new_qs = _calculate_quick_status(data["sections"])
        if data.get("quick_status") != new_qs:
            data["quick_status"] = new_qs
            changed = True

    return changed, branch_actions


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
        logger.error("Invalid template JSON: %s", e)
        result["success"] = False
        result["errors"].append(f"Invalid template JSON: {e}")
        return result

    # Load AIPASS registry
    if not AIPASS_REGISTRY.exists():
        result["success"] = False
        result["errors"].append(f"AIPASS_REGISTRY.json not found: {AIPASS_REGISTRY}")
        return result

    try:
        registry = json.loads(AIPASS_REGISTRY.read_text())
    except json.JSONDecodeError as e:
        logger.error("Invalid registry JSON: %s", e)
        result["success"] = False
        result["errors"].append(f"Invalid registry JSON: {e}")
        return result

    # Filter to active branches only
    branches = [b for b in registry.get("branches", []) if b.get("status") == "active"]
    branches_updated_list: List[str] = []

    repo_root = _find_repo_root()

    for branch in branches:
        branch_name = branch.get("name", "UNKNOWN").upper()
        raw_path = Path(branch.get("path", ""))
        branch_path = raw_path if raw_path.is_absolute() else repo_root / raw_path
        result["branches_scanned"] += 1

        if not branch_path.exists():
            result["branches_skipped"] += 1
            result["errors"].append(f"{branch_name}: branch path does not exist: {branch_path}")
            continue

        dashboard_path = branch_path / "DASHBOARD.local.json"
        branch_actions: List[str] = []

        if not dashboard_path.exists() or not dashboard_path.read_text().strip():
            label = "created from template" if not dashboard_path.exists() else "created from template (was empty)"
            new_dashboard = _create_from_template(template, branch_name)
            if not _safe_write_dashboard(dashboard_path, new_dashboard, branch_name, dry_run, result):
                continue
            branch_actions.append(label)
            result["branches_created"] += 1
            branches_updated_list.append(branch_name)
            result["changes"].append({"branch": branch_name, "actions": branch_actions})
            continue

        content = dashboard_path.read_text().strip()
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON in dashboard for %s: %s", branch_name, e)
            result["branches_skipped"] += 1
            result["errors"].append(f"{branch_name}: invalid JSON in dashboard, skipped")
            continue

        changed, branch_actions = _apply_structural_updates(data, template, branch_actions)

        if changed:
            data["last_updated"] = datetime.now().isoformat()
            if not _safe_write_dashboard(dashboard_path, data, branch_name, dry_run, result):
                continue
            result["branches_updated"] += 1
            branches_updated_list.append(branch_name)
            result["changes"].append({"branch": branch_name, "actions": branch_actions})

    # Update version file if any branches were modified
    if not dry_run and branches_updated_list:
        _update_version_file(branches_updated_list)

    json_handler.log_operation(
        "template_pushed",
        {
            "dry_run": dry_run,
            "branches_scanned": result["branches_scanned"],
            "branches_updated": result["branches_updated"],
            "branches_created": result["branches_created"],
        },
    )

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
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to update dashboard version file %s: %s", VERSION_FILE, e)
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
        "last_push_branches": [],
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
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read dashboard version file %s: %s", VERSION_FILE, e)
            status["version"] = "error reading version file"

    return status


# =============================================================================
# CLI INTERFACE
# =============================================================================

if __name__ == "__main__":
    import sys as _sys

    _out = _sys.stdout.write

    args = _sys.argv[1:]
    if not args:
        _out("Usage: drone @prax template [push|push --dry-run|status]\n\n")
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
            preview = ", ".join(pushed[:5])
            suffix = "..." if len(pushed) > 5 else ""
            _out(f"Branches pushed:   {len(pushed)} ({preview}{suffix})\n")
        _out("\n")
        _sys.exit(0)

    else:
        _out(f"Unknown command: {command}\n")
        _out("Usage: drone @prax template [push|push --dry-run|status]\n")
        _sys.exit(1)
