# =================== AIPass ====================
# Name: process.py
# Description: Memory Processing Handler
# Version: 1.9.0
# Created: 2025-11-25
# Modified: 2026-10-26
# =============================================

"""
Memory Processing Handler
"""

from pathlib import Path

import shutil
from datetime import datetime, timezone
from typing import Dict, List, Any

from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.plan.project_scope import archive_dir_for
from aipass.flow.apps.handlers.registry.load_registry import load_registry
from aipass.flow.apps.handlers.registry.save_registry import registry_lock, save_registry
from aipass.flow.apps.handlers.repo_root import find_repo_root, module_file
from aipass.prax.apps.modules.logger import system_logger as logger

_PKG_ROOT = module_file(__file__).parents[4]

FLOW_ROOT = _PKG_ROOT / "flow"

MODULE_NAME = "mbank_process"


def _find_repo_root() -> Path:
    """Walk up to the repo root (the directory holding AIPASS_REGISTRY.json)."""
    return find_repo_root(caller="mbank_process")


_REPO_ROOT = _find_repo_root()
PROCESSED_PLANS_DIR = _REPO_ROOT / ".backup" / "processed_plans"
REGISTRY_FILE = FLOW_ROOT / "flow_json" / "fplan_registry.json"


def _get_all_registry_files() -> List[str]:
    """Return per-type registry filenames via plan-type discovery."""
    try:
        from aipass.flow.apps.handlers.template.plan_type_loader import discover_plan_types  # type: ignore[import-not-found]

        files: List[str] = []
        for _key, config in discover_plan_types().items():
            rf = config.get("registry_file")
            if rf and rf not in files:
                files.append(rf)
        if files:
            return files
    except Exception as exc:
        logger.warning("[mbank] Failed to discover plan types, falling back to default registry: %s", exc)
    return [REGISTRY_FILE.name]


def get_closed_plans() -> List[Dict[str, Any]]:
    """Get closed PLANs from ALL per-type registries."""
    verify_and_heal_orphaned_plans()
    closed_plans: List[Dict[str, Any]] = []
    for reg_file in _get_all_registry_files():
        try:
            registry = load_registry(registry_file=reg_file)
        except Exception as exc:
            logger.warning("[mbank] Failed to load registry '%s' while fetching closed plans: %s", reg_file, exc)
            continue
        for plan_num, plan_info in registry.get("plans", {}).items():
            if plan_info.get("status") == "closed" and plan_info.get("processed") is not True:
                file_path = Path(plan_info.get("file_path", ""))
                if file_path.exists():
                    closed_plans.append(
                        {
                            "number": plan_num,
                            "path": file_path,
                            "info": plan_info,
                            "registry_file": reg_file,
                        }
                    )
    return closed_plans


def is_template_content(content: str) -> bool:
    """Check if plan content is still unedited template (v5.0)

    Real-work signals (checked boxes, Notes, a non-boilerplate Execution Log) override bracket markers.
    """
    import re

    user_content_signals = [
        "- [x] Agent deployed",
        "- [x] Agent completed",
        "- [x] Seedgo checklist",
        "- [x] All goals achieved",
    ]
    for signal in user_content_signals:
        if signal in content:
            return False

    notes_match = re.search(r"## Notes\s*\n(.*?)(?=\n---|\n## |\Z)", content, re.DOTALL)
    if notes_match:
        notes_content = notes_match.group(1).strip()
        if notes_content and notes_content != "[Working notes, issues encountered, decisions made]":
            return False

    _exec_boilerplate = ["**Log Pattern:**", "[task]", "[outcome]", "[file]"]
    exec_match = re.search(r"## Execution Log\s*\n(.*?)(?=\n---|\n## |\Z)", content, re.DOTALL)
    if exec_match:
        exec_content = exec_match.group(1).strip()
        is_boilerplate = any(m in exec_content for m in _exec_boilerplate)
        if not is_boilerplate:
            lines = [line.strip() for line in exec_content.split("\n") if line.strip()]
            if len(lines) > 8:
                return False

    default_markers = [
        "[What do you want to achieve? Specific end state.]",
        "[How will agents tackle this? What instructions will they need?]",
        "[List any planning docs, specs, or examples to reference]",
        "[Working notes, issues encountered, decisions made]",
        "[What specifically defines complete for this plan?]",
    ]

    master_markers = [
        "[What this phase accomplishes]",
        "[What the agent will build]",
        "[Files/outputs expected]",
        "[What specifically defines the project complete?]",
        "[Patterns discovered that span multiple phases]",
    ]

    proposal_markers = [
        "[Clear description of the idea, feature, improvement, or fix]",
        "[Why is this valuable? What problem does it solve? What does it enable?]",
        "[How would I tackle this? High-level steps.]",
        "[Any other branches, services, or approvals needed?]",
    ]

    for markers in [default_markers, master_markers, proposal_markers]:
        found = sum(1 for m in markers if m in content)
        if found >= 3:
            return True

    return False


