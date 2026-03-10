# =================== AIPass ====================
# Name: process.py
# Description: Memory Bank Processing Handler
# Version: 1.5.0
# Created: 2025-11-25
# Modified: 2025-11-25
# =============================================

"""
Memory Bank Processing Handler

Handles archival of closed PLAN files to backup_system/processed_plans/.
AI summarization removed — plans vectorized directly from backup_system/processed_plans/.

Key Functions:
- process_closed_plans() - Main entry point: archive plan → update registry
- archive_plan() - Move to backup_system/processed_plans/
- is_template_content() - Template detection
- verify_and_heal_orphaned_plans() - Orphan healing logic
"""

from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parents[4]

# Standard imports
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

# AI summarization removed — OpenRouter API no longer needed here
# from aipass.api.apps.modules.openrouter_client import get_response

# =============================================
# CONSTANTS
# =============================================

FLOW_ROOT = _PKG_ROOT / "flow"
FLOW_JSON_DIR = FLOW_ROOT / "flow_json"
def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


_REPO_ROOT = _find_repo_root()
MEMORY_BANK_PATH = _REPO_ROOT / "MEMORY_BANK" / "plans"
PROCESSED_PLANS_DIR = _PKG_ROOT / "backup_system" / "processed_plans"
PRIVATE_BRANCH_REGISTRY = _REPO_ROOT / "PRIVATE_BRANCH_REGISTRY.json"
REGISTRY_FILE = FLOW_JSON_DIR / "flow_registry.json"
CONFIG_FILE = FLOW_JSON_DIR / "flow_mbank_config.json"
TRL_REGISTRY_FILE = FLOW_JSON_DIR / "flow_mbank_registry.json"
API_CONFIG_FILE = FLOW_ROOT / "apps" / "handlers" / "json_templates" / "custom" / "api_config.json"

# =============================================
# PRIVATE BRANCH HELPERS
# =============================================

def _is_branch_private(branch_name: str) -> bool:
    """Check if branch is in the private registry."""
    if not PRIVATE_BRANCH_REGISTRY.exists():
        return False
    try:
        with open(PRIVATE_BRANCH_REGISTRY, 'r', encoding='utf-8') as f:
            registry = json.load(f)
        for branch in registry.get("branches", []):
            if branch.get("name", "").upper() == branch_name.upper():
                return True
    except (json.JSONDecodeError, IOError):
        pass
    return False


def _get_private_branch_path(branch_name: str) -> Optional[str]:
    """Get the path of a private branch."""
    if not PRIVATE_BRANCH_REGISTRY.exists():
        return None
    try:
        with open(PRIVATE_BRANCH_REGISTRY, 'r', encoding='utf-8') as f:
            registry = json.load(f)
        for branch in registry.get("branches", []):
            if branch.get("name", "").upper() == branch_name.upper():
                return branch.get("path")
    except (json.JSONDecodeError, IOError):
        pass
    return None


def _get_private_branch_for_path(plan_path: Path) -> Optional[Dict[str, str]]:
    """Check if a plan path falls under a private branch.

    Args:
        plan_path: Absolute path to plan file

    Returns:
        Dict with 'name' and 'path' if private, None otherwise
    """
    if not PRIVATE_BRANCH_REGISTRY.exists():
        return None
    try:
        with open(PRIVATE_BRANCH_REGISTRY, 'r', encoding='utf-8') as f:
            registry = json.load(f)
        plan_str = str(plan_path.resolve())
        for branch in registry.get("branches", []):
            branch_path = branch.get("path", "")
            if branch_path and plan_str.startswith(branch_path):
                return {"name": branch.get("name", ""), "path": branch_path}
    except (json.JSONDecodeError, IOError):
        pass
    return None


# =============================================
# CONFIGURATION
# =============================================

def load_config() -> Dict[str, Any]:
    """Load flow_mbank configuration"""
    default_config = {
        "module_name": "flow_mbank",
        "version": "1.0.0",
        "config": {
            "enabled": True,
            "archive_processed": True
        }
    }

    if not CONFIG_FILE.exists():
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)
        return default_config

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise Exception(f"Failed to load config: {e}")

