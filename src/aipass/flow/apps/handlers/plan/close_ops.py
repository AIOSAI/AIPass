# =================== AIPass ====================
# Name: close_ops.py
# Description: Plan Closure Implementation Handler
# Version: 1.2.0
# Created: 2026-03-08
# Modified: 2026-05-16
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
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List

from aipass.prax import logger

from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.plan.registry_routing import (
    _extract_prefix,
    _resolve_registry_file,
    _find_plan_across_registries,
    _canonical_plan_id,
)
from aipass.flow.apps.handlers.plan.close_helpers import (
    PROCESSED_PLANS_DIR,
    _find_relocated_plan,
    _find_unregistered_plan_file,
    _self_heal_unregistered_plan,
    _spawn_background_runner,
    _cleanup_orphaned_plan,
)

MODULE_NAME = "close_plan"

# Distinguishes "the caller did not inject a project" from "the caller stands
# in no project". Both are None-shaped and they mean opposite things: the first
# means go and resolve it, the second means refuse the run.
_UNSET = object()

# Why a row was held back. Two different things wearing one count is how the
# second kind stays invisible: an excluded type is the operator's choice, an
# out-of-scope row is the fence.
HELD_TYPE = "type"
HELD_SCOPE = "scope"


def _caller_project_default() -> Any:
    """Resolve the caller's project from where they actually stood."""
    from aipass.flow.apps.handlers.plan.project_scope import caller_project_root

    return caller_project_root()


def _project_label(root: Any) -> str:
    """Short display name for a project root."""
    from aipass.flow.apps.handlers.plan.project_scope import describe_project

    return describe_project(root)


def _default_resolve_project(location: Path) -> Any:
    """Resolve a row's project from the row's own location."""
    from aipass.flow.apps.handlers.plan.project_scope import find_project_root

    return find_project_root(location)


def _scope_reason(row_project: Any) -> str:
    """Name why a row is out of scope -- 'foreign' and 'unattributable' differ.

    A row in another project is fenced correctly. A row that answers to NO
    project is a data-quality problem in the registry, and collapsing the two
    into one count is how the second kind stays invisible for months.
    """
    from aipass.flow.apps.handlers.plan.project_scope import describe_project

    if row_project is None:
        return "no project register above its location"
    return f"belongs to {describe_project(row_project)}"


# =============================================
# CLOSE PLAN IMPLEMENTATION
# =============================================


