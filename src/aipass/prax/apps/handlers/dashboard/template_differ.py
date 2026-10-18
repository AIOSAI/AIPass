# =================== AIPass ====================
# Name: template_differ.py
# Description: Dashboard Template Diff Handler
# Version: 1.2.0
# Created: 2026-02-25
# Modified: 2026-10-17
# =============================================

"""
Dashboard Template Diff Handler

Reference: docs/dashboard.md
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional

from aipass.prax.apps.modules.logger import get_direct_logger

from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.repo_root import find_repo_root
from aipass.prax.apps.handlers.repo_root import resolved_file
from aipass.prax.apps.handlers.dashboard.template_pusher import DEPRECATED_QUICK_STATUS_KEYS

logger = get_direct_logger()

_PRAX_ROOT = resolved_file(Path(__file__)).parents[3]  # .../prax/


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root, never reading the cwd."""
    return find_repo_root(Path(__file__))


TEMPLATE_DIR = _PRAX_ROOT / "templates"
TEMPLATE_FILE = TEMPLATE_DIR / "DASHBOARD.template.json"
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

# DEPRECATED_QUICK_STATUS_KEYS is imported from the pusher: a local copy drifts and
# recommends deleting live keys. These two are only the fallback when the template says nothing.
REQUIRED_SECTIONS = ["ai_mail", "flow", "memory"]
REQUIRED_QUICK_STATUS_KEYS = ["new_mail", "opened_mail", "active_plans", "action_required", "summary"]


def _diff_branch(branch_name: str, branch_path: Path, template: dict) -> Dict[str, Any]:
    """Compare a single branch's dashboard against the template."""
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

    if "_warning" not in data:
        result["additions"].append("_warning header")

    sections = data.get("sections", {})
    if not isinstance(sections, dict):
        result["additions"].append("sections dict (missing or invalid)")
        result["status"] = "needs_update"
        return result

    for section_name in template.get("sections") or REQUIRED_SECTIONS:
        if section_name not in sections:
            result["additions"].append(f"{section_name} section")

    for deprecated in DEPRECATED_SECTIONS:
        if deprecated in sections:
            result["removals"].append(f"{deprecated} section")

    for section_name, section_data in sections.items():
        if isinstance(section_data, dict) and "last_updated" not in section_data:
            result["additions"].append(f"last_updated field in {section_name}")

    quick_status = data.get("quick_status", {})
    if isinstance(quick_status, dict):
        for dep_key in DEPRECATED_QUICK_STATUS_KEYS:
            if dep_key in quick_status:
                result["modifications"].append(f"quick_status: remove {dep_key}")

        for key in template.get("quick_status") or REQUIRED_QUICK_STATUS_KEYS:
            if key not in quick_status:
                result["additions"].append(f"quick_status.{key}")

    if result["additions"] or result["removals"] or result["modifications"]:
        result["status"] = "needs_update"

    return result


def diff_dashboard_template(branch_name: Optional[str] = None) -> Dict[str, Any]:
    """Compare dashboard template against branch dashboards."""
    result: Dict[str, Any] = {
        "branches": [],
        "summary": {"needs_update": 0, "up_to_date": 0, "missing": 0, "invalid_json": 0},
    }

    if not TEMPLATE_FILE.exists():
        return {"error": f"Template file not found: {TEMPLATE_FILE}", "branches": [], "summary": {}}

    try:
        template = json.loads(TEMPLATE_FILE.read_text())
    except json.JSONDecodeError as e:
        logger.error("Invalid template JSON: %s", e)
        return {"error": f"Invalid template JSON: {e}", "branches": [], "summary": {}}

    if not AIPASS_REGISTRY.exists():
        return {"error": f"AIPASS_REGISTRY.json not found: {AIPASS_REGISTRY}", "branches": [], "summary": {}}

    try:
        registry = json.loads(AIPASS_REGISTRY.read_text())
    except json.JSONDecodeError as e:
        logger.error("Invalid registry JSON: %s", e)
        return {"error": f"Invalid registry JSON: {e}", "branches": [], "summary": {}}

    branches = [b for b in registry.get("branches", []) if b.get("status") == "active"]

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
