# =================== AIPass ====================
# Name: process.py
# Description: Memory Processing Handler
# Version: 1.7.0
# Created: 2025-11-25
# Modified: 2026-10-17
# =============================================

"""
Memory Processing Handler
"""

from pathlib import Path

import json
import os
import shutil
import time
from datetime import datetime, timezone
from typing import Dict, List, Any

from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.repo_root import find_repo_root, module_file
from aipass.prax.apps.modules.logger import system_logger as logger

_PKG_ROOT = module_file(__file__).parents[4]

FLOW_ROOT = _PKG_ROOT / "flow"
FLOW_JSON_DIR = FLOW_ROOT / "flow_json"

MODULE_NAME = "mbank_process"
_LOCK_RETRIES = 10
_LOCK_BACKOFF_BASE = 0.05


def _sleep(seconds: float) -> None:
    """time.sleep(seconds), the lock backoff's wait.

    Tests patch this name so the backoff skips waiting without patching time.sleep globally.
    """
    time.sleep(seconds)


def _create_exclusive(lock_path: Path) -> int:
    """os.open(lock_path, O_CREAT | O_EXCL | O_WRONLY): the lock's one create.

    Tests inject Windows' delete-pending PermissionError here instead of patching os.open.
    """
    return os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)


def _acquire_lock(lock_path: Path) -> bool:
    """Atomically acquire a lockfile via O_CREAT|O_EXCL with retry+backoff.

    Returns: True once acquired; False only when the budget runs out on contention.
    Raises: PermissionError (chained) if the last attempt was denied; any other OSError at once.
    """
    denial: PermissionError | None = None
    waited = 0.0
    for attempt in range(_LOCK_RETRIES):
        try:
            fd = _create_exclusive(lock_path)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            denial = None
            logger.info("[%s] Lock contention on %s, retry %d", MODULE_NAME, lock_path, attempt + 1)
        except PermissionError as exc:
            denial = exc
            logger.info(
                "[%s] Lock denied on %s (delete-pending?), retry %d: %s", MODULE_NAME, lock_path, attempt + 1, exc
            )
        except OSError as exc:
            # False would read as a spent retry budget, so other OSErrors propagate.
            logger.warning("[%s] Lock creation failed for %s: %s", MODULE_NAME, lock_path, exc)
            raise
        delay = _LOCK_BACKOFF_BASE * (2**attempt)
        _sleep(delay)
        waited += delay
    if denial is not None:
        raise PermissionError(
            f"Lock {lock_path} still denied after {_LOCK_RETRIES} attempts ({waited:.2f}s waited)"
        ) from denial
    return False


def _release_lock(lock_path: Path) -> None:
    """Remove lockfile, tolerating already-removed."""
    try:
        lock_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("[%s] Could not release lock %s: %s", MODULE_NAME, lock_path, exc)


def _find_repo_root() -> Path:
    """Walk up to the repo root (the directory holding AIPASS_REGISTRY.json)."""
    return find_repo_root(caller="mbank_process")


_REPO_ROOT = _find_repo_root()
MEMORY_PATH = _REPO_ROOT / "src" / "aipass" / "memory"
PROCESSED_PLANS_DIR = _REPO_ROOT / ".backup" / "processed_plans"
REGISTRY_FILE = FLOW_JSON_DIR / "fplan_registry.json"


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