def archive_plan(plan_path: Path) -> bool:
    """Move a processed plan file into its own project's .backup/processed_plans/

    Returns True only when the destination exists and the source is gone.
    """
    try:
        archive_dir = archive_dir_for(Path(plan_path), PROCESSED_PLANS_DIR)
        archive_dir.mkdir(parents=True, exist_ok=True)

        destination = archive_dir / plan_path.name

        if destination.exists():
            timestamp = datetime.now().strftime("%H%M%S")
            stem = destination.stem
            suffix = destination.suffix
            destination = archive_dir / f"{stem}_{timestamp}{suffix}"

        source_path = Path(plan_path)

        # shutil.move, not rename: the archive may sit on another filesystem.
        shutil.move(str(plan_path), str(destination))

        if not destination.exists():
            return False

        if source_path.exists():
            return False

        return True

    except Exception as exc:
        logger.error("[mbank] Failed to archive plan '%s': %s", plan_path, exc)
        return False


def verify_and_heal_orphaned_plans() -> Dict[str, Any]:
    """Cross-check ALL registries vs filesystem and auto-heal orphaned plans."""
    orphans_found = 0
    successfully_healed = 0
    failed_to_heal = 0
    orphan_details: List[Dict[str, Any]] = []

    for reg_file in _get_all_registry_files():
        try:
            registry = load_registry(registry_file=reg_file)
        except Exception as exc:
            logger.warning("[mbank] Failed to load registry '%s' during orphan healing: %s", reg_file, exc)
            continue
        for plan_num, plan_info in registry.get("plans", {}).items():
            # Any closed plan, processed or not: auto-closed orphans never entered the post-close pipeline.
            if plan_info.get("status") == "closed":
                original_path = Path(plan_info.get("file_path", ""))
                if original_path.exists():
                    orphans_found += 1
                    plan_label = original_path.stem
                    if archive_plan(original_path):
                        successfully_healed += 1
                        orphan_details.append({"plan": plan_label, "status": "healed", "path": str(original_path)})
                    else:
                        failed_to_heal += 1
                        orphan_details.append({"plan": plan_label, "status": "heal_failed", "path": str(original_path)})

    return {
        "orphans_found": orphans_found,
        "successfully_healed": successfully_healed,
        "failed_to_heal": failed_to_heal,
        "orphans": orphan_details,
    }


def process_closed_plans() -> Dict[str, Any]:
    """Process all closed plans across all plan types.

    Processing: archive_plan() -> update registry flags -> vector processing (best effort)
    """
    try:
        closed_plans = get_closed_plans()
        if not closed_plans:
            return {"success": True, "processed": 0, "errors": 0, "results": []}

        processed_count = 0
        error_count = 0
        results: List[Dict[str, Any]] = []

        for plan in closed_plans:
            try:
                plan_path: Path = plan["path"]
                plan_num: str = plan["number"]
                reg_file: str = plan.get("registry_file", REGISTRY_FILE.name)
                plan_label = plan_path.stem
                correlation_id = f"{plan_label}-{datetime.now().strftime('%H%M%S')}"

                archive_success = archive_plan(plan_path)

                with registry_lock():
                    registry = load_registry(registry_file=reg_file)
                    if plan_num in registry.get("plans", {}):
                        registry["plans"][plan_num]["cleanup_completed"] = archive_success
                        registry["plans"][plan_num]["cleanup_date"] = datetime.now(timezone.utc).isoformat()
                        if archive_success:
                            registry["plans"][plan_num]["processed"] = True
                            registry["plans"][plan_num]["processed_date"] = datetime.now(timezone.utc).isoformat()
                        if not save_registry(registry, registry_file=reg_file):
                            raise OSError(f"could not save {reg_file}")

                if archive_success:
                    processed_count += 1
                    # Vector intake happens in post_close_runner, not here.
                    results.append({"plan": plan_label, "status": "archived", "correlation_id": correlation_id})
                else:
                    error_count += 1
                    results.append(
                        {
                            "plan": plan_label,
                            "status": "archive_failed",
                            "error": "Failed to move plan to backup/processed_plans/",
                            "correlation_id": correlation_id,
                        }
                    )
            except Exception as e:
                logger.error("[mbank] Error processing closed plan '%s': %s", plan.get("path", "unknown"), e)
                error_count += 1
                results.append({"plan": str(plan.get("path", "unknown")), "status": "error", "error": str(e)})

        json_handler.log_operation(
            "closed_plans_processed",
            {
                "processed": processed_count,
                "errors": error_count,
                "success": True,
            },
        )

        return {
            "success": True,
            "processed": processed_count,
            "errors": error_count,
            "results": results,
        }

    except Exception as e:
        logger.error("[mbank] Unexpected error in process_closed_plans: %s", e)
        return {"success": False, "processed": 0, "errors": 0, "results": [], "error": str(e)}
