# =================== AIPass ====================
# Name: create_ops.py
# Description: Plan Creation Implementation Handler
# Version: 1.1.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Plan Creation Operations Handler

Implements plan creation business logic, extracted from create_plan module.
Handles the full plan creation workflow including registry and dashboard updates.

Returns data - module handles all display.

Usage:
    from aipass.flow.apps.handlers.plan.create_ops import create_plan_impl, slugify_subject
"""

import re
from pathlib import Path
from datetime import datetime
from typing import Callable, Tuple, List, Dict, Any

from aipass.prax import logger

# logger imported from aipass.prax
from aipass.flow.apps.handlers.json import json_handler

# =============================================
# INFRASTRUCTURE
# =============================================

_PKG_ROOT = Path(__file__).resolve().parents[4]  # handlers/plan/ -> handlers/ -> apps/ -> flow/ -> aipass/

MODULE_NAME = "create_plan"

# =============================================
# HELPERS
# =============================================


def slugify_subject(subject: str, max_length: int = 40) -> str:
    """Sanitize subject for filename: lowercase, underscores, max *max_length* chars."""
    slug = re.sub(r"[^\w\s-]", "", subject.lower())
    slug = re.sub(r"[\s-]+", "_", slug)
    return slug.strip("_")[:max_length]


# =============================================
# CREATE PLAN IMPLEMENTATION
# =============================================


def create_plan_impl(
    location: str | None = None,
    subject: str = "",
    template_type: str = "default",
    plan_type_config: Dict[str, Any] | None = None,
    # Dependencies injected from module
    ecosystem_root: Path | None = None,
    load_registry: Callable[..., Dict[str, Any]] | None = None,
    save_registry: Callable[..., bool] | None = None,
    auto_close_orphaned_plans: Callable[..., tuple] | None = None,
    resolve_plan_location: Callable[..., tuple] | None = None,
    calculate_relative_location: Callable[..., str] | None = None,
    get_template: Callable[..., str] | None = None,
    create_plan_file: Callable[..., tuple] | None = None,
    build_plan_registry_entry: Callable[..., Dict[str, Any]] | None = None,
    display_plan_created: Callable[..., str] | None = None,
    update_dashboard_local: Callable[..., bool] | None = None,
    push_to_plans_central: Callable[..., bool] | None = None,
    push_flow_to_branch_dashboard: Callable[..., bool] | None = None,
) -> Tuple[bool, int, str, str, str, List[Dict[str, Any]]]:
    """
    Implement plan creation workflow

    Workflow Steps:
        1. Load registry
        2. Auto-cleanup orphaned plans
        3. Get next plan number
        4. Resolve location (@folder syntax support)
        5. Calculate relative path for display
        6. Build plan file path
        7. Get template content
        8. Create plan file
        9. Build and save registry entry
        10. Update dashboards
        11. Log and display results

    Args:
        location: Target directory for plan (@folder syntax supported)
        subject: Plan subject/title
        template_type: Template to use (default, master, etc.)
        (remaining args): Handler/service dependencies injected by module

    Returns:
        (success, plan_number, location_description, template_type, error_message, messages)
        messages is a list of dicts with type/text for the module to display
    """
    messages: List[Dict[str, Any]] = []

    # Validate required dependencies are provided
    required_deps = {
        "load_registry": load_registry,
        "save_registry": save_registry,
        "auto_close_orphaned_plans": auto_close_orphaned_plans,
        "resolve_plan_location": resolve_plan_location,
        "calculate_relative_location": calculate_relative_location,
        "get_template": get_template,
        "create_plan_file": create_plan_file,
        "build_plan_registry_entry": build_plan_registry_entry,
        "display_plan_created": display_plan_created,
        "update_dashboard_local": update_dashboard_local,
        "push_to_plans_central": push_to_plans_central,
        "push_flow_to_branch_dashboard": push_flow_to_branch_dashboard,
    }
    for dep_name, dep_fn in required_deps.items():
        if dep_fn is None:
            error_msg = f"Missing required dependency: {dep_name}"
            logger.error(f"[{MODULE_NAME}] {error_msg}")
            return False, 0, "", "", error_msg, messages

    # All deps validated as non-None above; assign to satisfy type checker
    assert load_registry is not None
    assert save_registry is not None
    assert auto_close_orphaned_plans is not None
    assert resolve_plan_location is not None
    assert calculate_relative_location is not None
    assert get_template is not None
    assert create_plan_file is not None
    assert build_plan_registry_entry is not None
    assert display_plan_created is not None
    assert update_dashboard_local is not None
    assert push_to_plans_central is not None
    assert push_flow_to_branch_dashboard is not None

    # Extract plan type settings from config (or fall back to FPLAN defaults)
    prefix = plan_type_config["prefix"] if plan_type_config else "FPLAN"
    digits = plan_type_config["digits"] if plan_type_config else 4
    slug_max = plan_type_config.get("slug_max_length", 45) if plan_type_config else 40
    registry_file = plan_type_config.get("registry_file") if plan_type_config else None

    try:
        # STEP 1: Load registry (type-specific when registry_file provided)
        registry = load_registry(registry_file=registry_file)

        # STEP 2: Auto-cleanup orphaned plans
        registry, auto_closed_count = auto_close_orphaned_plans(registry)
        if auto_closed_count > 0:
            save_registry(registry, registry_file=registry_file)
            messages.append({"type": "dim", "text": f"[AUTO-CLEANUP] Closed {auto_closed_count} orphaned plan(s)"})

        # STEP 3: Get next plan number
        NEXT_NUM = registry["next_number"]

        # STEP 4: Resolve location (@folder syntax support)
        success, target_dir, error_msg = resolve_plan_location(location, ecosystem_root)
        if not success:
            return False, 0, "", "", error_msg, messages

        # STEP 5: Calculate relative path for display
        RELATIVE_LOCATION = calculate_relative_location(target_dir, ecosystem_root)

        # STEP 6: Build plan file path ({PREFIX}-{XXXX}_{topic_slug}_{date}.md)
        topic_slug = slugify_subject(subject, max_length=slug_max)
        date_str = datetime.now().strftime("%Y-%m-%d")
        formatted_num = f"{NEXT_NUM:0{digits}d}"
        if topic_slug:
            PLAN_FILE = target_dir / f"{prefix}-{formatted_num}_{topic_slug}_{date_str}.md"
        else:
            PLAN_FILE = target_dir / f"{prefix}-{formatted_num}_{date_str}.md"

        # STEP 7: Get template content
        # Resolve template path from plan_type_config — no fallback
        template_path: Path | None = None
        if plan_type_config is not None:
            tmpl_name = plan_type_config.get("default_template", "default")
            tmpl_dir: Path | None = plan_type_config.get("_directory")
            if tmpl_dir is not None:
                available = sorted(p for p in tmpl_dir.glob("*.md")) if tmpl_dir.is_dir() else []
                candidate = tmpl_dir / f"{tmpl_name}.md"
                if candidate.is_file():
                    # Exact template match
                    template_path = candidate
                elif len(available) == 1:
                    # Single template in directory — use it regardless of name
                    template_path = available[0]
                elif len(available) > 1:
                    names = [p.stem for p in available]
                    error_msg = f"Multiple templates in {tmpl_dir.name}/. Specify which one: {names}"
                    return False, 0, "", "", error_msg, []
                else:
                    error_msg = f"No templates found in {tmpl_dir.name}/"
                    return False, 0, "", "", error_msg, []

        try:
            CONTENT = get_template(
                template_type,
                number=NEXT_NUM,
                location=RELATIVE_LOCATION,
                subject=subject,
                template_path=template_path,
                prefix=prefix,
                digits=digits,
            )
        except Exception as e:
            error_msg = f"Failed to load template '{template_type}': {e}"
            logger.error(f"[{MODULE_NAME}] {error_msg}")
            return False, 0, "", "", error_msg, messages

        # STEP 8: Create plan file
        success, error_msg = create_plan_file(PLAN_FILE, CONTENT)
        if not success:
            return False, 0, "", "", error_msg, messages

        # STEP 9: Build registry entry
        if "plans" not in registry:
            registry["plans"] = {}

        registry["plans"][formatted_num] = build_plan_registry_entry(
            NEXT_NUM, target_dir, RELATIVE_LOCATION, subject, PLAN_FILE, template_type
        )
        registry["next_number"] = NEXT_NUM + 1

        # STEP 10: Save updated registry (type-specific when registry_file provided)
        if not save_registry(registry, registry_file=registry_file):
            error_msg = "Failed to save registry after plan creation"
            logger.error(f"[{MODULE_NAME}] {error_msg}")
            messages.append({"type": "warning", "text": f"[WARNING] {error_msg}"})

        # STEP 11: Update dashboards (3-tier: modules log, handlers don't)
        dashboard_success = update_dashboard_local()
        central_success = push_to_plans_central()

        # Log dashboard update results
        if not dashboard_success:
            logger.warning(f"[{MODULE_NAME}] Failed to update DASHBOARD.local.json")
        if not central_success:
            logger.warning(f"[{MODULE_NAME}] Failed to update PLANS.central.json")

        # STEP 11b: Push flow section to branch's dashboard via write-through
        branch_dashboard_success = push_flow_to_branch_dashboard(target_dir)
        if not branch_dashboard_success:
            messages.append(
                {"type": "dim", "text": f"No branch dashboard at {target_dir} -- no branch is tracking this plan"}
            )

        # STEP 12: Log success
        plan_id = f"{prefix}-{formatted_num}"
        logger.info(f"[{MODULE_NAME}] Created {plan_id} in {RELATIVE_LOCATION}")

        # Build display message
        display_msg = display_plan_created(
            NEXT_NUM,
            RELATIVE_LOCATION,
            subject,
            template_type,
            prefix=prefix,
            digits=digits,
        )
        messages.append({"type": "display", "text": display_msg})

        # Fire trigger event for plan creation
        try:
            from aipass.trigger.apps.modules.core import trigger

            trigger.fire("plan_created", plan_number=NEXT_NUM, location=RELATIVE_LOCATION, subject=subject)
        except ImportError:
            logger.info(f"[{MODULE_NAME}] Trigger module not available, skipping plan_created event")

        json_handler.log_operation(
            "plan_created",
            {"plan_number": NEXT_NUM, "location": RELATIVE_LOCATION, "template": template_type, "success": True},
        )
        return True, NEXT_NUM, RELATIVE_LOCATION, template_type, "", messages

    except Exception as e:
        error_msg = f"Error creating plan: {e}"
        logger.error(f"[{MODULE_NAME}] {error_msg}")
        return False, 0, "", "", error_msg, messages
