# =================== AIPass ====================
# Name: close_ops.py
# Description: Plan Closure Implementation Handler
# Version: 1.6.0
# Created: 2026-03-08
# Modified: 2026-10-24
# =============================================

"""
Plan Closure Operations Handler

Returns data dicts - module handles all display.
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
    canonical_plan_id,
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

# "Not injected" (resolve it) vs None, "stands in no project" (refuse the run).
_UNSET = object()

# Kept apart so out-of-scope rows (the fence) never hide inside excluded types (a choice).
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


def _make_project_resolver() -> Any:
    """Build a row -> project resolver backed by a cache scoped to one sweep.

    Not a module-level memo: it would outlive the run and miss a register built mid-process.
    """
    from aipass.flow.apps.handlers.plan.project_scope import find_project_root

    cache: Dict[Path, Any] = {}

    def resolve(location: Path) -> Any:
        return find_project_root(location, cache)

    return resolve


def _scope_reason(row_project: Any) -> str:
    """Name why a row is out of scope -- 'foreign' and 'unattributable' differ."""
    from aipass.flow.apps.handlers.plan.project_scope import describe_project

    if row_project is None:
        return "no project register above its location"
    return f"belongs to {describe_project(row_project)}"


def _refuse_non_plan_file(plan_file: Path, plan_label: str, plan_key: str) -> Dict[str, Any] | None:
    """The failure result when ``plan_file`` is present but not a plan, else None.

    Old rows can name reports only named like plans; an unreadable file is refused too.
    """
    from aipass.flow.apps.handlers.registry.monitor_ops import is_plan_file

    verdict = is_plan_file(plan_file)
    if verdict is True:
        return None
    why = "cannot be read" if verdict is None else "is not a plan (its first line is no plan header)"
    logger.warning(f"[{MODULE_NAME}] Refused to close {plan_label}: {plan_file} {why}; nothing archived")
    return {
        "success": False,
        "messages": [
            {"type": "error_text", "text": f"Refused: {plan_file} {why}. Nothing was archived, moved or renamed."}
        ],
        "plan_key": plan_key,
        "cancelled": False,
    }


def _refresh_dashboards(
    locations: List[str],
    update_dashboard_local: Any,
    push_to_plans_central: Any,
    push_flow_to_branch_dashboard: Any,
    messages: List[Dict[str, Any]],
) -> None:
    """Refresh flow's dashboard, PLANS.central.json and each location's branch dashboard. Never raises."""
    try:
        # None is "flow has no dashboard", not a failure.
        if update_dashboard_local() is False:
            logger.warning(f"[{MODULE_NAME}] Failed to update DASHBOARD.local.json")
        if not push_to_plans_central():
            logger.warning(f"[{MODULE_NAME}] Failed to update PLANS.central.json")

        for location in dict.fromkeys(loc for loc in locations if loc):
            if push_flow_to_branch_dashboard(Path(location)) is False:
                logger.warning(f"[{MODULE_NAME}] Failed to push flow section to branch dashboard at {location}")
    except Exception as e:
        logger.warning(f"[{MODULE_NAME}] Dashboard update error: {e}")
        messages.append({"type": "warning", "text": f"  Dashboard update failed (non-critical): {e}"})


def close_plan_impl(
    plan_num: Any = None,
    confirm: bool = False,
    all_plans: bool = False,
    spawn_background: bool = True,
    dry_run: bool = False,
    exclude_types: List[str] | None = None,
    refresh_dashboards: bool = True,
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
    spawn_background=False and refresh_dashboards=False from close_all: it does both once, after the sweep.
    """
    messages: List[Dict[str, Any]] = []

    if all_plans:
        return close_all_plans_fn(confirm, dry_run=dry_run, exclude_types=exclude_types)

    if not plan_num:
        logger.warning(f"[{MODULE_NAME}] Plan number required for single plan closure")
        return {
            "success": False,
            "messages": [{"type": "error", "text": "invalid_number", "plan_num": ""}],
            "plan_key": "",
            "cancelled": False,
        }

    try:
        plan_key = normalize_plan_number(plan_num)

        reg_file = _resolve_registry_file(plan_num)
        if reg_file:
            registry = load_registry(registry_file=reg_file)
        else:
            registry = load_registry()
            exists_default, _ = validate_plan_exists(plan_key, registry)
            if not exists_default:
                found_reg = _find_plan_across_registries(plan_key, load_registry)
                if found_reg:
                    reg_file = found_reg
                    registry = load_registry(registry_file=reg_file)

        exists, error_msg = validate_plan_exists(plan_key, registry)
        if not exists:
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
                    "messages": [{"type": "error", "text": "not_found", "plan_num": plan_key, "prefix": prefix}],
                    "plan_key": plan_key,
                    "cancelled": False,
                }

        plan_info = registry["plans"][plan_key]
        plan_file = Path(plan_info.get("file_path", ""))

        plan_label = plan_file.stem if plan_file.name else f"PLAN-{plan_key}"

        plan_prefix = _extract_prefix(plan_label) or "FPLAN"

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

        if plan_info["status"] == "closed":
            closed_date = plan_info.get("closed", "unknown")

            if plan_file.exists():
                refusal = _refuse_non_plan_file(plan_file, plan_label, plan_key)
                if refusal is not None:
                    return refusal
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

        if not plan_file.exists():
            relocated = _find_relocated_plan(plan_file)
            if relocated:
                messages.append(
                    {"type": "warning", "text": f"  Plan file not at expected path, found at: {relocated.parent.name}/"}
                )
                logger.info(f"[{MODULE_NAME}] Relocated {plan_label}: {relocated}")
                plan_file = relocated

        # An absent file still closes in the registry only.
        if plan_file.exists():
            refusal = _refuse_non_plan_file(plan_file, plan_label, plan_key)
            if refusal is not None:
                return refusal

        # Informational only, never deletes: is_template_content() false-positives on minimal plans.
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

        messages.append({"type": "header", "plan_key": plan_key, "plan_info": plan_info, "prefix": plan_prefix})

        if confirm:
            if not confirm_plan_deletion(plan_key):
                logger.info(f"[{MODULE_NAME}] Closure cancelled by user for PLAN{plan_key}")
                return {
                    "success": False,
                    "messages": messages + [{"type": "cancelled"}],
                    "plan_key": plan_key,
                    "cancelled": True,
                }

        messages.append({"type": "step", "text": "[2/5] Marking plan as closed..."})
        try:
            # Close always succeeds from this point; archive is non-blocking.
            plan_info["status"] = "closed"
            plan_info["closed"] = datetime.now(timezone.utc).isoformat()
            if reg_file:
                saved = save_registry(registry, registry_file=reg_file)
            else:
                saved = save_registry(registry)
            # save_registry answers False rather than raising.
            if not saved:
                raise OSError("the registry was not saved; the plan is still open and nothing was archived")
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
                    saved = save_registry(registry, registry_file=reg_file)
                else:
                    saved = save_registry(registry)
                if not saved:
                    warn = "  Archived, but could not save the registry: the row reads unarchived"
                    messages.append({"type": "warning", "text": warn})
                if plan_file.parent != PROCESSED_PLANS_DIR:
                    logger.info(f"[{MODULE_NAME}] Archived {plan_label} to processed_plans")
                    messages.append({"type": "dim", "text": "  Plan archived to processed_plans/"})
            else:
                logger.error(f"[{MODULE_NAME}] Failed to archive {plan_label}")
                messages.append({"type": "warning", "text": "  Archive failed — plan file not moved"})
        except Exception as e:
            logger.error(f"[{MODULE_NAME}] Archive error for {plan_label}: {e}")
            messages.append({"type": "warning", "text": f"  Archive error: {e}"})

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

        messages.append({"type": "step", "text": "[4/5] Updating dashboards..."})
        if refresh_dashboards:
            _refresh_dashboards(
                [plan_info.get("location", "")],
                update_dashboard_local,
                push_to_plans_central,
                push_flow_to_branch_dashboard,
                messages,
            )

        messages.append({"type": "step", "text": "[5/5] Finalizing..."})
        messages.append({"type": "close_success", "plan_key": plan_key, "prefix": plan_prefix})

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

        if trigger_fire_fn is not None:
            try:
                trigger_fire_fn("plan_closed", plan_number=plan_key, location=str(plan_file.parent))
            except Exception as e:
                logger.warning(f"[{MODULE_NAME}] Trigger fire failed (non-critical): {e}")

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
    update_dashboard_local: Any = None,
    push_to_plans_central: Any = None,
    push_flow_to_branch_dashboard: Any = None,
) -> Dict[str, Any]:
    """
    Close every open plan that belongs to the CALLER'S project

    Fences: excluded types are held, rows outside the caller's project are held, untyped rows
    are refused as failures, never guessed. No self-preservation rule: the dry run names all.
    """
    messages: List[Dict[str, Any]] = []
    excluded_prefixes = {t.upper() for t in (exclude_types or [])}

    try:
        # No project above the caller means no boundary; a bulk close would sweep everything.
        if resolve_project_fn is None:
            resolve_project_fn = _make_project_resolver()
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

        # Resolved once to typed IDs so the dry run and the run cannot drift (keys repeat per type).
        resolved: List[tuple[str, Dict[str, Any]]] = []
        unresolved: List[tuple[str, Dict[str, Any]]] = []
        # (plan_id, category, reason, plan_info): count by category, never by reason text.
        held: List[tuple[str, str, str, Dict[str, Any]]] = []

        for plan_num, plan_info in open_plans:
            plan_id = canonical_plan_id(plan_num, plan_info)
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

        # The dry run is the authorisation step: it shows the post-fence list, not a superset.
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

        plan_list = [
            {"plan_num": plan_id, "subject": plan_info.get("subject", "No subject")} for plan_id, plan_info in resolved
        ]

        messages.append(_scope_summary())
        messages.append({"type": "plan_list", "count": len(resolved), "plans": plan_list})

        if confirm:
            messages.append({"type": "confirm_warning", "count": len(resolved)})

            if not sys.stdin.isatty():
                response = "yes"
            else:
                try:
                    response = input("Type 'yes' to confirm: ").strip().lower()
                except EOFError:
                    # Ctrl-D at a prompt means back out, never yes.
                    logger.warning("[%s] EOFError on stdin during close_all confirmation, cancelling", MODULE_NAME)
                    response = "no"

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

        success_count = 0
        failure_count = 0
        closed_ids: List[str] = []
        failed_ids: List[str] = []

        for position, (plan_id, _plan_info) in enumerate(resolved, start=1):
            messages.append(
                {"type": "closing_single", "plan_num": plan_id, "position": position, "total": len(resolved)}
            )

            # The typed plan_id makes the resolve land on this row's registry, not fplan's.
            result = close_plan_fn(
                plan_num=plan_id, confirm=False, all_plans=False, spawn_background=False, refresh_dashboards=False
            )

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

        # Untyped rows are named failures; held rows are not failures, they are the fence.
        for plan_num, plan_info in unresolved:
            messages.append({"type": "error_text", "text": _refusal_text(plan_num, plan_info)})
            logger.error(f"[{MODULE_NAME}] close_all refused untyped row {plan_num}")
            failure_count += 1
            failed_ids.append(plan_num)

        if success_count > 0:
            if update_dashboard_local is not None:
                _refresh_dashboards(
                    [info.get("location", "") for plan_id, info in resolved if plan_id in closed_ids],
                    update_dashboard_local,
                    push_to_plans_central,
                    push_flow_to_branch_dashboard,
                    messages,
                )
            try:
                _spawn_background_runner()
                logger.info(f"[{MODULE_NAME}] Spawned single background process for {success_count} closed plan(s)")
                messages.append({"type": "dim", "text": f"Background processing started for {success_count} plan(s)"})
            except Exception as e:
                logger.warning(f"[{MODULE_NAME}] Failed to spawn background post-processing: {e}")
                messages.append(
                    {"type": "warning", "text": "Background processing failed to start - will retry on next close"}
                )

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
