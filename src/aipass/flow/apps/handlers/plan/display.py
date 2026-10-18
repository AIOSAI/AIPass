# =================== AIPass ====================
# Name: display.py
# Description: Plan Display Handler
# Version: 0.2.0
# Created: 2025-11-15
# Modified: 2026-10-17
# =============================================

"""
Plan Display Handler

Returns formatted strings - caller handles actual output.
"""

from pathlib import Path
from typing import Dict, Any

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.flow.apps.handlers.json import json_handler


def display_plan_created(
    plan_num: int,
    relative_location: str,
    subject: str,
    template_type: str,
    prefix: str = "FPLAN",
    digits: int = 4,
) -> str:
    """Format plan creation success messages"""
    plan_id = f"{prefix}-{plan_num:0{digits}d}"
    lines = [
        f"[FLOW] Created {plan_id} in {relative_location}",
        f"[FLOW] Template: {template_type}",
        f"[FLOW] Subject: {subject}",
    ]
    json_handler.log_operation(
        "plan_displayed", {"plan_id": plan_id, "location": relative_location, "template": template_type}
    )
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
    """Display plan creation result with rich formatting"""
    if success:
        plan_id = f"{prefix}-{plan_num:0{digits}d}"
        return f"\n[green]Created {plan_id} in {location}/ using {template_type} template[/green]\n"
    else:
        return f"\n[red]ERROR: {error}[/red]\n"


def format_plan_deletion_header(plan_key: str, plan_info: Dict[str, Any], prefix: str = "FPLAN") -> str:
    """Format plan information header for deletion confirmation"""
    plan_file = Path(plan_info.get("file_path", ""))

    lines = [
        "",
        f"[bold cyan]╭─ Close {prefix}-" + plan_key + " ─╮[/bold cyan]",
        "",
        f"  [dim]Location:[/dim] {plan_info.get('relative_path', 'unknown')}",
        f"  [dim]Subject:[/dim]  {plan_info.get('subject', 'N/A')}",
        f"  [dim]Status:[/dim]   {plan_info.get('status', 'unknown')}",
        f"  [dim]File:[/dim]     {plan_file}",
        "",
        "[dim]─" + "─" * 68 + "[/dim]",
        "",
    ]
    return "\n".join(lines)


def format_plan_error(
    error_type: str,
    plan_num: str | None = None,
    details: str | None = None,
    prefix: str = "FPLAN",
) -> str:
    """Format error messages for plan operations"""
    if error_type == "not_found":
        return f"[ERROR] {prefix}-{plan_num} not found in registry"
    elif error_type == "invalid_number":
        return f"[ERROR] Invalid plan number: {plan_num}"
    elif error_type == "general":
        return f"[ERROR] Error deleting plan: {details}"
    else:
        return "[ERROR] Unknown error"


def format_plan_deletion_success(plan_key: str, prefix: str = "FPLAN") -> str:
    """Format success message for completed plan deletion"""
    return f"\n[SUCCESS] {prefix}-{plan_key} closed successfully\n"


def format_deletion_cancelled() -> str:
    """Format cancellation message"""
    return "Deletion cancelled"


def format_delete_usage_error() -> str:
    """Format usage error message for delete command"""
    lines = ["", "ERROR: Plan number required", "", "Usage: delete <plan_number> [--yes]", ""]
    return "\n".join(lines)


def format_restore_header(plan_key: str, plan_info: Dict[str, Any], prefix: str = "FPLAN") -> str:
    """Format plan information header for restore confirmation"""
    plan_file = Path(plan_info.get("file_path", ""))
    closed_date = plan_info.get("closed", "unknown")
    closed_reason = plan_info.get("closed_reason", "N/A")

    lines = [
        "",
        f"[bold cyan]╭─ Restore {prefix}-" + plan_key + " ─╮[/bold cyan]",
        "",
        f"  [dim]Location:[/dim]      {plan_info.get('relative_path', 'unknown')}",
        f"  [dim]Subject:[/dim]       {plan_info.get('subject', 'N/A')}",
        f"  [dim]Status:[/dim]        {plan_info.get('status', 'unknown')}",
        f"  [dim]Closed:[/dim]        {closed_date}",
        f"  [dim]Closed Reason:[/dim] {closed_reason}",
        f"  [dim]File:[/dim]          {plan_file}",
        "",
        "[dim]─" + "─" * 68 + "[/dim]",
        "",
    ]
    return "\n".join(lines)


