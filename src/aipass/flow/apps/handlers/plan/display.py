# =================== AIPass ====================
# Name: display.py
# Description: Plan Display Handler
# Version: 0.1.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================

"""
Plan Display Handler

All display and formatting functions for plan operations.
Returns formatted strings - caller handles actual output.
"""

from pathlib import Path
from typing import Dict, Any


# CREATE PLAN DISPLAY FUNCTIONS

def display_plan_created(
    plan_num: int,
    relative_location: str,
    subject: str,
    template_type: str,
    prefix: str = "FPLAN",
    digits: int = 4,
) -> str:
    """
    Format plan creation success messages

    Args:
        plan_num: Created plan number
        relative_location: Relative path to plan
        subject: Plan subject
        template_type: Template used
        prefix: Plan prefix (e.g. "FPLAN", "DPLAN")
        digits: Number of zero-padded digits in the plan number

    Returns:
        Multi-line formatted string for display
    """
    plan_id = f"{prefix}-{plan_num:0{digits}d}"
    lines = [
        f"[FLOW] Created {plan_id} in {relative_location}",
        f"[FLOW] Template: {template_type}",
        f"[FLOW] Subject: {subject}"
    ]
    return "\n".join(lines)


def display_plan_result(
    success: bool,
    plan_num: int,
    location: str,
    template_type: str,
    error: str,
    prefix: str = "FPLAN",
    digits: int = 4,
) -> str:
    """
    Display plan creation result with rich formatting

    Args:
        success: True if plan created successfully
        plan_num: Plan number (ignored if not success)
        location: Relative location (ignored if not success)
        template_type: Template type (ignored if not success)
        error: Error message (ignored if success)
        prefix: Plan prefix (e.g. "FPLAN", "DPLAN")
        digits: Number of zero-padded digits in the plan number

    Returns:
        Formatted result string with emoji and color markup
    """
    if success:
        plan_id = f"{prefix}-{plan_num:0{digits}d}"
        return f"\n[green]Created {plan_id} in {location}/ using {template_type} template[/green]\n"
    else:
        return f"\n[red]ERROR: {error}[/red]\n"


# DELETE PLAN DISPLAY FUNCTIONS

def format_plan_deletion_header(plan_key: str, plan_info: Dict[str, Any]) -> str:
    """
    Format plan information header for deletion confirmation

    Args:
        plan_key: Normalized plan number (e.g., "0001")
        plan_info: Plan metadata dictionary from registry

    Returns:
        Formatted header string with Rich markup for plan details
    """
    plan_file = Path(plan_info.get("file_path", ""))

    lines = [
        "",
        "[bold cyan]╭─ Close FPLAN-" + plan_key + " ─╮[/bold cyan]",
        "",
        f"  [dim]Location:[/dim] {plan_info.get('relative_path', 'unknown')}",
        f"  [dim]Subject:[/dim]  {plan_info.get('subject', 'N/A')}",
        f"  [dim]Status:[/dim]   {plan_info.get('status', 'unknown')}",
        f"  [dim]File:[/dim]     {plan_file}",
        "",
        "[dim]─" + "─" * 68 + "[/dim]",
        ""
    ]
    return "\n".join(lines)


def format_plan_error(
    error_type: str,
    plan_num: str | None = None,
    details: str | None = None
) -> str:
    """
    Format error messages for plan operations

    Args:
        error_type: Type of error ("not_found", "invalid_number", "general")
        plan_num: Plan number if relevant
        details: Additional error details

    Returns:
        Formatted error message
    """
    if error_type == "not_found":
        return f"[ERROR] FPLAN-{plan_num} not found in registry"
    elif error_type == "invalid_number":
        return f"[ERROR] Invalid plan number: {plan_num}"
    elif error_type == "general":
        return f"[ERROR] Error deleting plan: {details}"
    else:
        return "[ERROR] Unknown error"


def format_plan_deletion_success(plan_key: str) -> str:
    """
    Format success message for completed plan deletion

    Args:
        plan_key: Normalized plan number (e.g., "0001")

    Returns:
        Formatted success message
    """
    return f"\n[SUCCESS] FPLAN-{plan_key} deleted successfully\n"


def format_registry_removal_status(plan_key: str) -> str:
    """
    Format status message for registry removal

    Args:
        plan_key: Normalized plan number (e.g., "0001")

    Returns:
        Formatted status message
    """
    return f"[OK] Removed FPLAN-{plan_key} from registry"


def format_deletion_cancelled() -> str:
    """
    Format cancellation message

    Returns:
        Formatted cancellation message
    """
    return "Deletion cancelled"


def format_delete_usage_error() -> str:
    """
    Format usage error message for delete command

    Returns:
        Formatted usage instructions
    """
    lines = [
        "",
        "ERROR: Plan number required",
        "",
        "Usage: delete <plan_number> [--yes]",
        ""
    ]
    return "\n".join(lines)


# RESTORE PLAN DISPLAY FUNCTIONS

