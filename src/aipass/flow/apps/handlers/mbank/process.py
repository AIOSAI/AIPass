# =================== AIPass ====================
# Name: process.py
# Description: Memory Processing Handler
# Version: 1.5.0
# Created: 2025-11-25
# Modified: 2025-11-25
# =============================================

"""
Memory Processing Handler

Handles archival of closed PLAN files to flow/processed_plans/.
AI summarization removed — plans vectorized directly from flow/processed_plans/.

Key Functions:
- process_closed_plans() - Main entry point: archive plan → update registry
- archive_plan() - Move to flow/processed_plans/
- is_template_content() - Template detection
- verify_and_heal_orphaned_plans() - Orphan healing logic
"""

# ruff: noqa: E402
from pathlib import Path

# Standard imports
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

# AI summarization removed — OpenRouter API no longer needed here
# from aipass.api.apps.modules.openrouter_client import get_response

# =============================================
# CONSTANTS
# =============================================

FLOW_ROOT = _PKG_ROOT / "flow"
FLOW_JSON_DIR = FLOW_ROOT / "flow_json"

MODULE_NAME = "mbank_process"
_LOCK_RETRIES = 10
_LOCK_BACKOFF_BASE = 0.05


def _acquire_lock(lock_path: Path) -> bool:
    """Atomically acquire a lockfile via O_CREAT|O_EXCL with retry+backoff."""
    for attempt in range(_LOCK_RETRIES):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            logger.info("[%s] Lock contention on %s, retry %d", MODULE_NAME, lock_path, attempt + 1)
            time.sleep(_LOCK_BACKOFF_BASE * (2**attempt))
        except OSError as exc:
            logger.warning("[%s] Lock creation failed for %s: %s", MODULE_NAME, lock_path, exc)
            return False
    return False


def _release_lock(lock_path: Path) -> None:
    """Remove lockfile, tolerating already-removed."""
    try:
        lock_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("[%s] Could not release lock %s: %s", MODULE_NAME, lock_path, exc)


def _find_repo_root() -> Path:
    """Walk up to the repo root (the directory holding AIPASS_REGISTRY.json).

    Delegates to ``handlers/repo_root.find_repo_root`` — the one
    implementation. This used to be a private copy ending
    ``return Path.cwd()``; there were seven such copies in flow and six of
    them are called at MODULE level, so on a registry-less checkout every
    import guessed its root from the process directory, and with the cwd
    deleted the import died outright. See that module's docstring.
    """
    return find_repo_root(caller="mbank_process")


_REPO_ROOT = _find_repo_root()
MEMORY_PATH = _REPO_ROOT / "src" / "aipass" / "memory"
PROCESSED_PLANS_DIR = _REPO_ROOT / ".backup" / "processed_plans"
REGISTRY_FILE = FLOW_JSON_DIR / "fplan_registry.json"

# =============================================
# PLAN TYPE HELPERS
# =============================================


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


# =============================================
# REGISTRY OPERATIONS
# =============================================


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
    """Get closed PLANs from ALL per-type registries.

    Returns:
        List of dicts with keys: number, path, info, registry_file
    """
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


# =============================================
# TEMPLATE DETECTION
# =============================================


def is_template_content(content: str) -> bool:
    """Check if plan content is still unedited template (v5.0)

    Priority order:
    1. User-content signals (checked checkboxes) — strongest evidence of
       real work, overrides everything.
    2. Real content in Notes section — overrides bracket markers.
    3. Non-boilerplate Execution Log entries — user-written entries
       override bracket markers; template boilerplate is ignored.
    4. Bracket-marker check — 3+ template placeholders = template.

    Args:
        content: Plan file content

    Returns:
        True if plan is essentially an untouched template
    """
    import re

    # --- 1. User content signals override everything ---
    user_content_signals = [
        "- [x] Agent deployed",
        "- [x] Agent completed",
        "- [x] Seedgo checklist",
        "- [x] All goals achieved",
    ]
    for signal in user_content_signals:
        if signal in content:
            return False

    # --- 2. Real Notes content → not template ---
    notes_match = re.search(r"## Notes\s*\n(.*?)(?=\n---|\n## |\Z)", content, re.DOTALL)
    if notes_match:
        notes_content = notes_match.group(1).strip()
        if notes_content and notes_content != "[Working notes, issues encountered, decisions made]":
            return False

    # --- 3. Non-boilerplate Exec Log entries → not template ---
    _exec_boilerplate = ["**Log Pattern:**", "[task]", "[outcome]", "[file]"]
    exec_match = re.search(r"## Execution Log\s*\n(.*?)(?=\n---|\n## |\Z)", content, re.DOTALL)
    if exec_match:
        exec_content = exec_match.group(1).strip()
        is_boilerplate = any(m in exec_content for m in _exec_boilerplate)
        if not is_boilerplate:
            lines = [line.strip() for line in exec_content.split("\n") if line.strip()]
            if len(lines) > 8:
                return False

    # --- 4. Bracket markers: 3+ from any type = template ---
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


