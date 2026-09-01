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
from datetime import datetime, timedelta, timezone
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
from aipass.prax.apps.handlers.repo_root import find_repo_root

# Sections managed by the refresh path — everything else is write-through only
REFRESH_MANAGED_SECTIONS = {"ai_mail", "flow", "memory"}


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root, never reading the cwd.

    Delegates to ``handlers/repo_root.py``. Prax carried eight private copies of
    this walk, every one ending ``return Path.cwd()`` — @memory reported the
    consequence with a traceback on 2026-08-31: the walk runs at IMPORT time in
    most of the fleet, so a deleted working directory crashed the import, and a
    registry-less checkout (every clean CI clone) resolved against wherever the
    shell stood.
    """
    return find_repo_root(Path(__file__))


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


# @flow's section contract, their module 2.0.0 (Patrick's ruling, 2026-08-16).
# Mirrors flow/apps/handlers/dashboard/push_branch_dashboard.py::_build_section_data —
# sections.flow has two writers and both assign it wholesale, so a shape either
# side does not build is a shape the other side silently deletes.
OPEN_RECENT_LIMIT = 5
RECENTLY_CLOSED_LIMIT = 5

# How recently a plan must have closed to appear. @flow's push applies the same
# 7-day window (push_branch_dashboard.py::_filter_branch_plans); without it a prax
# refresh republishes closures their push had already aged out.
CLOSED_WINDOW_DAYS = 7

# Contract keys prax has no honest source for. The only per-branch closed number
# in PLANS.central.json is `branches.<name>.statistics.total_closed`, and that is
# a truncation artifact: @flow's aggregate feeds the already-capped 5-entry
# recently_closed list back in as the closed universe, so all 44 branches reported
# <= 5 when measured (a branch with 104 closed plans said 5). prax carries @flow's
# value through instead of deriving a number it knows to be wrong.
FLOW_KEYS_PRAX_CANNOT_SOURCE = ("total_plans",)


def _find_branch_block(plans_data: Dict, branch_name: str) -> Dict:
    """Locate one branch's own block in the central file.

    ``branches.<name>`` carries that branch's plans; the top-level arrays are the
    FLEET-WIDE roll-up. Reading the roll-up is how every dashboard came to publish
    other branches' closed plans.
    """
    branches = plans_data.get("branches", {})
    if not isinstance(branches, dict):
        return {}

    target = branch_name.lower()
    for key, block in branches.items():
        if not isinstance(block, dict):
            continue
        if key.lower() == target or str(block.get("branch_name", "")).lower() == target:
            return block
    return {}


def _branch_plan_rows(plans_data: Dict, branch_name: str) -> tuple:
    """Return this branch's (open, closed) plan rows — never the fleet's.

    Falls back to filtering the roll-up when the branch has no block of its own,
    which still filters by branch rather than publishing everyone's rows.
    """
    block = _find_branch_block(plans_data, branch_name)
    if block:
        return (block.get("active_plans") or [], block.get("recently_closed") or [])

    target = branch_name.lower()

    def mine(rows: List) -> List:
        """Keep only the rows this branch owns."""
        return [p for p in rows if str(p.get("branch", "")).lower() == target]

    return (mine(plans_data.get("active_plans") or []), mine(plans_data.get("recently_closed") or []))


def _build_open_recent(open_rows: List[Dict]) -> List[Dict]:
    """The bounded window of newest open plans, newest first.

    Byte-identical to @flow's ``_build_open_recent``: the cap lives in the writer,
    not the reader, and plans with no ``created`` sort last instead of raising.
    """
    newest_first = sorted(open_rows, key=lambda p: p.get("created") or "", reverse=True)
    return [
        {
            "plan_id": plan.get("plan_id", ""),
            "subject": plan.get("subject", ""),
            "created": plan.get("created", ""),
        }
        for plan in newest_first[:OPEN_RECENT_LIMIT]
    ]


def _within_closed_window(plan: Dict, cutoff: datetime) -> bool:
    """Whether a closed plan is recent enough to publish.

    Mirrors @flow's ``_filter_branch_plans`` decision by decision: no timestamp
    means it never ships, an unparseable one ships anyway rather than vanishing.
    """
    closed_ts = plan.get("closed", "")
    if not closed_ts:
        return False
    try:
        return datetime.fromisoformat(closed_ts) >= cutoff
    except (ValueError, TypeError) as exc:
        logger.warning(
            "Unparseable closed timestamp '%s' for plan %s, including anyway: %s",
            closed_ts,
            plan.get("plan_id", ""),
            exc,
        )
        return True


def _build_recently_closed(closed_rows: List[Dict]) -> List[Dict]:
    """Newest-first closed window in @flow's entry shape: {id, subject, closed}.

    prax used to publish ``{plan_id, subject}`` here — the key naming a plan
    changed depending on which service wrote the section last — and applied no age
    window at all, so a refresh republished closures @flow's push had already aged
    out. Live proof on 2026-08-16: @api's card went from 2 entries to 5, the oldest
    from May, purely by changing writer.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=CLOSED_WINDOW_DAYS)
    recent = [plan for plan in closed_rows if _within_closed_window(plan, cutoff)]
    newest_first = sorted(recent, key=lambda p: p.get("closed") or "", reverse=True)
    return [
        {
            "id": plan.get("plan_id", ""),
            "subject": plan.get("subject", ""),
            "closed": plan.get("closed", ""),
        }
        for plan in newest_first[:RECENTLY_CLOSED_LIMIT]
    ]


