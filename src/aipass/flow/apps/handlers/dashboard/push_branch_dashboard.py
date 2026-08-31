# =================== AIPass ====================
# Name: push_branch_dashboard.py
# Description: Push flow section to branch dashboards
# Version: 2.0.0
# Created: 2026-03-01
# Modified: 2026-08-16
# =============================================

"""
Push Flow Section to Branch Dashboard

Pushes the "flow" section of a branch's DASHBOARD.local.json via the
DevPulse write_section() write-through API.

Unlike update_local.py (which updates Flow's OWN dashboard), this handler
targets the branch where a plan LIVES. Each branch sees its own active plans
on its own dashboard.

Data Flow:
    1. Read fplan_registry.json (source of truth)
    2. Filter active plans for target branch (by location path)
    3. Get recently closed plans (last 5, within last 7 days)
    4. Get total plan count for this branch
    5. Call write_section(branch_path, "flow", section_data)

Section Structure:
{
    "managed_by": "flow",
    "active_plans": 23,
    "open_recent": [
        {"plan_id": "FPLAN-0373", "subject": "...", "created": "..."}
    ],
    "recently_closed": [
        {"id": "FPLAN-0372", "subject": "...", "closed": "..."}
    ],
    "total_plans": 15
}

open_recent is the bounded reading window: the 5 newest open plans by created
date, newest first, capped here in the renderer. Read it with active_plans —
the count is what stops 5 rows from reading as the whole world.

active_plans is an int COUNT, not a list. Ruling of 2026-08-16 (Patrick, via
@devpulse): the full open-plan list is the unbounded context a dashboard must
never carry, so it left the section entirely and `drone @flow list open` is the
only full-detail door. The int also matches the shape @prax's refresh already
writes, so the field means one thing no matter which writer built the section.

Usage:
    from aipass.flow.apps.handlers.dashboard.push_branch_dashboard import push_flow_to_branch_dashboard
    success = push_flow_to_branch_dashboard(Path("/path/to/branch"))
"""

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple

from aipass.flow.apps.handlers.json import json_handler
from aipass.prax.apps.modules.logger import system_logger as logger

# INFRASTRUCTURE IMPORT PATTERN
from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"

# Registry location (fallback default)
FLOW_JSON_DIR = FLOW_ROOT / "flow_json"
REGISTRY_FILE = FLOW_JSON_DIR / "fplan_registry.json"

# Dashboard template path (package-relative)
DASHBOARD_TEMPLATE_FILE = _PKG_ROOT / "devpulse" / "templates" / "DASHBOARD.template.json"

# quick_status ownership. Flow is the authority for plan counts and the only
# writer that emits commons_mentions, so it always recomputes those.
OWNED_KEYS = frozenset({"active_plans", "commons_mentions"})

# Mail counts mirror data Flow does not own — @prax sources them straight from
# inbox.json, while all we can see is the (possibly stale) ai_mail section. We
# seed them on a fresh dashboard but never overwrite a value already there.
MIRROR_KEYS = frozenset({"new_mail", "opened_mail"})

# Computed from every counter in the merged block, ours and foreign alike.
DERIVED_KEYS = frozenset({"action_required", "summary"})


# =============================================
# DASHBOARD WRITE (local — no cross-branch imports)
# =============================================


