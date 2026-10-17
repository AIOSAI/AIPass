# =================== AIPass ====================
# Name: command_parser.py
# Description: Command Argument Parser
# Version: 0.2.0
# Created: 2025-11-15
# Modified: 2026-10-17
# =============================================

"""Command Argument Parser"""

from typing import List, Tuple

from aipass.prax import logger
from aipass.flow.apps.handlers.json import json_handler

MODULE_NAME = "command_parser"


def parse_create_plan_args(args: List[str]) -> Tuple[str | None, str, str]:
    """Parse arguments for plan creation
    An unmapped third argument passes through unchanged for plan_type_loader lookup.
    """
    location = args[0] if len(args) > 0 else None
    subject = args[1] if len(args) > 1 else ""
    raw_type = args[2] if len(args) > 2 else "default"

    try:
        from aipass.flow.apps.handlers.template.registry_ops import get_type_map

        type_map = get_type_map()
    except Exception as e:
        logger.warning(f"[{MODULE_NAME}] Failed to load type map from registry_ops, using defaults: {e}")
        type_map = {"default": "flow_plans", "dplan": "dev_plans"}
    plan_type_key = type_map.get(raw_type.lower(), raw_type)

    json_handler.log_operation(
        "create_args_parsed", {"location": location, "subject": subject, "plan_type_key": plan_type_key}
    )
    return location, subject, plan_type_key


# Anything outside this set REFUSES the run: dropping an unknown flag would run a bulk close
# the operator believed they had fenced.
_CLOSE_BOOL_FLAGS = {
    "--all": "all_plans",
    "--confirm": "confirm",
    "--interactive": "confirm",
    "--dry-run": "dry_run",
    "--preview": "dry_run",
    # Inert (auto-confirm is the default) but recognised, so old scripts keep working.
    "--yes": None,
    "-y": None,
}

_EXCLUDE_TYPE_FLAG = "--exclude-type"


def _registered_prefixes() -> List[str]:
    """Return the plan-type prefixes that are actually registered.
    Read from the template registry, never a literal list: a hardcoded set misses a newly added type.
    """
    from aipass.flow.apps.handlers.template.registry_ops import get_prefix_map

    return sorted({prefix.upper() for prefix in get_prefix_map().values() if prefix})


def _read_exclude_value(args: List[str], index: int) -> Tuple[str | None, int]:
    """Read the value of an --exclude-type occurrence at `index`.
    A flag with no value returns (None, next index): a fence the operator believes they set must refuse.
    """
    arg = args[index]
    if "=" in arg:
        return (arg.split("=", 1)[1] or "").upper() or None, index + 1
    value = args[index + 1] if index + 1 < len(args) else ""
    if not value or value.startswith("-"):
        return None, index + 2
    return value.upper(), index + 2


def _validate_close_args(positionals: List[str], exclude_types: List[str], all_plans: bool) -> str | None:
    """Return a refusal message for the parsed close arguments, or None."""
    if len(positionals) > 1:
        return f"Unrecognised argument: {' '.join(positionals[1:])}"

    if all_plans and positionals:
        return f"Unrecognised argument: {positionals[0]} (--all takes no plan number)"

    if not exclude_types:
        return None

    # An unknown type is a typo in a fence; accepting it would sweep unprotected.
    try:
        valid = _registered_prefixes()
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Cannot read registered plan types: {e}")
        return f"Cannot read registered plan types: {e}"

    unknown = [t for t in exclude_types if t not in valid]
    if unknown:
        return f"Unknown plan type(s): {', '.join(unknown)}. Registered: {', '.join(valid)}"
    if not all_plans:
        return f"{_EXCLUDE_TYPE_FLAG} only applies to --all"
    return None


def parse_close_command_args(args: List[str]) -> Tuple[str | None, bool, bool, bool, List[str], str | None]:
    """Parse arguments for close command
    Auto-confirms by default (running 'close' IS the intent); --confirm/--interactive asks first.
    Returns (plan_num, confirm, all_plans, dry_run, exclude_types, error_message).
    """
    all_plans = False
    confirm = False
    dry_run = False
    exclude_types: List[str] = []
    positionals: List[str] = []

    index = 0
    while index < len(args):
        arg = args[index]

        if arg in _CLOSE_BOOL_FLAGS:
            target = _CLOSE_BOOL_FLAGS[arg]
            all_plans = all_plans or target == "all_plans"
            confirm = confirm or target == "confirm"
            dry_run = dry_run or target == "dry_run"
            index += 1
            continue

        if arg == _EXCLUDE_TYPE_FLAG or arg.startswith(f"{_EXCLUDE_TYPE_FLAG}="):
            value, index = _read_exclude_value(args, index)
            if value is None:
                return None, confirm, all_plans, dry_run, exclude_types, f"{_EXCLUDE_TYPE_FLAG} requires a plan type"
            exclude_types.append(value)
            continue

        if arg.startswith("-"):
            return None, confirm, all_plans, dry_run, exclude_types, f"Unrecognised argument: {arg}"

        positionals.append(arg)
        index += 1

    error = _validate_close_args(positionals, exclude_types, all_plans)
    if error:
        return None, confirm, all_plans, dry_run, exclude_types, error

    if all_plans:
        return None, confirm, True, dry_run, exclude_types, None

    if not positionals:
        return None, confirm, False, dry_run, exclude_types, "Plan number or --all required"

    json_handler.log_operation(
        "close_args_parsed",
        {"plan_num": positionals[0], "all_plans": all_plans, "dry_run": dry_run, "exclude_types": exclude_types},
    )
    return positionals[0], confirm, False, dry_run, exclude_types, None


def parse_restore_command_args(args: List[str]) -> Tuple[str | None, str | None]:
    """Parse arguments for restore command"""
    if len(args) < 1:
        return None, "Plan number required"

    plan_num = args[0]
    return plan_num, None
