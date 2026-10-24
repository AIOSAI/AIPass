# =================== AIPass ====================
# Name: create_ops.py
# Description: Plan Creation Implementation Handler
# Version: 1.4.0
# Created: 2026-03-08
# Modified: 2026-10-24
# =============================================

"""Plan Creation Operations Handler

Returns data - module handles all display.
"""

import re
from pathlib import Path
from datetime import datetime
from typing import Callable, Tuple, List, Dict, Any

from aipass.prax import logger

from aipass.flow.apps.handlers.json import json_handler


from aipass.flow.apps.handlers.registry.load_registry import next_free_number
from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]  # handlers/plan/ -> handlers/ -> apps/ -> flow/ -> aipass/

MODULE_NAME = "create_plan"


def slugify_subject(subject: str, max_length: int = 40) -> str:
    """Sanitize subject for filename: lowercase, underscores, max *max_length* chars."""
    slug = re.sub(r"[^\w\s-]", "", subject.lower())
    slug = re.sub(r"[\s-]+", "_", slug)
    return slug.strip("_")[:max_length]


def create_plan_impl(
    location: str | None = None,
    subject: str = "",
    template_type: str = "default",
    plan_type_config: Dict[str, Any] | None = None,
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
    update_dashboard_local: Callable[..., bool | None] | None = None,
    push_to_plans_central: Callable[..., bool] | None = None,
    push_flow_to_branch_dashboard: Callable[..., bool | None] | None = None,
) -> Tuple[bool, int, str, str, str, List[Dict[str, Any]]]:
    """Implement plan creation workflow
    Returns (success, plan_number, location_description, template_type, error_message, messages).
    """
    messages: List[Dict[str, Any]] = []

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

    # Narrowing for the type checker; the loop above already refused None.
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

    prefix = plan_type_config["prefix"] if plan_type_config else "FPLAN"
    digits = plan_type_config["digits"] if plan_type_config else 4
    slug_max = plan_type_config.get("slug_max_length", 45) if plan_type_config else 40
    registry_file = plan_type_config.get("registry_file") if plan_type_config else None

    try:
        registry = load_registry(registry_file=registry_file)

        registry, auto_closed_count = auto_close_orphaned_plans(registry)
        if auto_closed_count > 0:
            save_registry(registry, registry_file=registry_file)
            messages.append({"type": "dim", "text": f"[AUTO-CLEANUP] Closed {auto_closed_count} orphaned plan(s)"})

        # Never a number a row already holds, whatever next_number says.
        NEXT_NUM = next_free_number(registry)

        success, target_dir, error_msg = resolve_plan_location(location, ecosystem_root)
        if not success:
            return False, 0, "", "", error_msg, messages

        RELATIVE_LOCATION = calculate_relative_location(target_dir, ecosystem_root)

        topic_slug = slugify_subject(subject, max_length=slug_max)
        date_str = datetime.now().strftime("%Y-%m-%d")
        formatted_num = f"{NEXT_NUM:0{digits}d}"
        if topic_slug:
            PLAN_FILE = target_dir / f"{prefix}-{formatted_num}_{topic_slug}_{date_str}.md"
        else:
            PLAN_FILE = target_dir / f"{prefix}-{formatted_num}_{date_str}.md"

        template_path: Path | None = None
        if plan_type_config is not None:
            tmpl_name = plan_type_config.get("default_template", "default")
            tmpl_dir: Path | None = plan_type_config.get("_directory")
            if tmpl_dir is not None:
                available = sorted(p for p in tmpl_dir.glob("*.md")) if tmpl_dir.is_dir() else []
                candidate = tmpl_dir / f"{tmpl_name}.md"
                if candidate.is_file():
                    template_path = candidate
                elif len(available) == 1:
                    # A lone template is used whatever its name.
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

        success, error_msg = create_plan_file(PLAN_FILE, CONTENT)
        if not success:
            return False, 0, "", "", error_msg, messages

        if "plans" not in registry:
            registry["plans"] = {}

        registry["plans"][formatted_num] = build_plan_registry_entry(
            NEXT_NUM, target_dir, RELATIVE_LOCATION, subject, PLAN_FILE, template_type
        )
        registry["next_number"] = NEXT_NUM + 1

        if not save_registry(registry, registry_file=registry_file):
            # The file exists but no row names it, so the next create would reissue this number.
            error_msg = (
                f"{PLAN_FILE.name} was written but the registry was not saved; "
                "run 'drone @flow registry scan' to register it"
            )
            logger.error(f"[{MODULE_NAME}] {error_msg}")
            return False, 0, "", "", error_msg, messages

        dashboard_success = update_dashboard_local()
        central_success = push_to_plans_central()

        # None is "flow has no dashboard", not a failure.
        if dashboard_success is False:
            logger.warning(f"[{MODULE_NAME}] Failed to update DASHBOARD.local.json")
        if not central_success:
            logger.warning(f"[{MODULE_NAME}] Failed to update PLANS.central.json")

        # None: no dashboard there. False: the push failed (already logged).
        branch_dashboard_success = push_flow_to_branch_dashboard(target_dir)
        if branch_dashboard_success is None:
            messages.append(
                {"type": "dim", "text": f"No branch dashboard at {target_dir} -- no branch is tracking this plan"}
            )
        elif not branch_dashboard_success:
            messages.append(
                {
                    "type": "warning",
                    "text": f"[WARNING] Failed to push flow section to branch dashboard at {target_dir} (see log)",
                }
            )

        plan_id = f"{prefix}-{formatted_num}"
        logger.info(f"[{MODULE_NAME}] Created {plan_id} in {RELATIVE_LOCATION}")

        display_msg = display_plan_created(
            NEXT_NUM,
            RELATIVE_LOCATION,
            subject,
            template_type,
            prefix=prefix,
            digits=digits,
        )
        messages.append({"type": "display", "text": display_msg})

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