def _write_dashboard_section(branch_path: Path, section_name: str, section_data: Dict[str, Any]) -> bool:
    """
    Write a single section to a branch's DASHBOARD.local.json.

    Self-contained dashboard write — equivalent to DevPulse write_section()
    but without cross-branch imports. Loads existing dashboard, updates
    the named section, merge-updates quick_status (our keys recomputed,
    other writers' keys preserved), and saves.

    Args:
        branch_path: Path to branch root directory
        section_name: Section key (e.g. "flow")
        section_data: Dict of data for this section

    Returns:
        True if saved successfully, False on any error
    """
    try:
        dashboard_path = branch_path / "DASHBOARD.local.json"

        # Load existing or create fresh
        if dashboard_path.exists():
            content = dashboard_path.read_text().strip()
            if content:
                try:
                    dashboard = json.loads(content)
                except json.JSONDecodeError as exc:
                    logger.warning("Corrupt dashboard JSON at '%s', creating fresh: %s", dashboard_path, exc)
                    dashboard = _create_fresh_dashboard(branch_path)
            else:
                dashboard = _create_fresh_dashboard(branch_path)
        else:
            dashboard = _create_fresh_dashboard(branch_path)

        if "sections" not in dashboard:
            dashboard["sections"] = {}

        section_data["last_updated"] = datetime.now().isoformat()
        dashboard["sections"][section_name] = section_data
        dashboard["quick_status"] = _calculate_quick_status(dashboard["sections"], dashboard.get("quick_status"))
        dashboard["last_updated"] = datetime.now().isoformat()

        dashboard_path.write_text(json.dumps(dashboard, indent=2))
        return True

    except Exception as exc:
        logger.error("Failed to write dashboard section '%s' for branch '%s': %s", section_name, branch_path, exc)
        return False


def _create_fresh_dashboard(branch_path: Path) -> Dict[str, Any]:
    """
    Create fresh dashboard structure from template or fallback.

    Args:
        branch_path: Path to branch root

    Returns:
        Fresh dashboard dict
    """
    if DASHBOARD_TEMPLATE_FILE.exists():
        try:
            template = json.loads(DASHBOARD_TEMPLATE_FILE.read_text())
            dashboard = json.loads(json.dumps(template).replace("{{BRANCHNAME}}", branch_path.name.upper()))
            dashboard["last_updated"] = datetime.now().isoformat()
            return dashboard
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load dashboard template '%s', using fallback: %s", DASHBOARD_TEMPLATE_FILE, exc)

    now = datetime.now().isoformat()
    return {
        "_warning": "AUTO-GENERATED FILE - DO NOT MANUALLY EDIT.",
        "branch": branch_path.name.upper(),
        "last_updated": now,
        "quick_status": {"action_required": False},
        "sections": {
            "ai_mail": {"managed_by": "ai_mail", "new": 0, "opened": 0, "total": 0, "last_updated": ""},
            "flow": {"managed_by": "flow", "active_plans": 0, "recently_closed": [], "last_updated": ""},
            "memory": {"managed_by": "memory", "vectors_stored": 0, "notes": {}, "last_updated": ""},
            "devpulse": {"managed_by": "devpulse", "summary": {}, "last_updated": ""},
            "commons_activity": {"managed_by": "commons", "mentions": 0, "last_updated": ""},
        },
    }