def load_flow_registry(registry_file: str | None = None) -> Dict[str, Any]:
    """Load a plan registry."""
    target = FLOW_JSON_DIR / registry_file if registry_file else REGISTRY_FILE
    if not target.exists():
        raise Exception(f"Flow registry not found at {target}")
    try:
        with open(target, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise Exception(f"Failed to load flow registry: {e}")


def save_flow_registry(registry: Dict[str, Any], registry_file: str | None = None) -> None:
    """Save a plan registry with lockfile + atomic write."""
    target = FLOW_JSON_DIR / registry_file if registry_file else REGISTRY_FILE
    lock_path = target.with_suffix(".lock")

    try:
        if not _acquire_lock(lock_path):
            raise OSError(f"Could not acquire lock for {target}")

        try:
            registry["last_updated"] = datetime.now(timezone.utc).isoformat()
            tmp_path = target.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(registry, f, indent=2, ensure_ascii=False)
            os.replace(str(tmp_path), str(target))
        finally:
            _release_lock(lock_path)
    except Exception as e:
        raise Exception(f"Failed to save flow registry: {e}")


def get_closed_plans() -> List[Dict[str, Any]]:
    """Get closed PLANs from ALL per-type registries."""
    verify_and_heal_orphaned_plans()
    closed_plans: List[Dict[str, Any]] = []
    for reg_file in _get_all_registry_files():
        try:
            registry = load_flow_registry(registry_file=reg_file)
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
    """Move processed plan file to flow/processed_plans/

    Returns True only when the destination exists and the source is gone.
    """
    try:
        PROCESSED_PLANS_DIR.mkdir(parents=True, exist_ok=True)

        destination = PROCESSED_PLANS_DIR / plan_path.name

        if destination.exists():
            timestamp = datetime.now().strftime("%H%M%S")
            stem = destination.stem
            suffix = destination.suffix
            destination = PROCESSED_PLANS_DIR / f"{stem}_{timestamp}{suffix}"

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


def cleanup_temp_files() -> Dict[str, Any]:
    """Remove old -TEMP files from @memory (empty template plans)"""
    files_found = 0
    files_deleted = 0
    failed_deletes = 0
    details = []

    try:
        if MEMORY_PATH.exists():
            for temp_file in MEMORY_PATH.glob("*-TEMP-*.md"):
                files_found += 1

                try:
                    temp_file.unlink()

                    if not temp_file.exists():
                        files_deleted += 1
                        details.append({"file": temp_file.name, "status": "deleted"})
                    else:
                        failed_deletes += 1
                        details.append(
                            {
                                "file": temp_file.name,
                                "status": "delete_failed",
                                "error": "File still exists after deletion",
                            }
                        )

                except Exception as e:
                    logger.warning("[mbank] Failed to delete temp file '%s': %s", temp_file.name, e)
                    failed_deletes += 1
                    details.append({"file": temp_file.name, "status": "delete_failed", "error": str(e)})

    except Exception as e:
        logger.error("[mbank] Failed to scan @memory for temp files: %s", e)
        return {"files_found": 0, "files_deleted": 0, "failed_deletes": 0, "details": [], "scan_error": str(e)}

    return {
        "files_found": files_found,
        "files_deleted": files_deleted,
        "failed_deletes": failed_deletes,
        "details": details,
    }


def verify_and_heal_orphaned_plans() -> Dict[str, Any]:
    """Cross-check ALL registries vs filesystem and auto-heal orphaned plans."""
    orphans_found = 0
    successfully_healed = 0
    failed_to_heal = 0
    orphan_details: List[Dict[str, Any]] = []

    for reg_file in _get_all_registry_files():
        try:
            registry = load_flow_registry(registry_file=reg_file)
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
                    try:
                        PROCESSED_PLANS_DIR.mkdir(parents=True, exist_ok=True)
                        destination = PROCESSED_PLANS_DIR / original_path.name
                        if destination.exists():
                            timestamp = datetime.now().strftime("%H%M%S")
                            destination = PROCESSED_PLANS_DIR / f"{destination.stem}_{timestamp}{destination.suffix}"
                        original_path.rename(destination)
                        if destination.exists() and not original_path.exists():
                            successfully_healed += 1
                            orphan_details.append(
                                {
                                    "plan": plan_label,
                                    "status": "healed",
                                    "original_path": str(original_path),
                                    "destination": str(destination),
                                }
                            )
                        else:
                            failed_to_heal += 1
                            orphan_details.append(
                                {
                                    "plan": plan_label,
                                    "status": "heal_failed",
                                    "error": "Verification failed",
                                    "path": str(original_path),
                                }
                            )
                    except Exception as e:
                        logger.warning("[mbank] Failed to heal orphaned plan '%s': %s", plan_label, e)
                        failed_to_heal += 1
                        orphan_details.append(
                            {"plan": plan_label, "status": "heal_failed", "error": str(e), "path": str(original_path)}
                        )

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
            cleanup_result = cleanup_temp_files()
            return {"success": True, "processed": 0, "errors": 0, "results": [], "cleanup": cleanup_result}

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

                registry = load_flow_registry(registry_file=reg_file)
                if plan_num in registry.get("plans", {}):
                    registry["plans"][plan_num]["cleanup_completed"] = archive_success
                    registry["plans"][plan_num]["cleanup_date"] = datetime.now(timezone.utc).isoformat()
                    if archive_success:
                        registry["plans"][plan_num]["processed"] = True
                        registry["plans"][plan_num]["processed_date"] = datetime.now(timezone.utc).isoformat()
                    save_flow_registry(registry, registry_file=reg_file)

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

        cleanup_result = cleanup_temp_files()

        json_handler.log_operation(
            "closed_plans_processed",
            {
                "processed": processed_count,
                "errors": error_count,
                "cleanup_deleted": cleanup_result.get("files_deleted", 0),
                "success": True,
            },
        )

        return {
            "success": True,
            "processed": processed_count,
            "errors": error_count,
            "results": results,
            "cleanup": cleanup_result,
        }

    except Exception as e:
        logger.error("[mbank] Unexpected error in process_closed_plans: %s", e)
        return {"success": False, "processed": 0, "errors": 0, "results": [], "error": str(e)}