# =============================================
# CONTENT ANALYSIS (DISABLED)
# AI summarization removed — plans vectorized directly from flow/processed_plans/
# =============================================

# def analyze_plan_content(plan_path: Path) -> Dict[str, str]:
#     """Use OpenRouter to analyze plan content and determine TRL tags
#
#     Args:
#         plan_path: Path to PLAN file
#
#     Returns:
#         Dict with keys: type, category, action, summary
#
#     Raises:
#         Exception: If API call fails or response is invalid
#     """
#     trl_registry = load_trl_registry()
#
#     # Read plan content
#     with open(plan_path, 'r', encoding='utf-8') as f:
#         content = f.read()
#
#     # Prepare analysis prompt
#     try:
#         relative_path = str(plan_path.relative_to(_PKG_ROOT))
#         folder_context = str(plan_path.parent.relative_to(_PKG_ROOT))
#     except ValueError:
#         relative_path = str(plan_path)
#         folder_context = str(plan_path.parent)
#
#     trl_mapping = trl_registry["trl_mapping"]
#
#     types_desc = "\n".join([f"{k}: {v}" for k, v in trl_mapping["types"].items()])
#     categories_desc = "\n".join([f"{k}: {v}" for k, v in trl_mapping["categories"].items()])
#     actions_desc = "\n".join([f"{k}: {v}" for k, v in trl_mapping["actions"].items()])
#
#     type_codes = "|".join(trl_mapping["types"].keys())
#     category_codes = "|".join(trl_mapping["categories"].keys())
#     action_codes = "|".join(trl_mapping["actions"].keys())
#
#     prompt = f"""Analyze this completed plan file:
#
# Content: {content}
# Folder: {folder_context}
# File: {plan_path.name}
#
# Determine the primary classification using these options:
#
# TYPE options:
# {types_desc}
#
# CATEGORY options:
# {categories_desc}
#
# ACTION options:
# {actions_desc}
#
# Return ONLY a JSON object:
# {{
#   "type": "{type_codes}",
#   "category": "{category_codes}",
#   "action": "{action_codes}",
#   "summary": "brief description"
# }}"""
#
#     ai_model = get_ai_model()
#     response = get_response(prompt, model=ai_model, caller="flow_mbank")
#
#     if response:
#         try:
#             response_str = response.get('content', '').strip()
#
#             if response_str.startswith("```json"):
#                 start = response_str.find("```json") + 7
#                 end = response_str.rfind("```")
#                 if end > start:
#                     response_str = response_str[start:end].strip()
#             elif response_str.startswith("```"):
#                 start = response_str.find("```") + 3
#                 end = response_str.rfind("```")
#                 if end > start:
#                     response_str = response_str[start:end].strip()
#
#             try:
#                 analysis = json.loads(response_str)
#             except json.JSONDecodeError as e:
#                 first_brace = response_str.find('{')
#                 last_brace = response_str.rfind('}')
#
#                 if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
#                     json_only = response_str[first_brace:last_brace + 1]
#                     try:
#                         analysis = json.loads(json_only)
#                     except json.JSONDecodeError:
#                         raise Exception(f"API returned invalid JSON: {e}")
#                 else:
#                     raise Exception(f"API returned invalid JSON: {e}")
#
#             required_fields = ['type', 'category', 'action', 'summary']
#             for field in required_fields:
#                 if field not in analysis:
#                     raise Exception(f"API response missing required field: {field}")
#
#             return analysis
#         except json.JSONDecodeError as e:
#             raise Exception(f"API returned invalid JSON: {e}")
#     else:
#         raise Exception("No response from OpenRouter API - check API key and connection")

# =============================================
# MEMORY ENTRY CREATION (DISABLED)
# AI summarization removed — plans vectorized directly from flow/processed_plans/
# =============================================

