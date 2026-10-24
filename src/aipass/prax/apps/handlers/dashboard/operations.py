# =================== AIPass ====================
# Name: operations.py
# Description: Dashboard Operations Handler
# Version: 0.6.0
# Created: 2026-02-25
# Modified: 2026-10-23
# =============================================

"""Dashboard Operations Handler"""

import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator

try:
    import fcntl
except ImportError:  # Windows: no advisory lock, the atomic replace still holds
    fcntl = None  # type: ignore[assignment]

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


@contextmanager
def dashboard_lock(branch_path: Path) -> Iterator[None]:
    """Hold the sidecar lock every prax read-modify-write of a branch dashboard takes."""
    # flock is per open file: never nest two dashboard_lock() on one branch in one process.
    if fcntl is None:
        yield
        return
    lock_path = get_dashboard_path(branch_path).with_name("DASHBOARD.local.json.lock")
    with open(lock_path, "a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_write_text(path: Path, text: str) -> None:
    """Write text so a reader sees the old file or the new one, never half of either."""
    # Unique name: @flow stages its own writes as DASHBOARD.local.tmp in the same directory.
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".prax.tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(tmp_name, 0o644)
    os.replace(tmp_name, path)


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
    atomic_write_text(dashboard_path, rendered)
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
            "flow": {"managed_by": "flow", "active_plans": 0, "recently_closed": [], "last_updated": ""},
            "memory": {"managed_by": "memory", "vectors_stored": 0, "notes": {}, "last_updated": ""},
        },
    }


def _load_for_write(dashboard_path: Path, branch_path: Path) -> "Dict | None":
    """The dashboard on disk, a fresh one when there is none, or None when it is unreadable."""
    # None, never a template rebuild: saving a rebuild wipes every other service's sections.
    if not dashboard_path.exists():
        return create_fresh_dashboard(branch_path)
    try:
        data = json.loads(dashboard_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Dashboard at %s is unreadable, refusing to overwrite it: %s", dashboard_path, e)
        return None
    if not isinstance(data, dict):
        logger.error("Dashboard at %s is not a JSON object, refusing to overwrite it", dashboard_path)
        return None
    return data


def write_section(branch_path: Path, section_name: str, section_data: Dict) -> bool:
    """Write-through API: update a single section in a branch's dashboard."""
    # Called from every branch: keep it free of ai_mail/flow imports.
    try:
        branch_path = Path(branch_path)
        dashboard_path = get_dashboard_path(branch_path)

        with dashboard_lock(branch_path):
            dashboard = _load_for_write(dashboard_path, branch_path)
            if dashboard is None:
                return False

            if not isinstance(dashboard.get("sections"), dict):
                dashboard["sections"] = {}

            section_data["last_updated"] = datetime.now().isoformat()

            dashboard["sections"][section_name] = section_data

            # Merged, so a write-through caller cannot delete a key another service owns.
            from .status import calculate_quick_status, merge_quick_status

            dashboard["quick_status"] = merge_quick_status(
                dashboard.get("quick_status"),
                calculate_quick_status(dashboard["sections"], branch_path),
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
