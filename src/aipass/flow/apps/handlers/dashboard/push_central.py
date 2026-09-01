# =================== AIPass ====================
# Name: push_central.py
# Description: Push to Plans Central Handler
# Version: 1.1.0
# Created: 2025-11-21
# Modified: 2025-11-21
# =============================================

"""
Push to Plans Central Handler

Pushes plan data for ALL branches to the central PLANS.central.json file at .ai_central.
This handler follows the 3-tier logging standard (no Prax imports, no logging).

Features:
- Reads all per-type plan registries
- Groups plans by branch (derived from location path)
- Updates per-branch sections in PLANS.central.json
- Calls aggregate_central_impl to rebuild top-level active_plans
- Calculates global statistics across all branches
- Pure handler - returns boolean for success/failure

Usage:
    from aipass.flow.apps.handlers.dashboard.push_central import push_to_plans_central
    success = push_to_plans_central()
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List

from aipass.flow.apps.handlers.json import json_handler
from aipass.prax.apps.modules.logger import system_logger as logger

# INFRASTRUCTURE IMPORT PATTERN
from aipass.flow.apps.handlers.repo_root import find_repo_root, module_file

_PKG_ROOT = module_file(__file__).parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"

# Handler imports (aggregate_ops is a sibling handler — avoids handler→module layer violation)
from aipass.flow.apps.handlers.plan.aggregate_ops import aggregate_central_impl

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "push_central"
FLOW_JSON_DIR = FLOW_ROOT / "flow_json"
REGISTRY_FILE = FLOW_JSON_DIR / "fplan_registry.json"


def _find_repo_root() -> Path:
    """Walk up to the repo root (the directory holding AIPASS_REGISTRY.json).

    Delegates to ``handlers/repo_root.find_repo_root`` — the one
    implementation. This used to be a private copy ending
    ``return Path.cwd()``; there were seven such copies in flow and six of
    them are called at MODULE level, so on a registry-less checkout every
    import guessed its root from the process directory, and with the cwd
    deleted the import died outright. See that module's docstring.
    """
    return find_repo_root(caller="push_central")


_REPO_ROOT = _find_repo_root()
AI_CENTRAL_DIR = _REPO_ROOT / ".ai_central"
CENTRAL_FILE = AI_CENTRAL_DIR / "PLANS.central.json"

# =============================================
# PLAN TYPE HELPERS
# =============================================


def _get_all_registry_files() -> List[str]:
    """Return per-type registry filenames via plan-type discovery."""
    try:
        from aipass.flow.apps.handlers.template.plan_type_loader import discover_plan_types

        files: List[str] = []
        for _key, config in discover_plan_types().items():
            rf = config.get("registry_file")
            if rf and rf not in files:
                files.append(rf)
        if files:
            return files
    except Exception as exc:
        logger.warning("[push_central] Failed to discover plan types, falling back to default registry: %s", exc)
    return [REGISTRY_FILE.name]


# =============================================
# HELPER FUNCTIONS
# =============================================


def _load_registry() -> Dict[str, Any]:
    """Load all per-type plan registries and merge into a single dict.

    Uses PREFIX-NNNN composite keys to avoid collisions between registries
    that share the same plan number (e.g. FPLAN-0013 vs DPLAN-0013).

    Returns:
        Merged registry dict or empty structure if no files found
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


