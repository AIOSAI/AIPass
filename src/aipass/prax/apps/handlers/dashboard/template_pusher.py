# =================== AIPass ====================
# Name: template_pusher.py
# Description: Dashboard Template Push Handler
# Version: 1.1.0
# Created: 2026-02-25
# Modified: 2026-10-17
# =============================================

"""
Dashboard Template Push Handler

Reference: docs/dashboard.md
"""

import json
import copy
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from aipass.prax.apps.modules.logger import get_direct_logger

logger = get_direct_logger()

from aipass.prax.apps.handlers.json import json_handler
from .status import calculate_quick_status, merge_quick_status
from aipass.prax.apps.handlers.repo_root import find_repo_root
from aipass.prax.apps.handlers.repo_root import resolved_file

_PRAX_ROOT = resolved_file(Path(__file__)).parents[3]  # .../prax/


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root, never reading the cwd."""
    return find_repo_root(Path(__file__))


TEMPLATE_DIR = _PRAX_ROOT / "templates"
TEMPLATE_FILE = TEMPLATE_DIR / "DASHBOARD.template.json"
VERSION_FILE = TEMPLATE_DIR / ".dashboard_version.json"
AIPASS_REGISTRY = _find_repo_root() / "AIPASS_REGISTRY.json"

DEPRECATED_SECTIONS = [
    "bulletin_board",
    "devpulse",
    "commons_activity",
    "agent_status",
    "memory_bank",
    "session",
    "todo",
]

# Deleted from every branch on push: a key belongs here only when NOBODY writes it.
# commons_mentions is live (@flow's push_branch_dashboard.py OWNED_KEYS) and stays off.
DEPRECATED_QUICK_STATUS_KEYS = ["pending_bulletins"]

# Must match templates/DASHBOARD.template.json.
REQUIRED_SECTIONS = {
    "ai_mail": {"managed_by": "ai_mail", "new": 0, "opened": 0, "total": 0, "last_updated": ""},
    "flow": {"managed_by": "flow", "active_plans": 0, "recently_closed": [], "last_updated": ""},
    "memory": {"managed_by": "memory", "vectors_stored": 0, "notes": {}, "last_updated": ""},
}


def _replace_placeholders(template: dict, branch_name: str) -> dict:
    """Recursively replace {{BRANCHNAME}} with branch_name in all string values."""

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


def _calculate_quick_status(sections: Dict, branch_path: "Path | None" = None) -> Dict:
    """Calculate quick_status from live section data."""
    # Delegate only: a local copy drifted and pushed a block without todo_count fleet-wide.
    return calculate_quick_status(sections, branch_path)


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
        dashboard_path.write_text(content, encoding="utf-8")
        return True
    except OSError as e:
        logger.error("Failed to write dashboard for %s: %s", branch_name, e)
        result["errors"].append(f"{branch_name}: write failed: {e}")
        result["branches_skipped"] += 1
        return False


def _update_spawn_template(
    spawn_path: Path, template: dict, dry_run: bool, result: Dict[str, Any], updated_list: List[str]
) -> None:
    """Apply structural updates to spawn's builder template, preserving placeholders."""
    if not spawn_path.exists():
        return
    try:
        spawn_data = json.loads(spawn_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read spawn template: %s", e)
        result["errors"].append(f"SPAWN_TEMPLATE: {e}")
        return

    spawn_actions: List[str] = []
    changed, spawn_actions = _apply_structural_updates(spawn_data, template, spawn_actions)
    if not changed:
        return

    spawn_data["branch"] = "{{BRANCHNAME}}"
    spawn_data["last_updated"] = "{{DATE}}"
    for section in spawn_data.get("sections", {}).values():
        if isinstance(section, dict) and "last_updated" in section:
            section["last_updated"] = "{{DATE}}"

    if _safe_write_dashboard(spawn_path, spawn_data, "SPAWN_TEMPLATE", dry_run, result):
        updated_list.append("SPAWN_TEMPLATE")
        result["changes"].append({"branch": "SPAWN_TEMPLATE", "actions": spawn_actions})


def _apply_structural_updates(
    data: dict, template: dict, branch_actions: List[str], branch_path: "Path | None" = None
) -> tuple:
    """Apply structural updates from template to existing dashboard data."""
    changed = False

    for section in DEPRECATED_SECTIONS:
        if section in data.get("sections", {}):
            del data["sections"][section]
            branch_actions.append(f"removed deprecated section: {section}")
            changed = True

    qs = data.get("quick_status", {})
    for key in DEPRECATED_QUICK_STATUS_KEYS:
        if key in qs:
            del qs[key]
            branch_actions.append(f"removed deprecated quick_status key: {key}")
            changed = True

    sections = data.setdefault("sections", {})
    for section_name, defaults in REQUIRED_SECTIONS.items():
        if section_name not in sections:
            sections[section_name] = copy.deepcopy(defaults)
            branch_actions.append(f"added missing section: {section_name}")
            changed = True

    template_warning = template.get("_warning")
    if template_warning and data.get("_warning") != template_warning:
        data["_warning"] = template_warning
        branch_actions.append("updated _warning header")
        changed = True

    # Merged: no writer deletes a quick_status key it did not write (shared with @flow).
    if "sections" in data:
        new_qs = merge_quick_status(data.get("quick_status"), _calculate_quick_status(data["sections"], branch_path))
        if data.get("quick_status") != new_qs:
            data["quick_status"] = new_qs
            changed = True

    return changed, branch_actions


def push_dashboard_template(dry_run: bool = False) -> Dict[str, Any]:
    """Push dashboard template to all registered branches."""
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

        changed, branch_actions = _apply_structural_updates(data, template, branch_actions, branch_path)

        if changed:
            data["last_updated"] = datetime.now().isoformat()
            if not _safe_write_dashboard(dashboard_path, data, branch_name, dry_run, result):
                continue
            result["branches_updated"] += 1
            branches_updated_list.append(branch_name)
            result["changes"].append({"branch": branch_name, "actions": branch_actions})

    spawn_template_path = repo_root / "src" / "aipass" / "spawn" / "templates" / "builder" / "DASHBOARD.local.json"
    _update_spawn_template(spawn_template_path, template, dry_run, result, branches_updated_list)

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


def _update_version_file(branches_pushed: List[str]) -> bool:
    """Update .dashboard_version.json with push timestamp and branch list."""
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
    """Get current template version and push status."""
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