def _as_count(value: Any) -> int:
    """Read a quick_status value as a count — anything non-integer reads as 0."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _foreign_counters(existing: Dict[str, Any]) -> Dict[str, int]:
    """
    Extract positive `*_count` counters written by other services.

    quick_status has several writers with different schemas (@prax's refresh
    contributes `todo_count`, for one). We cannot interpret arbitrary foreign
    keys, but a key named `*_count` holding a real integer is unambiguously a
    counter, so it can still feed action_required and the summary line.

    Args:
        existing: The quick_status block currently on disk

    Returns:
        Mapping of foreign counter key -> positive count
    """
    known = OWNED_KEYS | MIRROR_KEYS | DERIVED_KEYS
    counters: Dict[str, int] = {}
    for key, value in existing.items():
        if key in known or not key.endswith("_count"):
            continue
        if _as_count(value) > 0:
            counters[key] = value
    return counters


def _counter_label(key: str) -> str:
    """Turn a foreign counter key into a summary label ('todo_count' -> 'todos')."""
    label = key[: -len("_count")].replace("_", " ").strip()
    return label if label.endswith("s") else f"{label}s"


def _calculate_quick_status(sections: Dict[str, Any], existing: Any = None) -> Dict[str, Any]:
    """
    Recalculate the quick_status keys Flow owns, preserving every other key.

    quick_status is shared ground: @prax's dashboard refresh writes it too,
    with a different set of keys. Replacing the whole block means whichever
    service wrote last silently deletes the other's fields — that is how a
    plan close used to zero `todo_count` on a branch card. So we merge:

      - OWNED_KEYS   recomputed from live section data (we are the authority)
      - MIRROR_KEYS  preserved if already set, seeded only when absent
      - DERIVED_KEYS recomputed over every counter present, foreign included
      - anything else carried through untouched

    Args:
        sections: All dashboard sections dict
        existing: The quick_status block currently on disk (ignored if not a dict)

    Returns:
        Quick status dict — our keys recomputed, other writers' keys preserved
    """
    existing = existing if isinstance(existing, dict) else {}

    ai_mail = sections.get("ai_mail", {})
    flow = sections.get("flow", {})
    commons = sections.get("commons_activity", {})

    # Mirror keys: never downgrade a value another writer sourced first-hand.
    new_mail = existing["new_mail"] if "new_mail" in existing else ai_mail.get("new", ai_mail.get("unread", 0))
    opened_mail = existing["opened_mail"] if "opened_mail" in existing else ai_mail.get("opened", 0)

    # Read active_plans, the one key BOTH writers set. This used to read
    # active_count, which only Flow writes — so a section built by @prax's
    # refresh counted as zero open plans on the glance.
    # The list branch covers dashboards written before the 2026-08-16 ruling,
    # which still carry the old full-list shape until their next push.
    active_plans = flow.get("active_plans", 0)
    if isinstance(active_plans, list):
        active_plans = len(active_plans)
    active_plans = _as_count(active_plans)
    mentions = _as_count(commons.get("mentions", 0))

    foreign = _foreign_counters(existing)

    action_required = _as_count(new_mail) > 0 or active_plans > 0 or mentions > 0 or bool(foreign)

    parts = []
    if _as_count(new_mail) > 0:
        parts.append(f"{new_mail} new emails")
    if _as_count(opened_mail) > 0:
        parts.append(f"{opened_mail} opened")
    if active_plans > 0:
        parts.append(f"{active_plans} active plans")
    if mentions > 0:
        parts.append(f"{mentions} mentions")
    parts.extend(f"{count} {_counter_label(key)}" for key, count in foreign.items())

    # Foreign keys first (preserved verbatim), then the values we stand behind.
    merged = dict(existing)
    merged.update(
        {
            "new_mail": new_mail,
            "opened_mail": opened_mail,
            "active_plans": active_plans,
            "commons_mentions": mentions,
            "action_required": action_required,
            "summary": ", ".join(parts) if parts else "All clear",
        }
    )
    return merged


# =============================================
# PLAN TYPE HELPERS
# =============================================


def _get_all_registry_files() -> List[str]:
    """Return per-type registry filenames from template_registry.json."""
    try:
        template_reg = FLOW_JSON_DIR / "template_registry.json"
        if template_reg.exists():
            with open(template_reg, "r", encoding="utf-8") as f:
                data = json.load(f)
            files: List[str] = []
            for _key, type_cfg in data.get("types", {}).items():
                prefix = type_cfg.get("prefix", "")
                if prefix:
                    rf = f"{prefix.lower()}_registry.json"
                    if rf not in files:
                        files.append(rf)
            if files:
                return files
    except Exception as exc:
        logger.warning("[push_branch_dashboard] Failed to read template registry, falling back to default: %s", exc)
    return [REGISTRY_FILE.name]


# =============================================
# HELPER FUNCTIONS
# =============================================


def _load_registry() -> Dict[str, Any]:
    """
    Load all per-type plan registries and merge into a single dict.

    Uses PREFIX-NNNN composite keys to avoid collisions between registries
    that share the same plan number (e.g. FPLAN-0013 vs DPLAN-0013).

    Returns:
        Merged registry dict or empty structure if unavailable
    """
    merged: Dict[str, Any] = {"plans": {}, "next_number": 1}
    for registry_file in _get_all_registry_files():
        target = FLOW_JSON_DIR / registry_file
        reg_prefix = registry_file.replace("_registry.json", "").upper()
        try:
            if not target.exists():
                continue
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            for plan_num, plan_data in data.get("plans", {}).items():
                file_path = plan_data.get("file_path", "")
                filename = Path(file_path).name if file_path else ""
                prefix_match = re.match(r"^([A-Z]+PLAN)", filename)
                prefix = prefix_match.group(1) if prefix_match else reg_prefix
                composite_key = f"{prefix}-{plan_num.zfill(4)}"
                merged["plans"][composite_key] = plan_data
            nn = data.get("next_number", 1)
            if nn > merged["next_number"]:
                merged["next_number"] = nn
        except Exception as exc:
            logger.warning("Failed to load registry '%s': %s", target, exc)
    return merged


def _filter_branch_plans(
    registry: Dict[str, Any], branch_path: Path
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """
    Filter plans for a specific branch from the registry.

    Args:
        registry: Full fplan_registry.json data
        branch_path: Absolute path to the branch directory

    Returns:
        Tuple of (active_plans, recently_closed_plans, total_branch_plans)
    """
    plans = registry.get("plans", {})
    branch_path_str = str(branch_path)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)

    active_plans = []
    closed_plans = []
    branch_total = 0

    for plan_key, plan_data in plans.items():
        location = plan_data.get("location", "")

        # Match plans whose location is this branch
        if location != branch_path_str:
            continue

        branch_total += 1
        # plan_key is composite PREFIX-NNNN from merged registry
        plan_id = plan_key

        if plan_data.get("status") == "open":
            active_plans.append(
                {
                    "id": plan_id,
                    "subject": plan_data.get("subject", ""),
                    "created": plan_data.get("created", ""),
                    "location": location,
                }
            )
        elif plan_data.get("status") == "closed":
            closed_ts = plan_data.get("closed", "")
            # Only include recently closed (within 7 days)
            if closed_ts:
                try:
                    closed_dt = datetime.fromisoformat(closed_ts)
                    if closed_dt >= cutoff:
                        closed_plans.append(
                            {"id": plan_id, "subject": plan_data.get("subject", ""), "closed": closed_ts}
                        )
                except (ValueError, TypeError) as exc:
                    # If we can't parse the timestamp, include it anyway
                    logger.warning(
                        "Unparseable closed timestamp '%s' for plan %s, including anyway: %s", closed_ts, plan_id, exc
                    )
                    closed_plans.append({"id": plan_id, "subject": plan_data.get("subject", ""), "closed": closed_ts})

    # Sort active by created date (newest first)
    active_plans.sort(key=lambda x: x.get("created", ""), reverse=True)

    # Sort closed by closed date (newest first), limit to 5
    closed_plans.sort(key=lambda x: x.get("closed", ""), reverse=True)
    recent_closed = closed_plans[:5]

    return active_plans, recent_closed, branch_total


# How many open plans the bounded window publishes. Patrick's spec: a reader
# gets its bearings from 5 named plans plus the total, never from 22 rows.
OPEN_RECENT_LIMIT = 5


def _build_open_recent(active_plans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build the bounded window of the newest open plans, newest first.

    The cap lives here, in the renderer, not in whoever reads the section —
    a consumer that has to remember to slice is a consumer that will one day
    forget, and the point of the field is that the full list never travels.

    Sorting is done here rather than trusted from the caller so the field's
    newest-first contract holds for any input order. Plans with no `created`
    date sort last instead of raising.

    Args:
        active_plans: Open plan dicts as built by _filter_branch_plans

    Returns:
        At most OPEN_RECENT_LIMIT entries of {plan_id, subject, created}
    """
    newest_first = sorted(active_plans, key=lambda p: p.get("created") or "", reverse=True)
    return [
        {
            "plan_id": plan.get("id", ""),
            "subject": plan.get("subject", ""),
            "created": plan.get("created", ""),
        }
        for plan in newest_first[:OPEN_RECENT_LIMIT]
    ]


