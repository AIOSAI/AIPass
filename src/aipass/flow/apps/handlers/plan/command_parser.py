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


def parse_close_command_args(args: List[str]) -> Tuple[str | None, bool, bool, bool, str | None]:
    """
    Parse arguments for close command

    Auto-confirms by default (running 'close' IS the intent).
    Use --confirm or --interactive to explicitly request a confirmation prompt.
    --yes/-y kept for backwards compatibility (now redundant, already auto-confirms).
    --dry-run or --preview previews what would be closed without taking action.

    Args:
        args: Command arguments

    Returns:
        Tuple of (plan_num, confirm, all_plans, dry_run, error_message)
        - plan_num: Plan number from first arg, or None if --all or missing
        - confirm: True only if --confirm or --interactive flag present, False otherwise
        - all_plans: True if --all flag present, False otherwise
        - dry_run: True if --dry-run or --preview flag present, False otherwise
        - error_message: None if valid, error string if invalid args

    Examples:
        >>> parse_close_command_args(["42"])
        ("42", False, False, False, None)

        >>> parse_close_command_args(["42", "--yes"])
        ("42", False, False, False, None)

        >>> parse_close_command_args(["42", "--confirm"])
        ("42", True, False, False, None)

        >>> parse_close_command_args(["42", "--interactive"])
        ("42", True, False, False, None)

        >>> parse_close_command_args(["--all"])
        (None, False, True, False, None)

        >>> parse_close_command_args(["--all", "--confirm"])
        (None, True, True, False, None)

        >>> parse_close_command_args(["42", "--dry-run"])
        ("42", False, False, True, None)

        >>> parse_close_command_args(["--all", "--preview"])
        (None, False, True, True, None)

        >>> parse_close_command_args([])
        (None, False, False, False, "Plan number or --all required")
    """
    # Check for --all flag
    all_plans = "--all" in args

    # Default: auto-confirm (confirm=False means no prompt)
    # --confirm or --interactive explicitly requests a prompt
    # --yes/-y kept for backwards compat (redundant, already auto-confirms)
    confirm = "--confirm" in args or "--interactive" in args

    # Check for --dry-run or --preview flag
    dry_run = "--dry-run" in args or "--preview" in args

    # If --all, plan_num is None
    if all_plans:
        return None, confirm, True, dry_run, None

    # Otherwise, need plan number
    # Filter out flag args to find the plan number
    non_flag_args = [a for a in args if not a.startswith("--") and a not in ("-y",)]
    if not non_flag_args:
        return None, False, False, dry_run, "Plan number or --all required"

    plan_num = non_flag_args[0]
    return plan_num, confirm, False, dry_run, None


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