def format_restore_success(plan_key: str, restored_location: str | None = None, prefix: str = "FPLAN") -> str:
    """Format success message for completed plan restore"""
    if restored_location:
        return f"\n[SUCCESS] {prefix}-{plan_key} restored to open status at: {restored_location}\n"
    return f"\n[SUCCESS] {prefix}-{plan_key} restored to open status\n"


def format_restore_error(
    error_type: str, plan_key: str | None = None, details: str | None = None, prefix: str = "FPLAN"
) -> str:
    """Format error messages for restore operations"""
    if error_type == "not_found":
        return f"[ERROR] {prefix}-{plan_key} not found in registry"
    elif error_type == "already_open":
        return f"[ERROR] {prefix}-{plan_key} is already open - cannot restore what isn't closed"
    elif error_type == "file_missing":
        return f"[ERROR] {prefix}-{plan_key} file not found at registered location - move file back first"
    elif error_type == "invalid_number":
        return f"[ERROR] Invalid plan number: {plan_key}"
    elif error_type == "general":
        return f"[ERROR] Error restoring plan: {details}"
    else:
        return "[ERROR] Unknown error"


def format_restore_usage_error() -> str:
    """Format usage error message for restore command"""
    lines = ["", "ERROR: Plan number required", "", "Usage: restore <plan_number>", ""]
    return "\n".join(lines)


def format_plan_info(plan_key: str, plan_info: Dict[str, Any], prefix: str = "FPLAN") -> str:
    """Format a single plan's information for display"""
    from datetime import datetime

    # list_ops tags _source_prefix and _plan_num when merging multi-registry plans.
    display_prefix = plan_info.get("_source_prefix", prefix)

    subject = plan_info.get("subject", "No subject")
    location = plan_info.get("relative_path", "unknown")
    status = plan_info.get("status", "unknown")
    created = plan_info.get("created", "unknown")

    if created != "unknown":
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            created = dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, AttributeError) as e:
            logger.warning(f"[display] Failed to parse created date '{created}': {e}")

    display_num = plan_info.get("_plan_num", plan_key)
    return f"  {display_prefix}-{display_num}  [{status:>6}]  {location:<30}  {subject:<40}  {created}"


def format_plans_list(
    plans: Dict[str, Dict[str, Any]], filter_status: str | None = None, show_header: bool = True
) -> str:
    """Format multiple plans for display with optional filtering"""
    if not plans:
        return "[dim]No plans found in registry[/dim]"

    if filter_status:
        filtered_plans = {k: v for k, v in plans.items() if v.get("status") == filter_status}
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

    sorted_plans = sorted(filtered_plans.items(), key=lambda x: x[0])

    for plan_key, plan_info in sorted_plans:
        lines.append(format_plan_info(plan_key, plan_info))

    if show_header:
        lines.append("[dim]─" * 120 + "[/dim]")
        lines.append("")

    return "\n".join(lines)


def format_statistics_summary(stats: Dict[str, Any]) -> str:
    """Format statistics summary"""
    lines = [
        "",
        "[bold]Summary:[/bold]",
        f"  Total plans: {stats['total_plans']}",
        f"  Open: {stats['open_plans']}",
        f"  Closed: {stats['closed_plans']}",
    ]

    if stats["other_plans"] > 0:
        lines.append(f"  Other: {stats['other_plans']}")

    lines.append("")

    return "\n".join(lines)
