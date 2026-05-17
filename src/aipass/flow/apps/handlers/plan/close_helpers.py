# =================== AIPass ====================
# Name: close_helpers.py
# Description: Plan Closure Helper Functions
# Version: 1.0.0
# Created: 2026-05-16
# Modified: 2026-05-16
# =============================================

"""
Plan Closure Helpers

Routing, resolution, self-healing, and utility functions extracted from close_ops.

Usage:
    from aipass.flow.apps.handlers.plan.close_helpers import (
        _extract_prefix,
        _resolve_registry_file,
        _find_plan_across_registries,
        _find_relocated_plan,
        _find_unregistered_plan_file,
        _self_heal_unregistered_plan,
        _spawn_background_runner,
    )
"""

import json
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List

from aipass.prax import logger

from aipass.flow.apps.handlers.json import json_handler

# =============================================
# INFRASTRUCTURE
# =============================================

_PKG_ROOT = Path(__file__).resolve().parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"

MODULE_NAME = "close_plan"


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


PROCESSED_PLANS_DIR = _find_repo_root() / ".backup" / "processed_plans"

# =============================================
# PLAN TYPE ROUTING
# =============================================


def _extract_prefix(plan_num_raw: str) -> str | None:
    """Extract plan-type prefix (e.g. ``"DPLAN"``) from raw input."""
    import re

    m = re.match(r"^([A-Z]+PLAN)-", plan_num_raw.strip(), re.IGNORECASE)
    return m.group(1).upper() if m else None


def _resolve_registry_file(plan_num_raw: str) -> str | None:
    """Resolve registry_file from a raw plan number with prefix.

    Returns registry filename or None if no prefix detected.
    """
    prefix = _extract_prefix(plan_num_raw)
    if prefix is None:
        return None
    return f"{prefix.lower()}_registry.json"


def _load_template_registry() -> Dict[str, Any]:
    """Read template_registry.json directly (avoids cross-handler import)."""
    registry_path = FLOW_ROOT / "flow_json" / "template_registry.json"
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[{MODULE_NAME}] Failed to read template_registry.json: {e}")
        return {"types": {}}


def _find_plan_across_registries(plan_key: str, load_registry_fn: Any) -> str | None:
    """Search all registries for a plan number when no prefix given.

    Returns registry filename where the plan was found, or None.
    """
    try:
        template_reg = _load_template_registry()
        for _type_key, config in template_reg.get("types", {}).items():
            prefix = config.get("prefix", "")
            if not prefix:
                continue
            reg_file = f"{prefix.lower()}_registry.json"
            try:
                registry = load_registry_fn(registry_file=reg_file)
                if plan_key in registry.get("plans", {}):
                    return reg_file
            except Exception as e:
                logger.warning(f"[{MODULE_NAME}] Failed to search registry '{reg_file}' for plan '{plan_key}': {e}")
                continue
    except Exception as e:
        logger.warning(f"[{MODULE_NAME}] Failed to discover plan types while searching for plan '{plan_key}': {e}")
    return None


# =============================================
# HELPER
# =============================================


def _find_relocated_plan(plan_file: Path) -> Path | None:
    """Search common locations for a plan file that was manually moved.

    Returns the found path, or None if not found anywhere.
    """
    filename = plan_file.name
    branch_dir = plan_file.parent

    search_dirs = [
        branch_dir / ".archive",
        branch_dir / "docs.local",
        PROCESSED_PLANS_DIR,
    ]

    for search_dir in search_dirs:
        candidate = search_dir / filename
        if candidate.exists():
            return candidate

    return None


def _find_unregistered_plan_file(prefix: str, plan_key: str) -> Path | None:
    """Search src/aipass/ for a plan file matching PREFIX-plan_key not in any registry."""
    aipass_root = FLOW_ROOT.parent
    pattern = f"{prefix}-{plan_key}*.md"
    skip_parts = {".backup", ".archive", "__pycache__", ".git", "processed_plans"}

    for match in aipass_root.rglob(pattern):
        if any(part in skip_parts for part in match.parts):
            continue
        return match

    return None


def _self_heal_unregistered_plan(
    prefix: str,
    plan_key: str,
    plan_file: Path,
    registry: Dict[str, Any],
    reg_file: str,
    save_registry_fn: Any,
    load_registry_fn: Any,
    messages: List[Dict[str, Any]],
) -> tuple[str, Dict[str, Any]]:
    """Register an unregistered plan file and handle number collisions.

    Returns (actual_plan_key, updated_registry).
    """
    import re as _re

    messages.append(
        {
            "type": "warning",
            "text": "Plan file found but not registered — likely created manually. Initiating self-heal.",
        }
    )
    messages.append({"type": "dim", "text": f"  Found: {plan_file}"})

    actual_key = plan_key

    if plan_key in registry.get("plans", {}):
        next_num = registry.get("next_number", int(plan_key) + 1)
        actual_key = f"{next_num:04d}"
        messages.append(
            {
                "type": "warning",
                "text": f"  Number {plan_key} already registered as {prefix}-{plan_key}. "
                f"Bumping to next available: {prefix}-{actual_key}.",
            }
        )

    try:
        template_reg = _load_template_registry()
        for _type_key, config in template_reg.get("types", {}).items():
            other_prefix = config.get("prefix", "")
            if other_prefix == prefix:
                continue
            other_reg_file = f"{other_prefix.lower()}_registry.json"
            try:
                other_registry = load_registry_fn(registry_file=other_reg_file)
                if plan_key in other_registry.get("plans", {}):
                    messages.append(
                        {
                            "type": "dim",
                            "text": f"  Note: {other_prefix}-{plan_key} also exists in {other_prefix} registry",
                        }
                    )
            except Exception as e:
                logger.warning(f"[{MODULE_NAME}] Failed to check cross-prefix registry '{other_reg_file}': {e}")
                continue
    except Exception as e:
        logger.warning(f"[{MODULE_NAME}] Cross-prefix collision check failed: {e}")

    stem = plan_file.stem
    subject = "Manually created plan"
    try:
        after_prefix = _re.sub(r"^[A-Z]+PLAN-\d{4}_", "", stem)
        after_prefix = _re.sub(r"_\d{4}-\d{2}-\d{2}$", "", after_prefix)
        if after_prefix:
            subject = after_prefix.replace("_", " ")
    except Exception as e:
        logger.warning(f"[{MODULE_NAME}] Failed to extract subject from filename '{stem}': {e}")

    entry = {
        "location": str(plan_file.parent),
        "relative_path": plan_file.parent.name,
        "created": datetime.now(timezone.utc).isoformat(),
        "subject": subject,
        "status": "open",
        "file_path": str(plan_file),
        "template_type": "default",
        "self_healed": True,
    }

    registry["plans"][actual_key] = entry
    if actual_key != plan_key:
        registry["next_number"] = int(actual_key) + 1
    save_registry_fn(registry, registry_file=reg_file)

    messages.append(
        {
            "type": "success",
            "text": f"  Registered {prefix}-{actual_key}: {subject}",
        }
    )

    logger.info(f"[{MODULE_NAME}] Self-healed: registered {prefix}-{actual_key} from file {plan_file}")
    json_handler.log_operation("self_heal_register", {"prefix": prefix, "plan_key": actual_key, "file": str(plan_file)})

    return actual_key, registry


def _spawn_background_runner():
    """Spawn post_close_runner.py as a fully detached background process"""
    bg_runner = FLOW_ROOT / "apps" / "modules" / "post_close_runner.py"
    subprocess.Popen(
        [sys.executable, str(bg_runner)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
    )
