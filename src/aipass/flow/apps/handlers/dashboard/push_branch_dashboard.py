# =================== AIPass ====================
# Name: push_branch_dashboard.py
# Description: Push flow section to branch dashboards
# Version: 2.4.0
# Created: 2026-03-01
# Modified: 2026-10-24
# =============================================

"""Push Flow Section to Branch Dashboard

active_plans is an int count, never the list: the full open-plan list is unbounded context a dashboard
must not carry (`drone @flow list open` is the full-detail door), and @prax's refresh writes the same int.
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple

from aipass.flow.apps.handlers.json import json_handler
from aipass.prax.apps.modules.logger import system_logger as logger

# Import the caps, never retype them: `sections.flow` has two writers (prax's refresh and this push).
from aipass.prax.apps.modules.dashboard import DASHBOARD_CHAR_BUDGET, cap_subject, dashboard_lock

from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"

FLOW_JSON_DIR = FLOW_ROOT / "flow_json"
REGISTRY_FILE = FLOW_JSON_DIR / "fplan_registry.json"

# Flow is the authority for these quick_status keys, so it always recomputes them.
OWNED_KEYS = frozenset({"active_plans", "commons_mentions"})

# @prax sources mail counts from inbox.json; ours may be stale, so seed them but never overwrite.
MIRROR_KEYS = frozenset({"new_mail", "opened_mail"})

DERIVED_KEYS = frozenset({"action_required", "summary"})


def _warn_over_budget(branch_path: Path, rendered: str) -> None:
    """Log one WARNING when a rendered dashboard is over DASHBOARD_CHAR_BUDGET.
    Warn, never refuse or trim: a refused save leaves a stale dashboard. Units are chars (len of the JSON).
    """
    size = len(rendered)
    if size > DASHBOARD_CHAR_BUDGET:
        logger.warning(
            "Dashboard for branch '%s' is %d chars, over the %d budget",
            branch_path.name,
            size,
            DASHBOARD_CHAR_BUDGET,
        )


def _write_dashboard_section(branch_path: Path, section_name: str, section_data: Dict[str, Any]) -> bool:
    """Write one section; an unreadable file is refused, since reseeding it drops every other section."""
    try:
        dashboard_path = branch_path / "DASHBOARD.local.json"
        # prax's refresh holds the same lock, so neither writer replaces the file between the other's read and write.
        with dashboard_lock(branch_path):
            try:
                dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Dashboard at '%s' unreadable, push refused: %s", dashboard_path, exc)
                return False

            if "sections" not in dashboard:
                dashboard["sections"] = {}

            section_data["last_updated"] = datetime.now().isoformat()
            dashboard["sections"][section_name] = section_data
            dashboard["quick_status"] = _calculate_quick_status(dashboard["sections"], dashboard.get("quick_status"))
            dashboard["last_updated"] = datetime.now().isoformat()

            rendered = json.dumps(dashboard, indent=2)
            _warn_over_budget(branch_path, rendered)
            tmp_path = dashboard_path.with_suffix(".tmp")
            tmp_path.write_text(rendered, encoding="utf-8")
            os.replace(tmp_path, dashboard_path)
            return True

    except Exception as exc:
        logger.error("Failed to write dashboard section '%s' for branch '%s': %s", section_name, branch_path, exc)
        return False


def _as_count(value: Any) -> int:
    """Read a quick_status value as a count — anything non-integer reads as 0."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _foreign_counters(existing: Dict[str, Any]) -> Dict[str, int]:
    """Extract positive `*_count` counters written by other services.
    Foreign keys cannot be interpreted, but a `*_count` int is unambiguously a counter.
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
    """Recompute OWNED keys, seed MIRROR keys only when absent, keep the rest: @prax writes this block too."""
    existing = existing if isinstance(existing, dict) else {}

    ai_mail = sections.get("ai_mail", {})
    flow = sections.get("flow", {})
    commons = sections.get("commons_activity", {})

    new_mail = existing["new_mail"] if "new_mail" in existing else ai_mail.get("new", ai_mail.get("unread", 0))
    opened_mail = existing["opened_mail"] if "opened_mail" in existing else ai_mail.get("opened", 0)

    # active_plans is the one key both writers set; a list is the old shape, kept until the next push.
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


def _load_registry() -> Dict[str, Any]:
    """Load all per-type plan registries and merge into a single dict.
    Keys are PREFIX-NNNN so registries sharing a plan number (FPLAN-0013, DPLAN-0013) do not collide.
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
    """Filter plans for a specific branch from the registry.
    Returns (active_plans, recently_closed_plans, total_branch_plans).
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

        if location != branch_path_str:
            continue

        branch_total += 1
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
            if closed_ts:
                try:
                    closed_dt = datetime.fromisoformat(closed_ts)
                    if closed_dt >= cutoff:
                        closed_plans.append(
                            {"id": plan_id, "subject": plan_data.get("subject", ""), "closed": closed_ts}
                        )
                except (ValueError, TypeError) as exc:
                    logger.warning(
                        "Unparseable closed timestamp '%s' for plan %s, including anyway: %s", closed_ts, plan_id, exc
                    )
                    closed_plans.append({"id": plan_id, "subject": plan_data.get("subject", ""), "closed": closed_ts})

    active_plans.sort(key=lambda x: x.get("created", ""), reverse=True)

    closed_plans.sort(key=lambda x: x.get("closed", ""), reverse=True)
    recent_closed = closed_plans[:5]

    return active_plans, recent_closed, branch_total


# A reader gets its bearings from 5 named plans plus the total, never from every row.
OPEN_RECENT_LIMIT = 5


def _build_open_recent(active_plans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build the bounded window of the newest open plans, newest first.
    The cap lives in the renderer: a consumer that must remember to slice will one day forget.
    """
    newest_first = sorted(active_plans, key=lambda p: p.get("created") or "", reverse=True)
    return [
        {
            "plan_id": plan.get("id", ""),
            "subject": cap_subject(plan.get("subject", "")),
            "created": plan.get("created", ""),
        }
        for plan in newest_first[:OPEN_RECENT_LIMIT]
    ]