def _extract_plans_by_branch(registry: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Extract plans from registry grouped by branch.

    Args:
        registry: Merged registry data (all plan types)

    Returns:
        Dict mapping branch_name -> branch section with active_plans,
        recently_closed, and statistics.
    """
    plans = registry.get("plans", {})
    branch_buckets: Dict[str, Dict[str, List]] = {}

    for plan_key, plan_data in plans.items():
        location = plan_data.get("location", "")
        if not location:
            continue

        branch_name = Path(location).name

        if branch_name not in branch_buckets:
            branch_buckets[branch_name] = {"active": [], "closed": [], "location": location}

        plan_entry = {
            "plan_id": plan_key,
            "subject": plan_data.get("subject", ""),
            "status": plan_data.get("status", "open"),
            "created": plan_data.get("created", ""),
            "file_path": plan_data.get("file_path", ""),
            "relative_path": plan_data.get("relative_path", ""),
            "branch": branch_name,
        }

        if plan_data.get("status") == "open":
            branch_buckets[branch_name]["active"].append(plan_entry)
        else:
            plan_entry["closed"] = plan_data.get("closed", "")
            plan_entry["closed_reason"] = plan_data.get("closed_reason", "")
            branch_buckets[branch_name]["closed"].append(plan_entry)

    result: Dict[str, Dict[str, Any]] = {}
    for branch_name, bucket in branch_buckets.items():
        active = sorted(bucket["active"], key=lambda x: x.get("created", ""), reverse=True)
        closed = sorted(bucket["closed"], key=lambda x: x.get("closed", ""), reverse=True)
        recently_closed = closed[:5]

        result[branch_name] = {
            "branch_name": branch_name.upper(),
            "branch_path": bucket["location"],
            "active_plans": active,
            "recently_closed": recently_closed,
            "statistics": {
                "active_count": len(active),
                "total_closed": len(closed),
                "recently_closed_included": len(recently_closed),
            },
        }

    return result


def _load_central() -> Dict[str, Any]:
    """Load existing PLANS.central.json

    Returns:
        Central file data or empty structure if file doesn't exist
    """
    if not CENTRAL_FILE.exists():
        return {
            "generated_at": "",
            "branches": {},
            "global_statistics": {"total_active": 0, "total_closed": 0, "branches_reporting": 0},
        }

    try:
        with open(CENTRAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Failed to load PLANS.central.json '%s': %s", CENTRAL_FILE, exc)
        return {
            "generated_at": "",
            "branches": {},
            "global_statistics": {"total_active": 0, "total_closed": 0, "branches_reporting": 0},
        }


def _calculate_global_statistics(central_data: Dict[str, Any]) -> Dict[str, int]:
    """Calculate global statistics by summing all branches

    Args:
        central_data: The full central file data

    Returns:
        Dict with total_active, total_closed, branches_reporting
    """
    branches = central_data.get("branches", {})
    total_active = 0
    total_closed = 0

    for branch_data in branches.values():
        stats = branch_data.get("statistics", {})
        total_active += stats.get("active_count", 0)
        total_closed += stats.get("total_closed", 0)

    return {"total_active": total_active, "total_closed": total_closed, "branches_reporting": len(branches)}


# =============================================
# MAIN HANDLER FUNCTION
# =============================================


def push_to_plans_central() -> bool:
    """Push plan data for ALL branches to .ai_central/PLANS.central.json

    Algorithm:
    1. Read all per-type plan registries
    2. Group plans by branch (derived from location path)
    3. Build per-branch sections with active/closed/stats
    4. Write all branch sections to PLANS.central.json
    5. Update global_statistics (total counts across all branches)
    6. Call aggregate_central_impl to rebuild top-level active_plans with validation

    Returns:
        True on success, False on failure
    """
    try:
        AI_CENTRAL_DIR.mkdir(parents=True, exist_ok=True)

        registry = _load_registry()
        branch_sections = _extract_plans_by_branch(registry)

        now = datetime.now(timezone.utc).isoformat()
        for section in branch_sections.values():
            section["last_updated"] = now

        central_data = _load_central()
        central_data["branches"] = branch_sections
        central_data["global_statistics"] = _calculate_global_statistics(central_data)
        central_data["generated_at"] = now

        with open(CENTRAL_FILE, "w", encoding="utf-8") as f:
            json.dump(central_data, f, indent=2, ensure_ascii=False)

        aggregate_central_impl(heal=True, central_file=CENTRAL_FILE, central_dir=AI_CENTRAL_DIR)

        total_active = sum(len(s.get("active_plans", [])) for s in branch_sections.values())
        json_handler.log_operation(
            "plans_central_pushed",
            {
                "active_plans": total_active,
                "branches_reporting": len(branch_sections),
                "success": True,
            },
        )

        return True

    except Exception as exc:
        logger.error("Failed to push plans to central '%s': %s", CENTRAL_FILE, exc)
        return False
