# =================== AIPass ====================
# Name: operations.py
# Description: Dashboard Operations Handler
# Version: 0.5.0
# Created: 2026-02-25
# Modified: 2026-10-17
# =============================================

"""Dashboard Operations Handler"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict

from aipass.prax.apps.modules.logger import get_direct_logger

logger = get_direct_logger()

from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.repo_root import resolved_file

_PRAX_ROOT = resolved_file(Path(__file__)).parents[3]  # .../prax/

# The one copy of the dashboard caps, in chars (len()); other branches import them
# via aipass.prax.apps.modules.dashboard. Reference: docs/dashboard_caps.md
SUBJECT_CAP = 120

DASHBOARD_CHAR_BUDGET = 6000

# Counted inside SUBJECT_CAP, never added to it.
TRUNCATION_MARKER = "..."


def cap_subject(text: str) -> str:
    """The first line of ``text``, cut to SUBJECT_CAP chars, marker included."""
    # Truncate, never refuse: a refused subject drops the plan from the glance.
    stripped = (text or "").strip()
    if not stripped:
        return ""
    first = stripped.splitlines()[0].strip()
    if len(first) <= SUBJECT_CAP:
        return first
    return first[: SUBJECT_CAP - len(TRUNCATION_MARKER)].rstrip() + TRUNCATION_MARKER


def get_dashboard_path(branch_path: Path) -> Path:
    """Get DASHBOARD.local.json path for a branch"""
    return branch_path / "DASHBOARD.local.json"


def load_dashboard(branch_path: Path, template: Dict) -> Dict:
    """Load branch dashboard, creating if needed"""
    dashboard_path = get_dashboard_path(branch_path)

    if dashboard_path.exists():
        content = dashboard_path.read_text().strip()
        # Empty file: a concurrent writer may be mid-write.
        if not content:
            new_dashboard = template.copy()
            new_dashboard["branch"] = branch_path.name.upper()
            return new_dashboard
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning("Corrupted dashboard JSON for %s, recreating from template: %s", branch_path.name, e)
            new_dashboard = template.copy()
            new_dashboard["branch"] = branch_path.name.upper()
            return new_dashboard
        if not isinstance(data, dict):
            logger.warning("Dashboard JSON for %s is not a dict, recreating from template", branch_path.name)
            new_dashboard = template.copy()
            new_dashboard["branch"] = branch_path.name.upper()
            return new_dashboard
        if "sections" not in data:
            data["sections"] = template["sections"].copy()
        return data

    new_dashboard = template.copy()
    new_dashboard["branch"] = branch_path.name.upper()
    return new_dashboard


def save_dashboard(branch_path: Path, data: Dict) -> bool:
    """Save branch dashboard"""
    data["last_updated"] = datetime.now().isoformat()
    dashboard_path = get_dashboard_path(branch_path)
    rendered = json.dumps(data, indent=2)
    if len(rendered) > DASHBOARD_CHAR_BUDGET:
        # Warn, never refuse or trim: a refused save leaves a stale dashboard,
        # which misreports mail counts on the next greeting.
        logger.warning(
            "Dashboard for %s is %d chars, over the %d budget — every greeting on that branch pays it",
            branch_path.name,
            len(rendered),
            DASHBOARD_CHAR_BUDGET,
        )
    dashboard_path.write_text(rendered)
    return True


def create_fresh_dashboard(branch_path: Path) -> Dict:
    """Create fresh dashboard with clean structure - NO preservation."""
    template_file = _PRAX_ROOT / "templates" / "DASHBOARD.template.json"
    if template_file.exists():
        try:
            template = json.loads(template_file.read_text())
            now = datetime.now().isoformat()
            dashboard = json.loads(json.dumps(template).replace("{{BRANCHNAME}}", branch_path.name.upper()))
            dashboard["last_updated"] = now
            return dashboard
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load dashboard template file %s, falling back to hardcoded: %s", template_file, e)

    now = datetime.now().isoformat()
    return {
        "_warning": (
            "AUTO-GENERATED FILE - DO NOT MANUALLY EDIT."
            " This file is 100% automated and will be overwritten."
            " Services update their own sections."
        ),
        "branch": branch_path.name.upper(),
        "last_updated": now,
        "quick_status": {"action_required": False},
        "sections": {
            "ai_mail": {"managed_by": "ai_mail", "new": 0, "opened": 0, "total": 0, "last_updated": ""},
            "flow": {"managed_by": "flow", "active_plans": 0, "recently_closed": [], "last_updated": ""},
            "memory": {"managed_by": "memory", "vectors_stored": 0, "notes": {}, "last_updated": ""},
        },
    }


def update_section(
    branch_path: Path, section_name: str, section_data: Dict, template: Dict, calculate_status_func
) -> bool:
    """Update a specific section in branch dashboard (legacy interface)."""
    dashboard = load_dashboard(branch_path, template)

    if "sections" not in dashboard:
        dashboard["sections"] = {}

    section_data["last_updated"] = datetime.now().isoformat()
    dashboard["sections"][section_name] = section_data

    # Merged, so this write cannot delete another service's key (e.g. @flow's commons_mentions).
    from .status import merge_quick_status

    dashboard["quick_status"] = merge_quick_status(
        dashboard.get("quick_status"), calculate_status_func(dashboard["sections"], branch_path)
    )

    return save_dashboard(branch_path, dashboard)


def _calculate_quick_status_standalone(sections: Dict, branch_path: Path) -> Dict:
    """Calculate quick_status from branch data sources."""
    # Delegate only: separate copies of this logic drift (one lost the list-shape guard).
    from .status import calculate_quick_status

    return calculate_quick_status(sections, branch_path)


def _load_or_create_dashboard(dashboard_path: Path, branch_path: Path) -> Dict:
    """Load existing dashboard JSON or create from template."""
    if not dashboard_path.exists():
        return create_fresh_dashboard(branch_path)
    content = dashboard_path.read_text(encoding="utf-8").strip()
    if not content:
        return create_fresh_dashboard(branch_path)
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning("Corrupted dashboard JSON at %s, creating fresh: %s", dashboard_path, e)
        return create_fresh_dashboard(branch_path)


def write_section(branch_path: Path, section_name: str, section_data: Dict) -> bool:
    """Write-through API: update a single section in a branch's dashboard."""
    # Called from every branch: keep it free of ai_mail/flow imports.
    try:
        branch_path = Path(branch_path)
        dashboard_path = get_dashboard_path(branch_path)

        dashboard = _load_or_create_dashboard(dashboard_path, branch_path)

        if "sections" not in dashboard:
            dashboard["sections"] = {}

        section_data["last_updated"] = datetime.now().isoformat()

        dashboard["sections"][section_name] = section_data

        # Merged, so a write-through caller cannot delete a key another service owns.
        from .status import merge_quick_status

        dashboard["quick_status"] = merge_quick_status(
            dashboard.get("quick_status"),
            _calculate_quick_status_standalone(dashboard["sections"], branch_path),
        )

        saved = save_dashboard(branch_path, dashboard)

        json_handler.log_operation(
            "section_updated",
            {
                "section": section_name,
                "branch": branch_path.name,
            },
        )

        return saved

    except Exception as e:
        logger.error("Failed to write section '%s' for branch %s: %s", section_name, branch_path.name, e)
        return False