def format_restore_header(plan_key: str, plan_info: Dict[str, Any]) -> str:
    """
    Format plan information header for restore confirmation

    Args:
        plan_key: Normalized plan number (e.g., "0001")
        plan_info: Plan metadata dictionary from registry

    Returns:
        Formatted header string with Rich markup for plan details
    """
    plan_file = Path(plan_info.get("file_path", ""))
    closed_date = plan_info.get("closed", "unknown")
    closed_reason = plan_info.get("closed_reason", "N/A")

    lines = [
        "",
        "[bold cyan]╭─ Restore FPLAN-" + plan_key + " ─╮[/bold cyan]",
        "",
        f"  [dim]Location:[/dim]      {plan_info.get('relative_path', 'unknown')}",
        f"  [dim]Subject:[/dim]       {plan_info.get('subject', 'N/A')}",
        f"  [dim]Status:[/dim]        {plan_info.get('status', 'unknown')}",
        f"  [dim]Closed:[/dim]        {closed_date}",
        f"  [dim]Closed Reason:[/dim] {closed_reason}",
        f"  [dim]File:[/dim]          {plan_file}",
        "",
        "[dim]─" + "─" * 68 + "[/dim]",
        ""
    ]
    return "\n".join(lines)


def format_restore_success(plan_key: str, restored_location: str | None = None) -> str:
    """
    Format success message for completed plan restore

    Args:
        plan_key: Normalized plan number (e.g., "0001")
        restored_location: Where the plan was restored to

    Returns:
        Formatted success message
    """
    if restored_location:
        return f"\n[SUCCESS] FPLAN-{plan_key} restored to open status at: {restored_location}\n"
    return f"\n[SUCCESS] FPLAN-{plan_key} restored to open status\n"


def format_restore_error(error_type: str, plan_key: str | None = None, details: str | None = None) -> str:
    """
    Format error messages for restore operations

    Args:
        error_type: Type of error ("not_found", "already_open", "file_missing", "invalid_number", "general")
        plan_key: Plan number if relevant
        details: Additional error details

    Returns:
        Formatted error message
    """
    if error_type == "not_found":
        return f"[ERROR] FPLAN-{plan_key} not found in registry"
    elif error_type == "already_open":
        return f"[ERROR] FPLAN-{plan_key} is already open - cannot restore what isn't closed"
    elif error_type == "file_missing":
        return f"[ERROR] FPLAN-{plan_key} file not found at registered location - move file back first"
    elif error_type == "invalid_number":
        return f"[ERROR] Invalid plan number: {plan_key}"
    elif error_type == "general":
        return f"[ERROR] Error restoring plan: {details}"
    else:
        return "[ERROR] Unknown error"


def format_restore_usage_error() -> str:
    """
    Format usage error message for restore command

    Returns:
        Formatted usage instructions
    """
    lines = [
        "",
        "ERROR: Plan number required",
        "",
        "Usage: restore <plan_number>",
        ""
    ]
    return "\n".join(lines)


# LIST PLAN DISPLAY FUNCTIONS

def format_plan_info(plan_key: str, plan_info: Dict[str, Any]) -> str:
    """
    Format a single plan's information for display

    Args:
        plan_key: Plan number (e.g., "0001")
        plan_info: Plan metadata dictionary

    Returns:
        Formatted string with plan details
    """
    from datetime import datetime

    subject = plan_info.get("subject", "No subject")
    location = plan_info.get("relative_path", "unknown")
    status = plan_info.get("status", "unknown")
    created = plan_info.get("created", "unknown")

    # Format created date if it's an ISO timestamp
    if created != "unknown":
        try:
            dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
            created = dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, AttributeError):
            pass  # Keep original value if parsing fails

    return f"  FPLAN-{plan_key}  [{status:>6}]  {location:<30}  {subject:<40}  {created}"


def format_plans_list(
    plans: Dict[str, Dict[str, Any]],
    filter_status: str | None = None,
    show_header: bool = True
) -> str:
    """
    Format multiple plans for display with optional filtering

    Args:
        plans: Dictionary of plan_key -> plan_info
        filter_status: Filter by status ("open", "closed", None for all)
        show_header: Whether to show column headers

    Returns:
        Formatted multi-line string with plan list
    """
    if not plans:
        return "[dim]No plans found in registry[/dim]"

    # Filter plans if needed
    if filter_status:
        filtered_plans = {
            k: v for k, v in plans.items()
            if v.get("status") == filter_status
        }
    else:
        filtered_plans = plans

    if not filtered_plans:
        status_text = filter_status if filter_status else "all"
        return f"[dim]No {status_text} plans found[/dim]"

    lines = []

    if show_header:
        lines.append("")
        status_text = f" ({filter_status})" if filter_status else ""
        lines.append(f"[bold cyan]╭─ PLAN Registry{status_text} ─╮[/bold cyan]")
        lines.append("")
        lines.append(f"  [dim]{'Number':<8}  {'Status':<8}  {'Location':<30}  {'Subject':<40}  Created[/dim]")
        lines.append("[dim]─" * 120 + "[/dim]")

    # Sort by plan number
    sorted_plans = sorted(filtered_plans.items(), key=lambda x: x[0])

    for plan_key, plan_info in sorted_plans:
        lines.append(format_plan_info(plan_key, plan_info))

    if show_header:
        lines.append("[dim]─" * 120 + "[/dim]")
        lines.append("")

    return "\n".join(lines)


def format_statistics_summary(stats: Dict[str, Any]) -> str:
    """
    Format statistics summary

    Args:
        stats: Statistics dictionary from get_registry_statistics

    Returns:
        Formatted statistics string
    """
    lines = [
        "",
        f"[bold]Summary:[/bold]",
        f"  Total plans: {stats['total_plans']}",
        f"  Open: {stats['open_plans']}",
        f"  Closed: {stats['closed_plans']}"
    ]

    if stats['other_plans'] > 0:
        lines.append(f"  Other: {stats['other_plans']}")

    lines.append("")

    return "\n".join(lines)