def _build_section_data(
    active_plans: List[Dict[str, Any]], recently_closed: List[Dict[str, Any]], total_plans: int
) -> Dict[str, Any]:
    """
    Build the flow section data for write_section().

    Args:
        active_plans: List of active plan dicts
        recently_closed: List of recently closed plan dicts
        total_plans: Total plan count for this branch

    Returns:
        Section data dict ready for write_section()
    """
    return {
        "managed_by": "flow",
        "active_plans": len(active_plans),
        "open_recent": _build_open_recent(active_plans),
        "recently_closed": recently_closed,
        "total_plans": total_plans,
    }


# =============================================
# HANDLER FUNCTION
# =============================================


def push_flow_to_branch_dashboard(branch_path: Path) -> bool:
    """
    Push flow section to a branch's DASHBOARD.local.json via write_section().

    Reads the flow registry, filters plans for the target branch,
    and writes the flow section to the branch's dashboard.

    Dashboard write failures are silent (returns False, never raises).

    Args:
        branch_path: Absolute path to the branch directory
            (e.g. Path("/repo/src/aipass/devpulse"))

    Returns:
        True if successfully written, False on any error
    """
    try:
        branch_path = Path(branch_path)

        # Guard: only push to paths that already have a dashboard (real branches)
        dashboard_file = branch_path / "DASHBOARD.local.json"
        if not dashboard_file.exists():
            return False

        # 1. Load the registry
        registry = _load_registry()

        # 2. Filter plans for this branch
        active_plans, recently_closed, total_plans = _filter_branch_plans(registry, branch_path)

        # 3. Build section data
        section_data = _build_section_data(active_plans, recently_closed, total_plans)

        # 4. Write flow section to branch dashboard
        result = _write_dashboard_section(branch_path, "flow", section_data)

        if result:
            json_handler.log_operation(
                "branch_dashboard_pushed",
                {
                    "branch": branch_path.name,
                    "active_plans": len(active_plans),
                    "recently_closed": len(recently_closed),
                    "total_plans": total_plans,
                    "success": True,
                },
            )

        return result

    except Exception as exc:
        logger.error("Failed to push flow section to branch dashboard '%s': %s", branch_path, exc)
        return False


