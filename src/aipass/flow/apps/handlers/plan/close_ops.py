# =================== AIPass ====================
# Name: close_ops.py
# Description: Plan Closure Implementation Handler
# Version: 1.1.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Plan Closure Operations Handler

Implements plan closure business logic, extracted from close_plan module.
Handles single plan closure workflow and bulk close-all operations.

Returns data dicts - module handles all display.

Usage:
    from aipass.flow.apps.handlers.plan.close_ops import close_plan_impl, close_all_plans_impl
"""

import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable, Dict, Any, List, Tuple

from aipass.prax import logger
# logger imported from aipass.prax
from aipass.flow.apps.handlers.json import json_handler

# =============================================
# INFRASTRUCTURE
# =============================================

_PKG_ROOT = Path(__file__).resolve().parents[4]  # handlers/plan/ -> handlers/ -> apps/ -> flow/ -> aipass/
FLOW_ROOT = _PKG_ROOT / "flow"

MODULE_NAME = "close_plan"

# =============================================
# PLAN TYPE ROUTING
# =============================================


def _extract_prefix(plan_num_raw: str) -> str | None:
    """Extract plan-type prefix (e.g. ``"DPLAN"``) from raw input."""
    import re
    m = re.match(r'^([A-Z]+PLAN)-', plan_num_raw.strip(), re.IGNORECASE)
    return m.group(1).upper() if m else None


def _resolve_registry_file(plan_num_raw: str) -> str | None:
    """Resolve registry_file from a raw plan number with prefix.

    Returns registry filename or None if no prefix detected.
    """
    prefix = _extract_prefix(plan_num_raw)
    if prefix is None:
        return None
    try:
        from aipass.flow.apps.handlers.template.plan_type_loader import get_plan_type  # type: ignore[import-not-found]
        config = get_plan_type(prefix)
        return config.get("registry_file")
    except Exception:
        return None


def _find_plan_across_registries(plan_key: str, load_registry_fn: Any) -> str | None:
    """Search all registries for a plan number when no prefix given.

    Returns registry filename where the plan was found, or None.
    """
    try:
        from aipass.flow.apps.handlers.template.plan_type_loader import discover_plan_types  # type: ignore[import-not-found]
        for _type_key, config in discover_plan_types().items():
            reg_file = config.get("registry_file")
            if not reg_file:
                continue
            try:
                registry = load_registry_fn(registry_file=reg_file)
                if plan_key in registry.get("plans", {}):
                    return reg_file
            except Exception:
                continue
    except Exception:
        pass
    return None


# =============================================
# HELPER
# =============================================

def _spawn_background_runner():
    """Spawn post_close_runner.py as a fully detached background process"""
    bg_runner = FLOW_ROOT / "apps" / "modules" / "post_close_runner.py"
    subprocess.Popen(
        [sys.executable, str(bg_runner)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )


# =============================================
# CLOSE PLAN IMPLEMENTATION
# =============================================

def close_plan_impl(plan_num: Any = None, confirm: bool = False,
                    all_plans: bool = False, spawn_background: bool = True,
                    dry_run: bool = False,
                    # Dependencies injected from module
                    normalize_plan_number: Any = None,
                    load_registry: Any = None,
                    save_registry: Any = None,
                    validate_plan_exists: Any = None,
                    confirm_plan_deletion: Any = None,
                    is_template_content: Any = None,
                    update_dashboard_local: Any = None,
                    push_to_plans_central: Any = None,
                    push_flow_to_branch_dashboard: Any = None,
                    close_all_plans_fn: Any = None) -> Dict[str, Any]:
    """
    Implement plan closure workflow

    Auto-confirms by default - running 'close' IS the intent.
    Use confirm=True (--confirm/--interactive) to explicitly request a prompt.

    Args:
        plan_num: Plan number (e.g., "0001" or "1" or "42") - required if all_plans=False
        confirm: Whether to ask for confirmation (default False, auto-confirms)
        all_plans: If True, close all open plans (default False)
        spawn_background: Whether to spawn background post-processing (default True).
                          Set False when called from close_all_plans() to avoid race condition.
        dry_run: If True, preview what would be closed without taking action (default False)
        (remaining args): Handler/service dependencies injected by module

    Returns:
        Dict with keys: success (bool), messages (list of dicts with type/text),
        plan_key (str), cancelled (bool)
    """
    messages: List[Dict[str, Any]] = []

    # Handle --all flag
    if all_plans:
        return close_all_plans_fn(confirm, dry_run=dry_run)

    # Single plan closure
    if not plan_num:
        logger.warning(f"[{MODULE_NAME}] Plan number required for single plan closure")
        return {
            "success": False,
            "messages": [{"type": "error", "text": "invalid_number", "plan_num": ""}],
            "plan_key": "",
            "cancelled": False,
        }

    try:
        # --- Internal validation (fast, no progress display) ---

        # 1. VALIDATE: Normalize plan number (handler)
        plan_key = normalize_plan_number(plan_num)

        # 2. LOAD DATA: Detect correct registry from prefix, then load
        reg_file = _resolve_registry_file(plan_num)
        if reg_file:
            registry = load_registry(registry_file=reg_file)
        else:
            # No prefix -- try default registry first
            registry = load_registry()
            exists_default, _ = validate_plan_exists(plan_key, registry)
            if not exists_default:
                # Search other registries
                found_reg = _find_plan_across_registries(plan_key, load_registry)
                if found_reg:
                    reg_file = found_reg
                    registry = load_registry(registry_file=reg_file)

        # 3. VALIDATE: Check plan exists (handler)
        exists, error_msg = validate_plan_exists(plan_key, registry)
        if not exists:
            logger.warning(f"[{MODULE_NAME}] {error_msg}")
            return {
                "success": False,
                "messages": [{"type": "error", "text": "not_found", "plan_num": plan_key}],
                "plan_key": plan_key,
                "cancelled": False,
            }

        plan_info = registry["plans"][plan_key]
        plan_file = Path(plan_info.get("file_path", ""))

        # Derive display label from filename (e.g. "FPLAN-0079" or "DPLAN-0004")
        plan_label = plan_file.stem if plan_file.name else f"PLAN-{plan_key}"

        # Extract prefix for display functions (e.g. "FPLAN", "DPLAN")
        plan_prefix = _extract_prefix(plan_label) or "FPLAN"

        # DRY RUN: Preview what would be closed, then return early
        if dry_run:
            location = plan_info.get("location", "unknown")
            subject = plan_info.get("subject", "No subject")
            status = plan_info.get("status", "unknown")
            messages.append({"type": "dim", "text": f"[DRY RUN] Would close {plan_label}"})
            messages.append({"type": "dim", "text": f"  Location: {location}"})
            messages.append({"type": "dim", "text": f"  Subject:  {subject}"})
            messages.append({"type": "dim", "text": f"  Status:   {status}"})
            messages.append({"type": "dim", "text": "No action taken."})
            logger.info(f"[{MODULE_NAME}] Dry run: would close {plan_label}")
            return {
                "success": True,
                "messages": messages,
                "plan_key": plan_key,
                "cancelled": False,
            }

        # 4. IDEMPOTENCY CHECK: Prevent double-closing (with orphan cleanup)
        if plan_info['status'] == 'closed':
            closed_date = plan_info.get('closed', 'unknown')

            # Check if .md file is orphaned on disk (registry-closed but file never moved)
            if plan_file.exists():
                messages.append({"type": "warning", "text": f"{plan_label} already closed on {closed_date} — orphaned .md file detected"})
                messages.append({"type": "dim", "text": f"  Cleaning up: moving {plan_file.name} to processed_plans/"})
                try:
                    from aipass.flow.apps.handlers.mbank.process import archive_plan
                    if archive_plan(plan_file):
                        logger.info(f"[{MODULE_NAME}] Cleaned up orphaned file for {plan_label}: {plan_file}")
                        messages.append({"type": "success", "text": "  Orphaned file archived successfully"})
                    else:
                        logger.warning(f"[{MODULE_NAME}] Failed to archive orphaned file for {plan_label}: {plan_file}")
                        messages.append({"type": "error_text", "text": "  Failed to move orphaned file — manual cleanup required"})
                except Exception as e:
                    logger.warning(f"[{MODULE_NAME}] Error cleaning orphaned file for {plan_label}: {e}")
                    messages.append({"type": "error_text", "text": f"  Error during cleanup: {e}"})
                return {
                    "success": True,
                    "messages": messages,
                    "plan_key": plan_key,
                    "cancelled": False,
                }

            messages.append({"type": "warning", "text": f"{plan_label} already closed on {closed_date}"})
            messages.append({"type": "dim", "text": "Nothing to do - plan is already archived"})
            return {
                "success": False,
                "messages": messages,
                "plan_key": plan_key,
                "cancelled": False,
            }

        # --- Step 1/5: Template check (may fast-delete) ---
        messages.append({"type": "step", "text": "[1/5] Checking template status..."})
        try:
            with open(plan_file, 'r', encoding='utf-8') as f:
                content = f.read()

            if is_template_content(content):
                messages.append({"type": "warning", "text": f"  {plan_label} is empty template - fast-deleting (not archiving)"})

                # Delete the file
                plan_file.unlink()
                logger.info(f"[{MODULE_NAME}] Deleted empty template file: {plan_file}")

                # Remove from registry and save to correct per-type registry
                del registry["plans"][plan_key]
                if reg_file:
                    save_registry(registry, registry_file=reg_file)
                else:
                    save_registry(registry)
                logger.info(f"[{MODULE_NAME}] Removed {plan_label} from registry")

                messages.append({"type": "success", "text": f"  Empty template deleted - {plan_label} removed from system"})
                return {
                    "success": True,
                    "messages": messages,
                    "plan_key": plan_key,
                    "cancelled": False,
                }

        except FileNotFoundError as e:
            logger.warning(f"[{MODULE_NAME}] Template check - file not found: {e}")
            messages.append({"type": "warning", "text": "  Plan file not found, continuing with registry close"})
        except Exception as e:
            logger.warning(f"[{MODULE_NAME}] Template check failed: {e}")
            messages.append({"type": "warning", "text": "  Could not check template status, continuing with normal close"})

        # DISPLAY: plan info header
        messages.append({"type": "header", "plan_key": plan_key, "plan_info": plan_info, "prefix": plan_prefix})

        # CONFIRM: Ask user only if explicitly requested (--confirm/--interactive)
        if confirm:
            if not confirm_plan_deletion(plan_key):
                logger.info(f"[{MODULE_NAME}] Closure cancelled by user for PLAN{plan_key}")
                return {
                    "success": False,
                    "messages": messages + [{"type": "cancelled"}],
                    "plan_key": plan_key,
                    "cancelled": True,
                }

        # --- Step 2/5: Mark as closed ---
        messages.append({"type": "step", "text": "[2/5] Marking plan as closed..."})
        try:
            # CRITICAL: Close ALWAYS succeeds from this point. Archive is non-blocking.
            plan_info['status'] = 'closed'
            plan_info['closed'] = datetime.now(timezone.utc).isoformat()
            if reg_file:
                save_registry(registry, registry_file=reg_file)
            else:
                save_registry(registry)
            logger.info(f"[{MODULE_NAME}] Marked {plan_label} as closed")
        except Exception as e:
            logger.error(f"[{MODULE_NAME}] Failed to mark plan as closed: {e}")
            messages.append({"type": "error_text", "text": f"  Failed to update registry: {e}"})
            return {
                "success": False,
                "messages": messages,
                "plan_key": plan_key,
                "cancelled": False,
            }

        # --- Step 3/5: Archive plan to processed_plans ---
        messages.append({"type": "step", "text": "[3/5] Archiving plan..."})
        try:
            from aipass.flow.apps.handlers.mbank.process import archive_plan
            archive_success = archive_plan(plan_file)
            if archive_success:
                # Set flags on same registry object we already have in memory
                plan_info["processed"] = True
                plan_info["processed_date"] = datetime.now(timezone.utc).isoformat()
                plan_info["cleanup_completed"] = True
                plan_info["cleanup_date"] = datetime.now(timezone.utc).isoformat()
                if reg_file:
                    save_registry(registry, registry_file=reg_file)
                else:
                    save_registry(registry)
                logger.info(f"[{MODULE_NAME}] Archived {plan_label} to processed_plans")
                messages.append({"type": "dim", "text": "  Plan archived to processed_plans/"})
            else:
                logger.error(f"[{MODULE_NAME}] Failed to archive {plan_label}")
                messages.append({"type": "warning", "text": "  Archive failed — plan file not moved"})
        except Exception as e:
            logger.error(f"[{MODULE_NAME}] Archive error for {plan_label}: {e}")
            messages.append({"type": "warning", "text": f"  Archive error: {e}"})

        # --- Vector intake + verification ---
        # Trigger memory's plan processor via drone (no cross-branch imports)
        try:
            subprocess.run(
                ["drone", "@memory", "process-plans"],
                capture_output=True, timeout=30,
            )
        except Exception:
            pass  # Best effort — verification below reports actual status

        # Verify vectorization via memory's verify module
        try:
            from aipass.memory.apps.modules.verify import is_plan_vectorized  # type: ignore[import-not-found]
            result = is_plan_vectorized(plan_label)
            if result.get("found"):
                chunk_count = result.get("count", 0)
                logger.info(f"[{MODULE_NAME}] Vectorized: {plan_label} ({chunk_count} chunks)")
                messages.append({"type": "dim", "text": f"  Vectorized: {chunk_count} chunks in chroma"})
            else:
                logger.warning(f"[{MODULE_NAME}] NOT vectorized: {plan_label}")
                messages.append({"type": "warning", "text": "  NOT vectorized — check drone @memory process-plans"})
        except ImportError:
            logger.warning(f"[{MODULE_NAME}] Vector verify unavailable — memory verify module not found")
            messages.append({"type": "warning", "text": "  Vector status: unknown (memory verify not available)"})
        except Exception as vec_err:
            logger.warning(f"[{MODULE_NAME}] Vector verify failed: {vec_err}")
            messages.append({"type": "warning", "text": f"  Vector status: unknown ({vec_err})"})

        # --- Step 4/5: Update dashboards ---
        messages.append({"type": "step", "text": "[4/5] Updating dashboards..."})
        try:
            dashboard_success = update_dashboard_local()
            central_success = push_to_plans_central()

            # Log dashboard update results (3-tier: modules log, handlers don't)
            if not dashboard_success:
                logger.warning(f"[{MODULE_NAME}] Failed to update DASHBOARD.local.json")
            if not central_success:
                logger.warning(f"[{MODULE_NAME}] Failed to update PLANS.central.json")

            # Push flow section to branch's dashboard via write-through
            plan_location = plan_info.get("location", "")
            if plan_location:
                branch_dashboard_success = push_flow_to_branch_dashboard(Path(plan_location))
                if not branch_dashboard_success:
                    logger.warning(f"[{MODULE_NAME}] Failed to push flow section to branch dashboard at {plan_location}")
        except Exception as e:
            logger.warning(f"[{MODULE_NAME}] Dashboard update error: {e}")
            messages.append({"type": "warning", "text": f"  Dashboard update failed (non-critical): {e}"})

        # --- Step 5/5: Done ---
        messages.append({"type": "step", "text": "[5/5] Finalizing..."})
        messages.append({"type": "close_success", "plan_key": plan_key, "prefix": plan_prefix})

        # Append to branch's CLOSED_PLANS.local.json
        try:
            from aipass.flow.apps.handlers.plan.append_closed_plan import append_to_closed_plans
            append_to_closed_plans(plan_key, plan_info, plan_file.parent)
        except Exception as e:
            logger.warning(f"[{MODULE_NAME}] CLOSED_PLANS update failed (non-critical): {e}")

        # Fire trigger event for plan closure
        try:
            from aipass.trigger.apps.modules.core import trigger
            trigger.fire('plan_closed', plan_number=plan_key, location=str(plan_file.parent))
        except ImportError:
            logger.info(f"[{MODULE_NAME}] Trigger module not available, skipping event fire")
        except Exception as e:
            logger.warning(f"[{MODULE_NAME}] Trigger fire failed (non-critical): {e}")

        json_handler.log_operation("plan_closed", {"plan_key": plan_key, "success": True})
        return {
            "success": True,
            "messages": messages,
            "plan_key": plan_key,
            "cancelled": False,
        }

    except ValueError as e:
        logger.warning(f"[{MODULE_NAME}] Invalid plan number: {plan_num}: {e}")
        return {
            "success": False,
            "messages": [{"type": "error", "text": "invalid_number", "plan_num": plan_num}],
            "plan_key": "",
            "cancelled": False,
        }

    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Unexpected error closing plan: {e}")
        return {
            "success": False,
            "messages": [{"type": "error", "text": "general", "details": str(e)}],
            "plan_key": "",
            "cancelled": False,
        }


def close_all_plans_impl(confirm: bool = False, dry_run: bool = False,
                         # Dependencies injected from module
                         get_open_plans: Any = None,
                         close_plan_fn: Any = None) -> Dict[str, Any]:
    """
    Close all open plans in one operation

    Args:
        confirm: Whether to ask for bulk confirmation (default False, auto-confirms)
        dry_run: If True, preview what would be closed without taking action (default False)
        get_open_plans: Handler function to get open plans
        close_plan_fn: Function to close a single plan (the module's close_plan)

    Returns:
        Dict with keys: success (bool), messages (list), success_count, failure_count, total
    """
    messages: List[Dict[str, Any]] = []

    try:
        # Get all open plans (handler)
        open_plans = get_open_plans()

        if not open_plans:
            logger.info(f"[{MODULE_NAME}] close_all: No open plans found")
            return {
                "success": False,
                "messages": [{"type": "warning", "text": "No open plans to close"}],
                "success_count": 0,
                "failure_count": 0,
                "total": 0,
            }

        # DRY RUN: Preview all plans that would be closed, then return early
        if dry_run:
            messages.append({"type": "dim", "text": f"[DRY RUN] Would close {len(open_plans)} plan(s):"})
            for plan_num, plan_info in open_plans:
                subject = plan_info.get("subject", "No subject")
                location = plan_info.get("location", "unknown")
                # Derive prefix from file_path if available
                plan_file = Path(plan_info.get("file_path", ""))
                plan_label = plan_file.stem if plan_file.name else f"PLAN-{plan_num}"
                prefix = _extract_prefix(plan_label) or "FPLAN"
                display_id = f"{prefix}-{plan_num}"
                messages.append({"type": "dim", "text": f"  {display_id:<14}{location:<14}{subject}"})
            messages.append({"type": "dim", "text": "No action taken."})
            logger.info(f"[{MODULE_NAME}] Dry run: would close {len(open_plans)} plan(s)")
            return {
                "success": True,
                "messages": messages,
                "success_count": 0,
                "failure_count": 0,
                "total": len(open_plans),
            }

        # Build plan list for display
        plan_list = []
        for plan_num, plan_info in open_plans:
            subject = plan_info.get("subject", "No subject")
            plan_list.append({"plan_num": plan_num, "subject": subject})

        messages.append({"type": "plan_list", "count": len(open_plans), "plans": plan_list})

        # Confirm bulk close
        if confirm:
            messages.append({"type": "confirm_warning", "count": len(open_plans)})

            # Auto-confirm in non-interactive environments (autonomous workflows)
            if not sys.stdin.isatty():
                response = "yes"
            else:
                try:
                    response = input("Type 'yes' to confirm: ").strip().lower()
                except EOFError:
                    response = "yes"

            if response != "yes":
                logger.info(f"[{MODULE_NAME}] close_all cancelled by user")
                return {
                    "success": False,
                    "messages": messages + [{"type": "cancelled"}],
                    "success_count": 0,
                    "failure_count": 0,
                    "total": len(open_plans),
                }

        messages.append({"type": "closing_all", "count": len(open_plans)})

        # Close each plan
        success_count = 0
        failure_count = 0

        for plan_num, plan_info in open_plans:
            messages.append({"type": "closing_single", "plan_num": plan_num})

            # Call close_plan with spawn_background=False to avoid race condition
            result = close_plan_fn(plan_num=plan_num, confirm=False, all_plans=False, spawn_background=False)

            # Handle both old bool and new dict return formats
            if isinstance(result, dict):
                plan_success = result.get("success", False)
                messages.extend(result.get("messages", []))
            else:
                plan_success = bool(result)

            if plan_success:
                success_count += 1
            else:
                failure_count += 1

        # Spawn ONE background process for all closed plans
        if success_count > 0:
            try:
                _spawn_background_runner()
                logger.info(f"[{MODULE_NAME}] Spawned single background process for {success_count} closed plan(s)")
                messages.append({"type": "dim", "text": f"Background processing started for {success_count} plan(s)"})
            except Exception as e:
                logger.warning(f"[{MODULE_NAME}] Failed to spawn background post-processing: {e}")
                messages.append({"type": "warning", "text": "Background processing failed to start - will retry on next close"})

        # Summary
        messages.append({
            "type": "close_all_summary",
            "success_count": success_count,
            "failure_count": failure_count,
            "total": len(open_plans),
        })

        logger.info(f"[{MODULE_NAME}] close_all completed: {success_count} success, {failure_count} failures")
        json_handler.log_operation("all_plans_closed", {"success_count": success_count, "failure_count": failure_count, "total": len(open_plans)})
        return {
            "success": success_count > 0,
            "messages": messages,
            "success_count": success_count,
            "failure_count": failure_count,
            "total": len(open_plans),
        }

    except Exception as e:
        error_msg = f"Error in close_all: {e}"
        logger.error(f"[{MODULE_NAME}] {error_msg}")
        return {
            "success": False,
            "messages": [{"type": "error_text", "text": error_msg}],
            "success_count": 0,
            "failure_count": 0,
            "total": 0,
        }