def load_trl_registry() -> Dict[str, Any]:
    """Load TRL mapping registry"""
    default_registry = {
        "module_name": "flow_mbank",
        "description": "TRL (Type-Category-Action) classification registry for memory bank processing",
        "version": "1.0.0",
        "trl_mapping": {
            "types": {
                "SEEDGO": "Seedgo AI System",
                "NEXUS": "Nexus AI System",
                "SKILL": "Skills Modules",
                "PRAX": "Prax Infrastructure",
                "FLOW": "Flow Workflow System",
                "BACKUP": "Backup System",
                "DRONE": "Drone Commands",
                "HELP": "Help System",
                "MCP": "MCP Servers",
                "TOOLS": "Tools & Scripts"
            },
            "categories": {
                "API": "API & External Services",
                "MEM": "Memory & Storage",
                "DB": "Database & Data",
                "UI": "User Interface",
                "CFG": "Configuration",
                "DOC": "Documentation",
                "TEST": "Testing & QA",
                "SEC": "Security",
                "NET": "Networking",
                "FILE": "File Operations",
                "LOG": "Logging & Monitoring",
                "DEV": "Development"
            },
            "actions": {
                "IMP": "Implementation",
                "FIX": "Bug Fixes",
                "UPD": "Updates & Improvements",
                "NEW": "New Features",
                "REF": "Refactoring",
                "DOC": "Documentation",
                "TEST": "Testing",
                "CFG": "Configuration",
                "MIGR": "Migration",
                "OPT": "Optimization"
            }
        },
        "excluded_paths": [
            "admin", "archive", "backups", "tests", "trash", "__pycache__",
            ".git", ".venv", "venv", "node_modules", "mcp_servers"
        ]
    }

    if not TRL_REGISTRY_FILE.exists():
        TRL_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TRL_REGISTRY_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_registry, f, indent=2, ensure_ascii=False)
        return default_registry

    try:
        with open(TRL_REGISTRY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise Exception(f"Failed to load TRL registry: {e}")

def get_ai_model() -> Optional[str]:
    """Get AI model from custom API config"""
    try:
        if API_CONFIG_FILE.exists():
            with open(API_CONFIG_FILE, 'r', encoding='utf-8') as f:
                api_config = json.load(f)
                return api_config.get("api_settings", {}).get("model")

        return None

    except Exception:
        return None

# =============================================
# REGISTRY OPERATIONS
# =============================================

def load_flow_registry() -> Dict[str, Any]:
    """Load the flow registry"""
    if not REGISTRY_FILE.exists():
        raise Exception(f"Flow registry not found at {REGISTRY_FILE}")

    try:
        with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise Exception(f"Failed to load flow registry: {e}")

def save_flow_registry(registry: Dict[str, Any]):
    """Save the flow registry"""
    try:
        registry["last_updated"] = datetime.now(timezone.utc).isoformat()
        with open(REGISTRY_FILE, 'w', encoding='utf-8') as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise Exception(f"Failed to save flow registry: {e}")

def get_closed_plans() -> List[Dict[str, Any]]:
    """Get closed PLANs from flow registry

    AUTO-HEAL: Before getting closed plans, verify and heal any orphaned plans

    Returns:
        List of dicts with keys: number, path, info
    """
    # AUTO-HEAL LAYER: Fix orphaned plans before processing new ones
    heal_result = verify_and_heal_orphaned_plans()

    registry = load_flow_registry()
    closed_plans = []

    for plan_num, plan_info in registry.get("plans", {}).items():
        if plan_info.get("status") == "closed" and plan_info.get("processed") != True:
            file_path = Path(plan_info.get("file_path", ""))
            if file_path.exists():
                closed_plans.append({
                    "number": plan_num,
                    "path": file_path,
                    "info": plan_info
                })

    return closed_plans

# =============================================
# TEMPLATE DETECTION
# =============================================

def is_template_content(content: str) -> bool:
    """Check if plan content is still unedited template (v4.0)

    Uses bracket placeholders only (not section headers) to detect untouched
    templates. Also checks for user-added content in key sections — if any
    real work was added, the plan is NOT a template even if placeholders remain.

    Args:
        content: Plan file content

    Returns:
        True if plan is essentially an untouched template
    """
    # User content indicators — if ANY of these are found, plan has real work
    user_content_signals = [
        "- [x] Agent deployed",       # Checked execution log item
        "- [x] Agent completed",       # Checked execution log item
        "- [x] Seedgo checklist",      # Checked completion item
        "- [x] All goals achieved",    # Checked completion item
    ]
    for signal in user_content_signals:
        if signal in content:
            return False

    # Check Notes section for user content (not just the placeholder)
    import re
    notes_match = re.search(r'## Notes\s*\n(.*?)(?=\n---|\n## |\Z)', content, re.DOTALL)
    if notes_match:
        notes_content = notes_match.group(1).strip()
        # If notes has content beyond the template placeholder, it's real work
        if notes_content and notes_content != "[Working notes, issues encountered, decisions made]":
            return False

    # Check Execution Log for user-added entries beyond template
    exec_match = re.search(r'## Execution Log\s*\n(.*?)(?=\n---|\n## |\Z)', content, re.DOTALL)
    if exec_match:
        exec_content = exec_match.group(1).strip()
        lines = [l.strip() for l in exec_content.split('\n') if l.strip()]
        # Template has ~6 lines (date header + checkbox items). More = user added content.
        if len(lines) > 8:
            return False

    # Bracket placeholders only (no section headers — those persist in real plans)
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

    # 3+ bracket placeholders from any type = template
    for markers in [default_markers, master_markers, proposal_markers]:
        found = sum(1 for m in markers if m in content)
        if found >= 3:
            return True

    return False

# =============================================
# CONTENT ANALYSIS (DISABLED)
# AI summarization removed — plans vectorized directly from backup_system/processed_plans/
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
# MEMORY BANK CREATION (DISABLED)
# AI summarization removed — plans vectorized directly from backup_system/processed_plans/
# =============================================

# def create_memory_entry(plan_path: Path, analysis: Dict[str, str]) -> Optional[Path]:
#     """Create memory bank entry from analyzed plan
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
#         filename = f"{folder_context}-{analysis['type']}-{analysis['category']}-{analysis['action']}-FPLAN-{plan_num}{template_suffix}-{today}.md"
#
#         filename = re.sub(r'[<>:"|?*]', '-', filename)
#         filename = re.sub(r'-+', '-', filename)
#
#         private_branch = _get_private_branch_for_path(plan_path)
#         if private_branch:
#             archive_dir = Path(private_branch["path"]) / ".archive" / "plans"
#             _private_archive_log = f"[mbank] Archiving plan locally for private branch: {private_branch['name']}"
#         else:
#             archive_dir = MEMORY_BANK_PATH
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
    """Move processed plan file to backup_system/processed_plans/

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

        # Attempt move
        plan_path.rename(destination)

        # VERIFICATION LAYER: Confirm move actually happened
        if not destination.exists():
            return False

        if source_path.exists():
            return False

        return True

    except Exception:
        return False

# =============================================
# TEMP FILE CLEANUP
# =============================================

def cleanup_temp_files() -> Dict[str, Any]:
    """Remove old -TEMP files from MEMORY_BANK (empty template plans)

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
        # Scan MEMORY_BANK/plans/ for files with -TEMP in name
        if MEMORY_BANK_PATH.exists():
            for temp_file in MEMORY_BANK_PATH.glob("*-TEMP-*.md"):
                files_found += 1

                try:
                    # Delete the TEMP file
                    temp_file.unlink()

                    # Verify deletion
                    if not temp_file.exists():
                        files_deleted += 1
                        details.append({
                            "file": temp_file.name,
                            "status": "deleted"
                        })
                    else:
                        failed_deletes += 1
                        details.append({
                            "file": temp_file.name,
                            "status": "delete_failed",
                            "error": "File still exists after deletion"
                        })

                except Exception as e:
                    failed_deletes += 1
                    details.append({
                        "file": temp_file.name,
                        "status": "delete_failed",
                        "error": str(e)
                    })

    except Exception as e:
        # Failed to scan directory
        return {
            "files_found": 0,
            "files_deleted": 0,
            "failed_deletes": 0,
            "details": [],
            "scan_error": str(e)
        }

    return {
        "files_found": files_found,
        "files_deleted": files_deleted,
        "failed_deletes": failed_deletes,
        "details": details
    }

# =============================================
# ORPHAN HEALING
# =============================================

def verify_and_heal_orphaned_plans() -> Dict[str, Any]:
    """Cross-check registry vs filesystem and auto-heal orphaned plans

    Detects plans where registry says processed=true but file still at original location.
    Attempts to move orphaned files to processed_plans/ directory.

    Returns:
        Dict with keys:
            - orphans_found: int
            - successfully_healed: int
            - failed_to_heal: int
            - orphans: list of plan details
    """
    registry = load_flow_registry()

    orphans_found = 0
    successfully_healed = 0
    failed_to_heal = 0
    orphan_details = []

    for plan_num, plan_info in registry.get("plans", {}).items():
        # Only check plans marked as processed
        if plan_info.get("processed") == True and plan_info.get("cleanup_completed") == True:
            original_path = Path(plan_info.get("file_path", ""))

            # VERIFICATION: Does file still exist at original location?
            if original_path.exists():
                # ORPHAN DETECTED
                orphans_found += 1

                # Attempt auto-heal by moving file now
                try:
                    PROCESSED_PLANS_DIR.mkdir(parents=True, exist_ok=True)
                    destination = PROCESSED_PLANS_DIR / original_path.name

                    # Handle duplicates
                    if destination.exists():
                        timestamp = datetime.now().strftime("%H%M%S")
                        stem = destination.stem
                        suffix = destination.suffix
                        destination = PROCESSED_PLANS_DIR / f"{stem}_{timestamp}{suffix}"

                    # Attempt move
                    original_path.rename(destination)

                    # Verify move
                    if destination.exists() and not original_path.exists():
                        successfully_healed += 1
                        orphan_details.append({
                            "plan": f"FPLAN-{plan_num}",
                            "status": "healed",
                            "original_path": str(original_path),
                            "destination": str(destination)
                        })
                    else:
                        failed_to_heal += 1
                        orphan_details.append({
                            "plan": f"FPLAN-{plan_num}",
                            "status": "heal_failed",
                            "error": "Verification failed after rename",
                            "path": str(original_path)
                        })

                except Exception as e:
                    failed_to_heal += 1
                    orphan_details.append({
                        "plan": f"FPLAN-{plan_num}",
                        "status": "heal_failed",
                        "error": str(e),
                        "path": str(original_path)
                    })

    return {
        "orphans_found": orphans_found,
        "successfully_healed": successfully_healed,
        "failed_to_heal": failed_to_heal,
        "orphans": orphan_details
    }

# =============================================
# MAIN PROCESSING
# =============================================

def process_closed_plans() -> Dict[str, Any]:
    """Main function to process all closed plans

    # AI summarization removed — plans vectorized directly from backup_system/processed_plans/
    # Processing is now: archive_plan() → update registry flags → done

    AUTO-HEAL: Cleans up old -TEMP files from MEMORY_BANK after processing

    Returns:
        Dict with keys:
            - success: bool
            - processed: int (successfully processed)
            - errors: int (failed)
            - results: list of per-plan results
            - error: str (if success=False)
            - cleanup: dict (TEMP file cleanup results)
    """
    try:
        # Get closed plans from registry (includes auto-heal)
        closed_plans = get_closed_plans()

        if not closed_plans:
            # No closed plans to process, but still run cleanup
            cleanup_result = cleanup_temp_files()
            return {
                "success": True,
                "processed": 0,
                "errors": 0,
                "results": [],
                "cleanup": cleanup_result
            }

        processed_count = 0
        error_count = 0
        results = []

        for plan in closed_plans:
            try:
                plan_path = plan["path"]
                plan_num = plan["number"]

                # Generate correlation ID for tracking
                correlation_id = f"FPLAN-{plan_num}-{datetime.now().strftime('%H%M%S')}"

                # Archive plan to backup_system/processed_plans/
                archive_success = archive_plan(plan_path)

                # Update registry flags
                registry = load_flow_registry()
                if plan_num in registry.get("plans", {}):
                    registry["plans"][plan_num]["cleanup_completed"] = archive_success
                    registry["plans"][plan_num]["cleanup_date"] = datetime.now(timezone.utc).isoformat()

                    if archive_success:
                        registry["plans"][plan_num]["processed"] = True
                        registry["plans"][plan_num]["processed_date"] = datetime.now(timezone.utc).isoformat()

                    save_flow_registry(registry)

                if archive_success:
                    processed_count += 1
                    results.append({
                        "plan": f"FPLAN-{plan_num}",
                        "status": "archived",
                        "correlation_id": correlation_id
                    })
                else:
                    error_count += 1
                    results.append({
                        "plan": f"FPLAN-{plan_num}",
                        "status": "archive_failed",
                        "error": "Failed to move plan to backup_system/processed_plans/",
                        "correlation_id": correlation_id
                    })

            except Exception as e:
                error_count += 1
                plan_num = plan.get('number', 'unknown')
                results.append({
                    "plan": f"FPLAN-{plan_num}",
                    "status": "error",
                    "error": str(e)
                })

        # AUTO-HEAL: Clean up old -TEMP files from MEMORY_BANK
        cleanup_result = cleanup_temp_files()

        return {
            "success": True,
            "processed": processed_count,
            "errors": error_count,
            "results": results,
            "cleanup": cleanup_result
        }

    except Exception as e:
        return {
            "success": False,
            "processed": 0,
            "errors": 0,
            "results": [],
            "error": str(e)
        }