# def create_memory_entry(plan_path: Path, analysis: Dict[str, str]) -> Optional[Path]:
#     """Create @memory entry from analyzed plan
#
#     Args:
#         plan_path: Path to source PLAN file
#         analysis: Dict with type, category, action, summary
#
#     Returns:
#         Path to created memory file, or None on failure
#     """
#     try:
#         with open(plan_path, 'r', encoding='utf-8') as f:
#             content = f.read()
#
#         is_template = is_template_content(content)
#
#         try:
#             relative_path = plan_path.relative_to(_PKG_ROOT)
#             folder_context = str(relative_path.parent).replace("\\", "-").replace("/", "-")
#         except ValueError:
#             relative_path = plan_path
#             folder_context = str(plan_path.parent).replace("\\", "-").replace("/", "-")
#
#         if folder_context == "." or folder_context == "":
#             folder_context = "root"
#
#         today = datetime.now().strftime("%Y%m%d")
#         plan_num = plan_path.stem.replace("FPLAN-", "")
#         template_suffix = "-TEMP" if is_template else ""
#         filename = (
#             f"{folder_context}-{analysis['type']}-{analysis['category']}"
#             f"-{analysis['action']}-FPLAN-{plan_num}{template_suffix}-{today}.md"
#         )
#
#         filename = re.sub(r'[<>:"|?*]', '-', filename)
#         filename = re.sub(r'-+', '-', filename)
#
#         private_branch = _get_private_branch_for_path(plan_path)
#         if private_branch:
#             archive_dir = Path(private_branch["path"]) / ".archive" / "plans"
#             _private_archive_log = f"[mbank] Archiving plan locally for private branch: {private_branch['name']}"
#         else:
#             archive_dir = MEMORY_PATH
#             _private_archive_log = None
#
#         memory_file = archive_dir / filename
#         memory_file.parent.mkdir(parents=True, exist_ok=True)
#
#         if memory_file.exists():
#             return None
#
#         memory_content = f"""# {analysis['summary']}
#
# **Source**: {relative_path}
# **TRL Tags**: {analysis['type']}-{analysis['category']}-{analysis['action']}
# **Created**: {datetime.now().strftime('%Y-%m-%d')}
# **Location**: {relative_path.parent}
#
# ## Summary
# {analysis['summary']}
#
# ## Original Content
# {content}
# """
#
#         with open(memory_file, 'w', encoding='utf-8') as f:
#             f.write(memory_content)
#
#         return memory_file
#
#     except Exception as e:
#         raise Exception(f"Failed to create memory entry: {e}")

# =============================================
# PLAN ARCHIVAL
# =============================================


def archive_plan(plan_path: Path) -> bool:
    """Move processed plan file to flow/processed_plans/

    VERIFICATION: Returns True ONLY if file successfully moved AND verified

    Args:
        plan_path: Path to PLAN file to archive

    Returns:
        True if successfully archived and verified, False otherwise
    """
    try:
        # Create processed_plans directory if it doesn't exist
        PROCESSED_PLANS_DIR.mkdir(parents=True, exist_ok=True)

        # Move plan to processed_plans directory
        destination = PROCESSED_PLANS_DIR / plan_path.name

        # Handle duplicate names by adding timestamp
        if destination.exists():
            timestamp = datetime.now().strftime("%H%M%S")
            stem = destination.stem
            suffix = destination.suffix
            destination = PROCESSED_PLANS_DIR / f"{stem}_{timestamp}{suffix}"

        # Store source path for verification
        source_path = Path(plan_path)

        # Attempt move (shutil.move handles cross-filesystem moves)
        shutil.move(str(plan_path), str(destination))

        # VERIFICATION LAYER: Confirm move actually happened
        if not destination.exists():
            return False

        if source_path.exists():
            return False

        return True

    except Exception as exc:
        logger.error("[mbank] Failed to archive plan '%s': %s", plan_path, exc)
        return False


# =============================================
# TEMP FILE CLEANUP
# =============================================


def cleanup_temp_files() -> Dict[str, Any]:
    """Remove old -TEMP files from @memory (empty template plans)

    These files are created when empty template plans are closed and processed.
    They have no value and should be auto-cleaned.

    Returns:
        Dict with keys:
            - files_found: int
            - files_deleted: int
            - failed_deletes: int
            - details: list of file operations
    """
    files_found = 0
    files_deleted = 0
    failed_deletes = 0
    details = []

    try:
        # Scan @memory for files with -TEMP in name
        if MEMORY_PATH.exists():
            for temp_file in MEMORY_PATH.glob("*-TEMP-*.md"):
                files_found += 1

                try:
                    # Delete the TEMP file
                    temp_file.unlink()

                    # Verify deletion
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
        # Failed to scan directory
        logger.error("[mbank] Failed to scan @memory for temp files: %s", e)
        return {"files_found": 0, "files_deleted": 0, "failed_deletes": 0, "details": [], "scan_error": str(e)}

    return {
        "files_found": files_found,
        "files_deleted": files_deleted,
        "failed_deletes": failed_deletes,
        "details": details,
    }


# =============================================
# ORPHAN HEALING
# =============================================


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
            # Heal ANY closed plan whose file still sits at its original location.
            # Covers both fully-processed plans and auto-closed orphans that
            # never entered the post-close pipeline.
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


# =============================================
# MAIN PROCESSING
# =============================================


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
                    # Vector intake triggered by post_close_runner via direct import
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