def close_plan_impl(
    plan_num: Any = None,
    confirm: bool = False,
    all_plans: bool = False,
    spawn_background: bool = True,
    dry_run: bool = False,
    exclude_types: List[str] | None = None,
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
    close_all_plans_fn: Any = None,
    archive_plan_fn: Any = None,
    trigger_fire_fn: Any = None,
) -> Dict[str, Any]:
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
        exclude_types: Plan-type prefixes to hold back; only meaningful with all_plans
        (remaining args): Handler/service dependencies injected by module

    Returns:
        Dict with keys: success (bool), messages (list of dicts with type/text),
        plan_key (str), cancelled (bool)
    """
    messages: List[Dict[str, Any]] = []

    # Handle --all flag
    if all_plans:
        return close_all_plans_fn(confirm, dry_run=dry_run, exclude_types=exclude_types)

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
            # SELF-HEAL: Check if plan file exists on disk but not in registry
            prefix = _extract_prefix(plan_num) or "FPLAN"
            if not reg_file:
                reg_file = f"{prefix.lower()}_registry.json"
            plan_file_found = _find_unregistered_plan_file(prefix, plan_key)

            if plan_file_found:
                plan_key, registry = _self_heal_unregistered_plan(
                    prefix,
                    plan_key,
                    plan_file_found,
                    registry,
                    reg_file,
                    save_registry,
                    load_registry,
                    messages,
                )
            else:
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
        if plan_info["status"] == "closed":
            closed_date = plan_info.get("closed", "unknown")

            # Check if .md file is orphaned on disk (registry-closed but file never moved)
            if plan_file.exists():
                messages.append(
                    {
                        "type": "warning",
                        "text": f"{plan_label} already closed on {closed_date} — orphaned .md file detected",
                    }
                )
                _cleanup_orphaned_plan(
                    plan_file,
                    plan_label,
                    plan_info,
                    registry,
                    save_registry,
                    reg_file,
                    messages,
                    archive_plan=archive_plan_fn,
                )
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

        # --- File location resolution ---
        # If plan file was manually moved, find it before proceeding
        if not plan_file.exists():
            relocated = _find_relocated_plan(plan_file)
            if relocated:
                messages.append(
                    {"type": "warning", "text": f"  Plan file not at expected path, found at: {relocated.parent.name}/"}
                )
                logger.info(f"[{MODULE_NAME}] Relocated {plan_label}: {relocated}")
                plan_file = relocated

        # --- Step 1/5: Template check (informational only -- never deletes) ---
        # Was previously a fast-delete branch (unlink + registry row removal). Removed:
        # is_template_content() is a heuristic and can false-positive on real-but-minimal
        # FPLANs (the template itself encourages short, disposable single-task plans), and
        # a false positive there was destroying both the file and the registry row with no
        # archive, no CLOSED_PLANS entry, and no vectorization -- unrecoverable data loss,
        # and a violation of the house rule to never delete (archive instead). Empty templates
        # now flow through the same close/archive/vectorize pipeline as everything else;
        # cleanup_temp_files() already exists to prune the resulting low-value vector entries.
        messages.append({"type": "step", "text": "[1/5] Checking template status..."})
        try:
            with open(plan_file, "r", encoding="utf-8") as f:
                content = f.read()

            if is_template_content(content):
                messages.append(
                    {
                        "type": "warning",
                        "text": f"  {plan_label} looks like an empty template — closing and archiving normally",
                    }
                )

        except FileNotFoundError:
            logger.warning(f"[{MODULE_NAME}] Plan file not found at any location: {plan_file}")
            messages.append(
                {"type": "warning", "text": "  Plan file not found at any location, closing in registry only"}
            )
        except Exception as e:
            logger.warning(f"[{MODULE_NAME}] Template check failed: {e}")
            messages.append(
                {"type": "warning", "text": "  Could not check template status, continuing with normal close"}
            )

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
            plan_info["status"] = "closed"
            plan_info["closed"] = datetime.now(timezone.utc).isoformat()
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
            if plan_file.exists() and plan_file.parent == PROCESSED_PLANS_DIR:
                archive_success = True
                logger.info(f"[{MODULE_NAME}] {plan_label} already in processed_plans/, skipping move")
                messages.append({"type": "dim", "text": "  Already in processed_plans/ — skipping move"})
            else:
                archive_success = archive_plan_fn(plan_file) if archive_plan_fn else False

            if archive_success:
                plan_info["processed"] = True
                plan_info["processed_date"] = datetime.now(timezone.utc).isoformat()
                plan_info["cleanup_completed"] = True
                plan_info["cleanup_date"] = datetime.now(timezone.utc).isoformat()
                if reg_file:
                    save_registry(registry, registry_file=reg_file)
                else:
                    save_registry(registry)
                if plan_file.parent != PROCESSED_PLANS_DIR:
                    logger.info(f"[{MODULE_NAME}] Archived {plan_label} to processed_plans")
                    messages.append({"type": "dim", "text": "  Plan archived to processed_plans/"})
            else:
                logger.error(f"[{MODULE_NAME}] Failed to archive {plan_label}")
                messages.append({"type": "warning", "text": "  Archive failed — plan file not moved"})
        except Exception as e:
            logger.error(f"[{MODULE_NAME}] Archive error for {plan_label}: {e}")
            messages.append({"type": "warning", "text": f"  Archive error: {e}"})

        # --- Vector intake (background) ---
        if spawn_background:
            try:
                _spawn_background_runner()
                logger.info(f"[{MODULE_NAME}] Spawned background vectorization for {plan_label}")
                messages.append({"type": "dim", "text": "  Vectorizing in background"})
            except Exception as e:
                logger.warning(f"[{MODULE_NAME}] Background vectorization failed to start: {e}")
                messages.append(
                    {"type": "warning", "text": "  Background vectorization failed to start — will retry on next close"}
                )

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
                    logger.warning(
                        f"[{MODULE_NAME}] Failed to push flow section to branch dashboard at {plan_location}"
                    )
        except Exception as e:
            logger.warning(f"[{MODULE_NAME}] Dashboard update error: {e}")
            messages.append({"type": "warning", "text": f"  Dashboard update failed (non-critical): {e}"})

        # --- Step 5/5: Done ---
        messages.append({"type": "step", "text": "[5/5] Finalizing..."})
        messages.append({"type": "close_success", "plan_key": plan_key, "prefix": plan_prefix})

        # Append to branch's CLOSED_PLANS.local.json
        try:
            from aipass.flow.apps.handlers.plan.append_closed_plan import append_to_closed_plans

            if not append_to_closed_plans(plan_key, plan_info, plan_file.parent):
                logger.error(f"[{MODULE_NAME}] CLOSED_PLANS append failed for {plan_prefix}-{plan_key}")
                messages.append(
                    {
                        "type": "warning",
                        "text": f"  CLOSED_PLANS append failed for {plan_prefix}-{plan_key}",
                    }
                )
        except Exception as e:
            logger.error(f"[{MODULE_NAME}] CLOSED_PLANS update failed: {e}")
            messages.append(
                {
                    "type": "warning",
                    "text": f"  CLOSED_PLANS update failed: {e}",
                }
            )

        # Fire trigger event for plan closure
        if trigger_fire_fn is not None:
            try:
                trigger_fire_fn("plan_closed", plan_number=plan_key, location=str(plan_file.parent))
            except Exception as e:
                logger.warning(f"[{MODULE_NAME}] Trigger fire failed (non-critical): {e}")

        # --- VERIFY: Physical state check for self-healed plans ---
        if plan_info.get("self_healed"):
            messages.append({"type": "step", "text": "[VERIFY] Checking physical state..."})
            try:
                original_source = Path(plan_info.get("file_path", ""))
                dest = PROCESSED_PLANS_DIR / original_source.name
                if dest.exists():
                    messages.append({"type": "dim", "text": f"  [OK] File in processed_plans/: {original_source.name}"})
                else:
                    messages.append({"type": "warning", "text": "  [FAIL] File NOT found in processed_plans/"})
                if not original_source.exists():
                    messages.append(
                        {"type": "dim", "text": f"  [OK] Source location clean: {original_source.parent.name}/"}
                    )
                else:
                    messages.append(
                        {"type": "warning", "text": f"  [FAIL] Source file still exists at: {original_source}"}
                    )
                verify_reg = load_registry(registry_file=reg_file) if reg_file else load_registry()
                verify_info = verify_reg.get("plans", {}).get(plan_key, {})
                if verify_info.get("status") == "closed":
                    messages.append({"type": "dim", "text": "  [OK] Registry status: closed"})
                else:
                    messages.append(
                        {
                            "type": "warning",
                            "text": f"  [FAIL] Registry status: {verify_info.get('status', 'unknown')}",
                        }
                    )
            except Exception as e:
                logger.warning(f"[{MODULE_NAME}] Self-heal verification failed: {e}")
                messages.append({"type": "warning", "text": f"  Verification error: {e}"})

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


def close_all_plans_impl(
    confirm: bool = False,
    dry_run: bool = False,
    exclude_types: List[str] | None = None,
    # Dependencies injected from module
    get_open_plans: Any = None,
    close_plan_fn: Any = None,
    caller_project: Any = _UNSET,
    resolve_project_fn: Any = None,
) -> Dict[str, Any]:
    """
    Close every open plan that belongs to the CALLER'S project

    Three fences, applied at the read, all visible in the dry run:

    1. TYPE      -- rows whose prefix is in `exclude_types` are held back.
                    Validated by the caller against the registered templates.
    2. SCOPE     -- rows whose nearest register-holding ancestor is not the
                    caller's project are out of scope. A service running in a
                    project never leaves it; 50 of the 792 live rows belong to
                    baud, Vera-Studio, AIPL, marketstand and speakeasy, and a
                    sweep from AIPass must not touch one of them.
    3. TYPE-EVIDENCE -- a row whose file_path carries no prefix cannot be named
                    and is REFUSED as a failure, never guessed.

    There is deliberately NO self-preservation rule. DPLAN-0316 -- the plan
    tracking this command -- is one of the rows a full sweep closes, and an
    invisible exemption would be a fallback wearing a helpful hat. The dry run
    NAMES it; the operator decides.

    Args:
        confirm: Whether to ask for bulk confirmation (default False, auto-confirms)
        dry_run: If True, preview what would be closed without taking action
        exclude_types: Upper-cased prefixes to hold back (e.g. ["APLAN"])
        get_open_plans: Handler function to get open plans
        close_plan_fn: Function to close a single plan (the module's close_plan)
        caller_project: Project root the caller is standing in (Path or None)
        resolve_project_fn: Callable(Path) -> project root or None, for a row

    Returns:
        Dict with keys: success (bool), messages (list), success_count,
        failure_count, total, and the resolution buckets (see below).
    """
    messages: List[Dict[str, Any]] = []
    excluded_prefixes = {t.upper() for t in (exclude_types or [])}

    try:
        # SCOPE FENCE PRE-CHECK -- refuse before reading anything.
        # No project above the caller means no answer to "which plans are
        # mine", and a bulk close with no answer to that question would sweep
        # by default. Refusing is the only honest move; the alternative is the
        # exact silent-widening this command exists to remove.
        if resolve_project_fn is None:
            resolve_project_fn = _default_resolve_project
        if caller_project is _UNSET:
            caller_project = _caller_project_default()
        if caller_project is None:
            logger.error(f"[{MODULE_NAME}] close_all refused: caller stands in no registered project")
            return {
                "success": False,
                "messages": [
                    {
                        "type": "error_text",
                        "text": (
                            "REFUSED: no project register stands above your working directory, "
                            "so 'every plan' has no boundary. Run this from inside a project."
                        ),
                    }
                ],
                "success_count": 0,
                "failure_count": 0,
                "total": 0,
            }

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

        # RESOLVE IDENTITY AND SCOPE ONCE -- this list drives BOTH the preview
        # and the run. A bare registry key is ambiguous across types (every
        # registry numbers from 0001), so each row is resolved to its typed ID
        # up front. The preview used to derive a label here while the execution
        # passed the bare key downstream to be re-resolved: two paths, and they
        # disagreed on 61 of 72 live rows. One resolution means the dry run
        # cannot drift from the run -- and that matters most at the moment of
        # authorisation, where a preview that does not match the run
        # manufactures false confidence.
        resolved: List[tuple[str, Dict[str, Any]]] = []
        unresolved: List[tuple[str, Dict[str, Any]]] = []
        # (plan_id, category, reason, plan_info). The CATEGORY is carried, not
        # re-derived from the reason text -- counting by string prefix means an
        # edit to a human-readable sentence silently moves the numbers.
        held: List[tuple[str, str, str, Dict[str, Any]]] = []

        for plan_num, plan_info in open_plans:
            plan_id = _canonical_plan_id(plan_num, plan_info)
            if plan_id is None:
                unresolved.append((plan_num, plan_info))
                continue

            location = plan_info.get("location") or ""
            row_project = resolve_project_fn(Path(location)) if location else None
            if row_project != caller_project:
                held.append((plan_id, HELD_SCOPE, _scope_reason(row_project), plan_info))
                continue

            prefix = plan_id.split("-", 1)[0]
            if prefix in excluded_prefixes:
                held.append((plan_id, HELD_TYPE, f"type {prefix} excluded", plan_info))
                continue

            resolved.append((plan_id, plan_info))

        held_by_type = sum(1 for _id, category, _reason, _info in held if category == HELD_TYPE)
        held_out_of_scope = len(held) - held_by_type

        def _refusal_text(plan_num: str, plan_info: Dict[str, Any]) -> str:
            return (
                f"  REFUSED {plan_num} ({plan_info.get('subject', 'No subject')}) — "
                "registry row has no typed file_path, so its plan type cannot be "
                "established. Refusing to guess."
            )

        def _scope_summary() -> Dict[str, Any]:
            return {
                "type": "close_all_scope",
                "project": _project_label(caller_project),
                "considered": len(open_plans),
                "in_scope": len(resolved),
                "held_by_type": held_by_type,
                "held_out_of_scope": held_out_of_scope,
                "refused": len(unresolved),
                "excluded_types": sorted(excluded_prefixes),
            }

        # DRY RUN: Preview exactly what the run would resolve, then return early.
        # This IS the authorisation step, so it shows the post-fence list --
        # not a superset, not a statement of intent.
        if dry_run:
            messages.append(_scope_summary())
            messages.append({"type": "dim", "text": f"[DRY RUN] Would close {len(resolved)} plan(s):"})
            for plan_id, plan_info in resolved:
                messages.append(
                    {
                        "type": "dry_run_row",
                        "plan_id": plan_id,
                        "location": plan_info.get("location", "unknown"),
                        "subject": plan_info.get("subject", "No subject"),
                    }
                )
            if held:
                messages.append({"type": "dim", "text": f"Held back ({len(held)}):"})
                for plan_id, _category, reason, plan_info in held:
                    messages.append(
                        {
                            "type": "held_row",
                            "plan_id": plan_id,
                            "reason": reason,
                            "subject": plan_info.get("subject", "No subject"),
                        }
                    )
            for plan_num, plan_info in unresolved:
                messages.append({"type": "error_text", "text": _refusal_text(plan_num, plan_info)})
            messages.append({"type": "dim", "text": "No action taken."})
            logger.info(
                "[%s] Dry run: %d to close, %d held (type %d / scope %d), %d refused",
                MODULE_NAME,
                len(resolved),
                len(held),
                held_by_type,
                held_out_of_scope,
                len(unresolved),
            )
            return {
                "success": True,
                "messages": messages,
                "success_count": 0,
                "failure_count": 0,
                "total": len(open_plans),
                "plan_ids": [plan_id for plan_id, _ in resolved],
                "held_ids": [plan_id for plan_id, _cat, _reason, _info in held],
                "refused": [plan_num for plan_num, _ in unresolved],
            }

        # Build plan list for display
        plan_list = [
            {"plan_num": plan_id, "subject": plan_info.get("subject", "No subject")} for plan_id, plan_info in resolved
        ]

        messages.append(_scope_summary())
        messages.append({"type": "plan_list", "count": len(resolved), "plans": plan_list})

        # Confirm bulk close
        if confirm:
            messages.append({"type": "confirm_warning", "count": len(resolved)})

            # Auto-confirm in non-interactive environments (autonomous workflows)
            if not sys.stdin.isatty():
                response = "yes"
            else:
                try:
                    response = input("Type 'yes' to confirm: ").strip().lower()
                except EOFError:
                    logger.warning("[%s] EOFError on stdin during close_all confirmation, auto-confirming", MODULE_NAME)
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

        messages.append({"type": "closing_all", "count": len(resolved)})

        # Close each plan
        success_count = 0
        failure_count = 0
        closed_ids: List[str] = []
        failed_ids: List[str] = []

        for position, (plan_id, _plan_info) in enumerate(resolved, start=1):
            # Position is carried so the operator sees movement. A bulk close
            # of 55 plans takes minutes; a few minutes is fine, a SILENT few
            # minutes is not.
            messages.append(
                {"type": "closing_single", "plan_num": plan_id, "position": position, "total": len(resolved)}
            )

            # Call close_plan with spawn_background=False to avoid race condition.
            # plan_id carries the type prefix, so the downstream resolve lands on
            # this row's own registry instead of defaulting to fplan_registry.json.
            result = close_plan_fn(plan_num=plan_id, confirm=False, all_plans=False, spawn_background=False)

            # Handle both old bool and new dict return formats
            if isinstance(result, dict):
                plan_success = result.get("success", False)
                messages.extend(result.get("messages", []))
            else:
                plan_success = bool(result)

            if plan_success:
                success_count += 1
                closed_ids.append(plan_id)
            else:
                failure_count += 1
                failed_ids.append(plan_id)

        # Rows whose type could not be established are failures, and are NAMED.
        # A bare count cannot distinguish "nothing to do" from "something broke".
        # Held-back rows are NOT failures -- they are the fence working.
        for plan_num, plan_info in unresolved:
            messages.append({"type": "error_text", "text": _refusal_text(plan_num, plan_info)})
            logger.error(f"[{MODULE_NAME}] close_all refused untyped row {plan_num}")
            failure_count += 1
            failed_ids.append(plan_num)

        # Spawn ONE background process for all closed plans
        if success_count > 0:
            try:
                _spawn_background_runner()
                logger.info(f"[{MODULE_NAME}] Spawned single background process for {success_count} closed plan(s)")
                messages.append({"type": "dim", "text": f"Background processing started for {success_count} plan(s)"})
            except Exception as e:
                logger.warning(f"[{MODULE_NAME}] Failed to spawn background post-processing: {e}")
                messages.append(
                    {"type": "warning", "text": "Background processing failed to start - will retry on next close"}
                )

        # Summary
        messages.append(
            {
                "type": "close_all_summary",
                "success_count": success_count,
                "failure_count": failure_count,
                "held_count": len(held),
                "total": len(open_plans),
            }
        )

        logger.info(
            "[%s] close_all completed: %d success, %d failures, %d held",
            MODULE_NAME,
            success_count,
            failure_count,
            len(held),
        )
        json_handler.log_operation(
            "all_plans_closed",
            {
                "success_count": success_count,
                "failure_count": failure_count,
                "held_count": len(held),
                "total": len(open_plans),
            },
        )
        return {
            "success": success_count > 0,
            "messages": messages,
            "success_count": success_count,
            "failure_count": failure_count,
            "total": len(open_plans),
            # Named separately from the dry run's "plan_ids" (what it WOULD
            # attempt) because these report what actually happened.
            "closed_ids": closed_ids,
            "failed_ids": failed_ids,
            "held_ids": [plan_id for plan_id, _cat, _reason, _info in held],
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
