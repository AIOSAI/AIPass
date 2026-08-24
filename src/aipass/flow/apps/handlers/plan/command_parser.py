# =================== AIPass ====================
# Name: command_parser.py
# Description: Command Argument Parser
# Version: 0.2.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================

"""
Command Argument Parser

Parses command-line arguments for plan operations.
"""

from typing import List, Tuple

from aipass.prax import logger
from aipass.flow.apps.handlers.json import json_handler

MODULE_NAME = "command_parser"


def parse_create_plan_args(args: List[str]) -> Tuple[str | None, str, str]:
    """
    Parse arguments for plan creation

    The third argument is treated as a plan type identifier and mapped
    to a plan_type_key understood by the plan_types plugin system:

    - No 3rd arg or "default" -> "flow_plans" (FPLAN with default template)
    - "master"                -> "master"     (FPLAN with master template)
    - "dplan"                 -> "dev_plans"  (DPLAN with default template)
    - Any other value         -> passed through for plan_type_loader lookup

    Args:
        args: List of command arguments

    Returns:
        Tuple of (location, subject, plan_type_key)
        - location: First arg or None
        - subject: Second arg or empty string
        - plan_type_key: Resolved plan type key for the plugin system

    Examples:
        >>> parse_create_plan_args(["@flow", "My task", "master"])
        ("@flow", "My task", "master")

        >>> parse_create_plan_args(["@flow", "My task", "dplan"])
        ("@flow", "My task", "dev_plans")

        >>> parse_create_plan_args([])
        (None, "", "flow_plans")

        >>> parse_create_plan_args(["@flow"])
        ("@flow", "", "flow_plans")
    """
    location = args[0] if len(args) > 0 else None
    subject = args[1] if len(args) > 1 else ""
    raw_type = args[2] if len(args) > 2 else "default"

    # Map raw type argument to plan_type_key via registry
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


# Every argument the close command understands. Anything outside this set
# REFUSES the run. The defect this removes: `--exclude APLAN` used to be
# byte-identical to passing nothing at all -- the flag was dropped and the bulk
# close proceeded, so the operator watched the dangerous thing happen while
# believing they had fenced it. A fallback that does the risky action on an
# argument it did not understand is the worst shape of fallback there is.
_CLOSE_BOOL_FLAGS = {
    "--all": "all_plans",
    "--confirm": "confirm",
    "--interactive": "confirm",
    "--dry-run": "dry_run",
    "--preview": "dry_run",
    # Accepted and inert: auto-confirm is already the default. Kept recognised
    # so old scripts keep working -- inert is not the same as unrecognised.
    "--yes": None,
    "-y": None,
}

_EXCLUDE_TYPE_FLAG = "--exclude-type"


def _registered_prefixes() -> List[str]:
    """Return the plan-type prefixes that are actually registered.

    Read from the template registry -- the same source `drone @flow templates`
    reads -- never a literal list. Types are registered over time; a hardcoded
    set goes stale the day someone adds a type that also must not be swept.
    """
    from aipass.flow.apps.handlers.template.registry_ops import get_prefix_map

    return sorted({prefix.upper() for prefix in get_prefix_map().values() if prefix})


def _read_exclude_value(args: List[str], index: int) -> Tuple[str | None, int]:
    """Read the value of an --exclude-type occurrence at `index`.

    Handles both ``--exclude-type APLAN`` and ``--exclude-type=APLAN``.

    Returns:
        (upper-cased type, next index), or (None, next index) when the flag
        carries no value -- a flag with nothing after it is a fence the
        operator believes they set, so it must refuse rather than pass.
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

    # Validate against the live registry, and name the valid ones. An unknown
    # type is a typo in a fence -- accepting it silently would let the sweep
    # run without the protection the operator asked for.
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
    """
    Parse arguments for close command

    Auto-confirms by default (running 'close' IS the intent).
    Use --confirm or --interactive to explicitly request a confirmation prompt.
    --yes/-y kept for backwards compatibility (now redundant, already auto-confirms).
    --dry-run or --preview previews what would be closed without taking action.
    --exclude-type <TYPE> holds a whole plan type back from --all; repeatable.

    Unrecognised arguments REFUSE the run -- see _CLOSE_BOOL_FLAGS.

    Args:
        args: Command arguments

    Returns:
        Tuple of (plan_num, confirm, all_plans, dry_run, exclude_types, error_message)
        - plan_num: Plan number from the positional arg, or None if --all or missing
        - confirm: True only if --confirm or --interactive flag present, False otherwise
        - all_plans: True if --all flag present, False otherwise
        - dry_run: True if --dry-run or --preview flag present, False otherwise
        - exclude_types: Upper-cased plan-type prefixes to hold back (may be empty)
        - error_message: None if valid, error string if invalid args

    Examples:
        >>> parse_close_command_args(["42"])
        ("42", False, False, False, [], None)

        >>> parse_close_command_args(["--all"])
        (None, False, True, False, [], None)

        >>> parse_close_command_args(["--all", "--exclude-type", "APLAN"])
        (None, False, True, False, ["APLAN"], None)

        >>> parse_close_command_args([])
        (None, False, False, False, [], "Plan number or --all required")
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
    """
    Parse arguments for restore command

    Args:
        args: Command arguments

    Returns:
        Tuple of (plan_num, error_message)
        - plan_num: Plan number from first arg, or None if missing
        - error_message: None if valid, error string if plan_num missing

    Examples:
        >>> parse_restore_command_args(["42"])
        ("42", None)

        >>> parse_restore_command_args(["0034"])
        ("0034", None)

        >>> parse_restore_command_args([])
        (None, "Plan number required")
    """
    if len(args) < 1:
        return None, "Plan number required"

    plan_num = args[0]
    return plan_num, None