def push_flow_to_all_branch_dashboards() -> Dict[str, int]:
    """
    Push the flow section to every branch Flow holds plans for.

    Card values are written per-branch on plan events, so a change to the
    section contract only reaches a branch that happens to file a plan
    afterwards. After the 2.0.0 shape change, 14 of 17 cards still read
    total_plans 0 and two more still served the pre-2.0.0 list shape: those
    branches were not waiting on time, they were waiting on an event that may
    never arrive (@prax, 2026-08-16). This sweep is the repair, and the way to
    land any future contract change fleet-wide instead of one plan at a time.

    Branches are discovered from plan locations in the registry. Paths without
    a dashboard are skipped, never created — push_flow_to_branch_dashboard
    already refuses those, and a directory with no dashboard is not a branch.
    One branch failing never costs the others their push.

    Returns:
        Counts of {"pushed", "skipped", "failed"}
    """
    registry = _load_registry()
    locations = {plan.get("location", "") for plan in registry.get("plans", {}).values() if plan.get("location", "")}

    counts = {"pushed": 0, "skipped": 0, "failed": 0}
    for location in sorted(locations):
        branch_path = Path(location)
        if not (branch_path / "DASHBOARD.local.json").exists():
            counts["skipped"] += 1
            continue
        try:
            counts["pushed" if push_flow_to_branch_dashboard(branch_path) else "failed"] += 1
        except Exception as exc:
            logger.error("Sweep failed for branch '%s', continuing: %s", branch_path, exc)
            counts["failed"] += 1

    logger.info(
        "Flow dashboard sweep complete: %d pushed, %d skipped (no dashboard), %d failed",
        counts["pushed"],
        counts["skipped"],
        counts["failed"],
    )
    return counts