def _build_section_data(
    active_plans: List[Dict[str, Any]], recently_closed: List[Dict[str, Any]], total_plans: int
) -> Dict[str, Any]:
    """Build the flow section data for write_section().
    Subjects are capped here, the one seam both lists pass through, so no new build path can skip it.
    """
    return {
        "managed_by": "flow",
        "active_plans": len(active_plans),
        "open_recent": _build_open_recent(active_plans),
        "recently_closed": [{**plan, "subject": cap_subject(plan.get("subject", ""))} for plan in recently_closed],
        "total_plans": total_plans,
    }


def push_flow_to_branch_dashboard(branch_path: Path) -> bool | None:
    """Push flow section to a branch's DASHBOARD.local.json via write_section().
    Failures are logged, never raised: the plan operation that called this has already happened.

    Returns True if written, None if the path has no DASHBOARD.local.json (not a branch, nothing
    created), False if the push failed; None and False must stay distinct.
    """
    try:
        branch_path = Path(branch_path)

        dashboard_file = branch_path / "DASHBOARD.local.json"
        if not dashboard_file.exists():
            return None

        registry = _load_registry()

        active_plans, recently_closed, total_plans = _filter_branch_plans(registry, branch_path)

        section_data = _build_section_data(active_plans, recently_closed, total_plans)

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
    """Push the flow section to every branch Flow holds plans for.
    Cards are written on plan events, so this sweep lands a section contract change fleet-wide.
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
            pushed = push_flow_to_branch_dashboard(branch_path)
            # None: the dashboard went between the check above and the push.
            counts["skipped" if pushed is None else "pushed" if pushed else "failed"] += 1
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