def _extract_flow_section(centrals: Dict, branch_name: str, existing: "Dict | None" = None) -> Dict:
    """Build the flow section from PLANS.central.json in @flow's five-key shape.

    Args:
        centrals: All central files as read by read_all_centrals()
        branch_name: Uppercase branch name (central keys are lowercase)
        existing: The flow section already on disk, for the keys prax cannot source

    Returns:
        Section dict matching @flow's published contract
    """
    carried = {key: (existing or {}).get(key, 0) for key in FLOW_KEYS_PRAX_CANNOT_SOURCE}

    plans_data = centrals.get("plans")
    if not plans_data:
        return {
            "managed_by": "flow",
            "active_plans": 0,
            "open_recent": [],
            "recently_closed": [],
            **carried,
        }

    open_rows, closed_rows = _branch_plan_rows(plans_data, branch_name)

    return {
        "managed_by": "flow",
        "active_plans": len(open_rows),
        "open_recent": _build_open_recent(open_rows),
        "recently_closed": _build_recently_closed(closed_rows),
        **carried,
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


def _read_existing_section(branch_path: Path, name: str) -> Dict:
    """Read one section off the dashboard already on disk.

    The refresh path rebuilds each dashboard from the template, so a section's
    previous contents are gone before it can be consulted. Sections owned by
    another service can carry keys prax has no source for.
    """
    dashboard_path = Path(branch_path) / "DASHBOARD.local.json"
    if not dashboard_path.exists():
        return {}
    try:
        data = json.loads(dashboard_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "Could not read the existing dashboard at %s (%s), so the '%s' section's "
            "foreign keys cannot be carried forward on this refresh.",
            dashboard_path,
            type(exc).__name__,
            name,
        )
        return {}
    section = data.get("sections", {}).get(name, {})
    return section if isinstance(section, dict) else {}


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
            # Read @flow's section before the template rebuild drops it — it holds
            # keys prax cannot source and must not delete.
            existing_flow = _read_existing_section(branch_path, "flow")

            # Create fresh dashboard
            dashboard = create_fresh_dashboard(branch_path)

            # Populate sections from centrals
            dashboard["sections"]["ai_mail"] = _extract_ai_mail_section(centrals, branch_name)
            dashboard["sections"]["flow"] = _extract_flow_section(centrals, branch_name, existing_flow)
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
        existing_flow = _read_existing_section(branch_path, "flow")

        dashboard = create_fresh_dashboard(branch_path)

        dashboard["sections"]["ai_mail"] = _extract_ai_mail_section(centrals, branch_name)
        dashboard["sections"]["flow"] = _extract_flow_section(centrals, branch_name, existing_flow)
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
