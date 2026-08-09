# =================== AIPass ====================
# Name: plan_file.py
# Description: PLAN file event handlers for registry updates
# Version: 1.1.0
# Created: 2026-01-20
# Modified: 2026-08-09
# =============================================

"""
PLAN File Event Handlers

Handles filesystem events for PLAN files and updates Flow's registry.

Events handled:
- plan_file_created: New PLAN file detected
- plan_file_deleted: PLAN file removed
- plan_file_moved: PLAN file moved/renamed

Architecture:
- Flow fires these events via trigger.fire()
- Trigger handlers update Flow's registry
- Decoupled: Flow doesn't know what happens after firing
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from aipass.trigger.apps.config import TRIGGER_ROOT, AIPASS_PKG_ROOT, atomic_write_json, trail_logger
from aipass.trigger.apps.handlers.json import json_handler


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


REPO_ROOT = _find_repo_root()

# Registry JSON file path (direct file access, no handler imports)
FLOW_JSON_DIR = AIPASS_PKG_ROOT / "flow" / "flow_json"
REGISTRY_FILE = FLOW_JSON_DIR / "PLAN_REGISTRY.json"

HANDLER_LOG = TRIGGER_ROOT / "logs" / "plan_file_handler.jsonl"

MODULE_NAME = "trigger.plan_file"


# Deliberately NOT prax: this handler runs on the event path the log watchers
# read, so a line through prax would be detected and fired straight back at it.
# The sidecar is `.jsonl`, which the watchers skip — they read only `*.log`.
logger = trail_logger(HANDLER_LOG)


def _load_registry() -> dict:
    """Load registry from JSON file"""
    import json

    if REGISTRY_FILE.exists():
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"plans": {}, "next_number": 1}


def _save_registry(registry: dict) -> None:
    """Save registry to JSON file"""
    atomic_write_json(REGISTRY_FILE, registry)


def _get_plan_number(file_path: Path) -> Optional[str]:
    """Extract plan number from filename (e.g., FPLAN-0001.md -> 0001)"""
    match = re.search(r"FPLAN-(\d{4})\.md$", file_path.name)
    return match.group(1) if match else None


def handle_plan_file_created(path: str, **kwargs):
    """
    Handle new PLAN file creation

    Args:
        path: Absolute path to the new PLAN file
    """
    file_path = Path(path)
    plan_number = _get_plan_number(file_path)

    if not plan_number:
        return

    try:
        registry = _load_registry()

        # Check if already exists
        if plan_number in registry.get("plans", {}):
            existing_plan = registry["plans"][plan_number]

            # If plan is closed, preserve closed status and just update location
            if existing_plan.get("status") == "closed":
                existing_plan["location"] = str(file_path.parent)
                existing_plan["relative_path"] = str(file_path.parent.relative_to(REPO_ROOT))
                existing_plan["file_path"] = str(file_path)
                existing_plan["last_updated"] = datetime.now(timezone.utc).isoformat()
                _save_registry(registry)
                return
            else:
                return

        # Add to registry
        relative_path = str(file_path.parent.relative_to(REPO_ROOT))
        registry.setdefault("plans", {})[plan_number] = {
            "location": str(file_path.parent),
            "relative_path": relative_path,
            "created": datetime.now(timezone.utc).isoformat(),
            "subject": "Auto-detected PLAN",
            "status": "open",
            "file_path": str(file_path),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        # Update next_number if needed
        current_next = registry.get("next_number", 1)
        plan_num_int = int(plan_number)
        if plan_num_int >= current_next:
            registry["next_number"] = plan_num_int + 1

        _save_registry(registry)

        json_handler.log_operation("plan_event", {"success": True})

    except Exception as e:
        logger.error(f"handle_plan_file_created failed for {path}: {e}", module=MODULE_NAME)


def handle_plan_file_deleted(path: str, **kwargs):
    """
    Handle PLAN file deletion

    Args:
        path: Absolute path to the deleted PLAN file
    """
    file_path = Path(path)
    plan_number = _get_plan_number(file_path)

    if not plan_number:
        return

    try:
        registry = _load_registry()
        plans = registry.get("plans", {})

        if plan_number in plans:
            plan_info = plans[plan_number]

            # If plan is closed/processed, preserve it in registry but mark as archived
            if plan_info.get("status") == "closed" or plan_info.get("processed"):
                plan_info["archived"] = True
                plan_info["archived_date"] = datetime.now(timezone.utc).isoformat()
                plan_info["last_updated"] = datetime.now(timezone.utc).isoformat()
                _save_registry(registry)
            else:
                # Plan is open but file deleted - remove from registry completely
                del plans[plan_number]
                registry["plans"] = plans
                _save_registry(registry)

    except Exception as e:
        logger.error(f"handle_plan_file_deleted failed for {path}: {e}", module=MODULE_NAME)


def handle_plan_file_moved(src_path: str, dest_path: str, **kwargs):
    """
    Handle PLAN file move/rename

    Args:
        src_path: Original path of the PLAN file
        dest_path: New path of the PLAN file
    """
    dest_file = Path(dest_path)
    plan_number = _get_plan_number(dest_file)

    if not plan_number:
        return

    try:
        registry = _load_registry()
        plans = registry.get("plans", {})

        if plan_number in plans:
            relative_path = str(dest_file.parent.relative_to(REPO_ROOT))

            # CRITICAL: Only update location fields, preserve ALL other metadata
            # (status, closed, closed_reason, memory_created, memory_created_date, etc.)
            plans[plan_number]["location"] = str(dest_file.parent)
            plans[plan_number]["relative_path"] = relative_path
            plans[plan_number]["file_path"] = str(dest_file)
            plans[plan_number]["last_updated"] = datetime.now(timezone.utc).isoformat()

            _save_registry(registry)

    except Exception as e:
        logger.error(f"handle_plan_file_moved failed for {src_path} -> {dest_path}: {e}", module=MODULE_NAME)
