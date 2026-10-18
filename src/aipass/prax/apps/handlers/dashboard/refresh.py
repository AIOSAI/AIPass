# =================== AIPass ====================
# Name: refresh.py
# Description: Dashboard Refresh Handler
# Version: 0.7.0
# Created: 2026-02-25
# Modified: 2026-10-17
# =============================================

"""Dashboard Refresh Handler

AIPASS owns all dashboards; services only maintain their central files.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from aipass.prax.apps.modules.logger import get_direct_logger

from .operations import cap_subject, create_fresh_dashboard, save_dashboard
from .status import calculate_quick_status, merge_quick_status, read_existing_quick_status

from ..central.reader import read_all_centrals

from aipass.prax.apps.handlers.json import json_handler
from .template_pusher import DEPRECATED_SECTIONS
from aipass.prax.apps.handlers.repo_root import find_repo_root

logger = get_direct_logger()

REFRESH_MANAGED_SECTIONS = {"ai_mail", "flow", "memory"}


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root, never reading the cwd (it runs at import)."""
    return find_repo_root(Path(__file__))


AIPASS_REGISTRY = _find_repo_root() / "AIPASS_REGISTRY.json"


def _load_branch_paths() -> List[Path]:
    """Load all branch paths from registry; FileNotFoundError when it is missing."""
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


# Mirrors flow's push_branch_dashboard.py::_build_section_data: sections.flow has two
# writers that assign it wholesale, so a shape one side does not build the other deletes.
OPEN_RECENT_LIMIT = 5
RECENTLY_CLOSED_LIMIT = 5

# Same window as @flow's _filter_branch_plans, or a refresh republishes closures it aged out.
CLOSED_WINDOW_DAYS = 7

# No honest source in PLANS.central.json (its per-branch totals are capped at 5): carry @flow's value.
FLOW_KEYS_PRAX_CANNOT_SOURCE = ("total_plans",)


def _find_branch_block(plans_data: Dict, branch_name: str) -> Dict:
    """Locate one branch's own block in the central file; the top-level arrays are the fleet roll-up."""
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
    """Return this branch's (open, closed) plan rows — never the fleet's."""
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

    Mirrors @flow's ``_build_open_recent``; the subject cap must match its push or it re-inflates.
    """
    newest_first = sorted(open_rows, key=lambda p: p.get("created") or "", reverse=True)
    return [
        {
            "plan_id": plan.get("plan_id", ""),
            "subject": cap_subject(plan.get("subject", "")),
            "created": plan.get("created", ""),
        }
        for plan in newest_first[:OPEN_RECENT_LIMIT]
    ]


def _within_closed_window(plan: Dict, cutoff: datetime) -> bool:
    """Whether a closed plan is recent enough to publish.

    Mirrors @flow's ``_filter_branch_plans``: no timestamp never ships, an unparseable one ships."""
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
    """Newest-first closed window in @flow's entry shape: {id, subject, closed}."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=CLOSED_WINDOW_DAYS)
    recent = [plan for plan in closed_rows if _within_closed_window(plan, cutoff)]
    newest_first = sorted(recent, key=lambda p: p.get("closed") or "", reverse=True)
    return [
        {
            "id": plan.get("plan_id", ""),
            "subject": cap_subject(plan.get("subject", "")),
            "closed": plan.get("closed", ""),
        }
        for plan in newest_first[:RECENTLY_CLOSED_LIMIT]
    ]


def _extract_flow_section(centrals: Dict, branch_name: str, existing: "Dict | None" = None) -> Dict:
    """Build the flow section from PLANS.central.json in @flow's five-key shape."""
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
    """Extract memory section - LOCAL vectors for this branch, not the global count."""
    local_vectors = 0

    chroma_dir = branch_path / ".chroma"
    if chroma_dir.exists():
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

    mb_data = centrals.get("memory", {})
    mb_last_updated = mb_data.get("last_updated", datetime.now().isoformat())

    return {"managed_by": "memory", "vectors_stored": local_vectors, "notes": {}, "last_updated": mb_last_updated}


def _calculate_quick_status(sections: Dict, branch_path: Path) -> Dict:
    """Calculate quick_status from branch data sources; thin delegate to status.py."""
    return calculate_quick_status(sections, branch_path)


def _read_existing_section(branch_path: Path, name: str) -> Dict:
    """Read one section off the dashboard already on disk.

    The refresh rebuilds from the template, so a foreign section's keys survive only through here."""
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


def _merge_over_disk(branch_path: Path, computed: Dict) -> Dict:
    """The computed quick_status merged over the block already on disk.

    An unreadable dashboard sets previous_unreadable so the loss of other services' keys shows in the file."""
    existing = read_existing_quick_status(branch_path)
    merged = merge_quick_status(existing, computed)
    if existing is None:
        merged["previous_unreadable"] = True
    else:
        merged.pop("previous_unreadable", None)
    return merged


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
    """Refresh all branch dashboards from central files."""
    errors = []
    branches_updated = 0
    branches_failed = 0

    centrals = read_all_centrals()

    try:
        branch_paths = _load_branch_paths()
    except Exception as e:
        logger.error("Failed to load branch paths: %s", e)
        return {"status": "error", "branches_updated": 0, "branches_failed": 0, "errors": [str(e)]}

    for branch_path in branch_paths:
        branch_name = branch_path.name.upper()

        try:
            # Read before the template rebuild drops it: it holds keys prax cannot source.
            existing_flow = _read_existing_section(branch_path, "flow")

            dashboard = create_fresh_dashboard(branch_path)

            dashboard["sections"]["ai_mail"] = _extract_ai_mail_section(centrals, branch_name)
            dashboard["sections"]["flow"] = _extract_flow_section(centrals, branch_name, existing_flow)
            dashboard["sections"]["memory"] = _extract_memory_section(centrals, branch_path)

            _preserve_write_through_sections(dashboard, branch_path, branch_name)
            _prune_deprecated_sections(dashboard)

            # Mail counts come from the branch's own inbox (status.py::_read_mail_counts),
            # never from the ai_mail section, which is read by nothing and popped before save.
            dashboard["quick_status"] = _merge_over_disk(
                branch_path, _calculate_quick_status(dashboard["sections"], branch_path)
            )
            dashboard["sections"].pop("ai_mail", None)

            save_dashboard(branch_path, dashboard)

            if branch_name == "DEVPULSE":
                _run_devpulse_plugin(branch_path)

            branches_updated += 1

        except Exception as e:
            logger.warning("Dashboard refresh failed for %s: %s", branch_name, e)
            errors.append(f"{branch_name}: {str(e)}")
            branches_failed += 1

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
    """Refresh a single branch's dashboard."""
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

        dashboard["quick_status"] = _merge_over_disk(
            branch_path, _calculate_quick_status(dashboard["sections"], branch_path)
        )
        dashboard["sections"].pop("ai_mail", None)

        save_dashboard(branch_path, dashboard)

        if branch_name == "DEVPULSE":
            _run_devpulse_plugin(branch_path)

        return {"status": "success", "branch": branch_name}

    except Exception as e:
        logger.error("Single dashboard refresh failed for %s: %s", branch_name, e)
        return {"status": "error", "branch": branch_name, "error": str(e)}
