# =================== AIPass ====================
# Name: unified_stream.py
# Description: Unified Display Handler
# Version: 0.1.1
# Created: 2025-11-23
# Modified: 2026-03-09
# =============================================

"""
Unified Stream Display Handler

Single point for all monitoring terminal output with:
- Event formatting with branch attribution
- Color coding by event type
- Thread-safe console output
- Status displays and headers
"""

from datetime import datetime
from typing import Optional, Dict, List
from threading import Lock

from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.prax.apps.handlers.json import json_handler

logger = get_direct_logger()

try:
    from aipass.cli.apps.modules import console
except ImportError as e:
    logger.info(f"[unified_stream] CLI console not available, falling back to rich.Console: {e}")
    from rich.console import Console

    console = Console()

# Thread safety
_print_lock = Lock()

# Color schemes by event type and level
COLORS = {
    "file_created": "green",
    "file_modified": "yellow",
    "file_deleted": "red",
    "file_moved": "blue",
    "log_info": "white",
    "log_warning": "yellow",
    "log_error": "red",
    "log_critical": "bold red",
    "module_loaded": "cyan",
    "module_error": "red",
    "system_info": "blue",
    "system_warning": "yellow",
    "system_error": "bold red",
}

# Symbols for different event types
SYMBOLS = {
    "file": "📁",
    "log": "📝",
    "module": "⚡",
    "system": "🔧",
    "error": "❌",
    "warning": "⚠️",
    "success": "✅",
    "info": "ℹ️",
}

# Branch display width — wide enough for three-tier labels like AIPASS/DEVPULSE/OPUS
BRANCH_WIDTH = 24

# Level-based color mapping (simplified)
LEVEL_COLORS = {
    "error": "red",
    "warning": "yellow",
    "critical": "bold red",
    "info": "white",
    "success": "green",
}

# Branch-specific colors for visual distinction.
# For three-tier labels (AIPASS/DEVPULSE/OPUS), the base key is the first segment (AIPASS).
# Internal AIPass branches also appear as bare names for non-session events.
BRANCH_COLORS = {
    # Internal AIPass branches — individually colored for non-session events
    "SEEDGO": "green",
    "DRONE": "cyan",
    "FLOW": "blue",
    "PRAX": "magenta",
    "CLI": "yellow",
    "AI_MAIL": "bright_cyan",
    "BACKUP": "bright_green",
    "MEMORY": "bright_magenta",
    "DEVPULSE": "bright_yellow",
    "API": "bright_red",
    "SECURITY": "red",
    "TRIGGER": "bright_red",
    "SPEAKEASY": "bright_white",
    "THE_COMMONS": "bright_green",
    "ASSISTANT": "bright_yellow",
    # Project-level keys — used for three-tier labels (first segment of PROJECT/AGENT/MODEL)
    "AIPASS": "bold white",  # All internal AIPass agent sessions
    "AIPL": "bright_blue",  # AIPL external project
    "VERA-STUDIO": "bright_cyan",  # Vera Studio external project
}


def print_event(event_type: str, branch: str, message: str, level: str = "info", pid: Optional[int] = None):
    """
    Format and print event with branch attribution

    Format:
    [HH:MM:SS] [BRANCH:PID] Message text

    Color coding:
    - Timestamp: dim
    - Branch name: unique color per branch
    - Message: colored by level (error=red, warning=yellow, info=white)

    Args:
        event_type: Type of event (file, log, module, system)
        branch: Branch name for attribution
        message: Event message
        level: Event level (info, warning, error, critical)
        pid: Optional process ID for the active agent
    """
    json_handler.log_operation("stream_output", {"event_type": event_type, "branch": branch, "level": level})

    with _print_lock:
        # Timestamp
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Get branch color (unique per branch)
        # Strip suffixes for color lookup: 'DEVPULSE AGENT' → DEVPULSE, 'DEVPULSE/opus' → DEVPULSE
        branch_upper = branch.upper()
        base_branch = branch_upper.split("/")[0]  # strip model tag
        if base_branch.endswith(" AGENT"):
            base_branch = base_branch[:-6]
        branch_color = BRANCH_COLORS.get(base_branch, "white")

        # Format branch label with optional PID
        if pid:
            branch_label = f"{branch_upper}:{pid}"
        else:
            branch_label = branch_upper
        branch_formatted = f"[{branch_color}][{branch_label:<{BRANCH_WIDTH}}][/{branch_color}]"

        # Get message color based on level
        msg_color = LEVEL_COLORS.get(level, "white")

        # Format and print - timestamp, branch colored, message colored by level
        console.print(f"[dim]{timestamp}[/dim] {branch_formatted} [{msg_color}]{message}[/{msg_color}]")


def print_command_separator(branch: str, command: str, caller: Optional[str] = None, target: Optional[str] = None):
    """
    Print prominent command separator/header with caller attribution.

    Args:
        branch: Branch that executed the command (log location)
        command: The command that was run
        caller: Branch that initiated the command (optional)
        target: Branch being acted upon (optional, e.g. audit target)
    """
    with _print_lock:
        branch_color = BRANCH_COLORS.get(branch.upper(), "white")
        console.print()
        console.print(f"[bold {branch_color}]{'─' * 60}[/bold {branch_color}]")

        # Build context line: CALLER → TARGET
        context_parts = []
        if caller and caller.upper() != "UNKNOWN":
            caller_color = BRANCH_COLORS.get(caller.upper(), "cyan")
            context_parts.append(f"[{caller_color}]{caller}[/{caller_color}]")
        if target:
            target_color = BRANCH_COLORS.get(target.upper(), "cyan")
            if context_parts:
                context_parts.append(f"→ [{target_color}]{target}[/{target_color}]")
            else:
                context_parts.append(f"→ [{target_color}]{target}[/{target_color}]")

        if context_parts:
            console.print(f"  {' '.join(context_parts)}")

        console.print(f"[bold {branch_color}]▶ {command}[/bold {branch_color}]")
        console.print(f"[bold {branch_color}]{'─' * 60}[/bold {branch_color}]")


def print_status(watched_branches: List[str], verbosity: int, filters: Optional[Dict] = None):
    """
    Display current monitoring status

    Args:
        watched_branches: List of branches being monitored
        verbosity: Current verbosity level (0-2)
        filters: Optional filter configuration
    """
    with _print_lock:
        console.print("\n[bold]Current Status:[/bold]")
        console.print(f"  Watching: [cyan]{', '.join(watched_branches) if watched_branches else 'All branches'}[/cyan]")
        console.print(f"  Verbosity: [yellow]{verbosity}[/yellow]")

        if filters:
            console.print("  Filters:")
            if filters.get("file_types"):
                console.print(f"    File types: {', '.join(filters['file_types'])}")
            if filters.get("log_levels"):
                console.print(f"    Log levels: {', '.join(filters['log_levels'])}")
            if filters.get("exclude_patterns"):
                console.print(f"    Excluded: {', '.join(filters['exclude_patterns'])}")
        console.print()


def print_help():
    """Display help information"""
    with _print_lock:
        console.print("\n[bold]Available Commands:[/bold]")
        console.print("  [cyan]help[/cyan]              - Show this help")
        console.print("  [cyan]status[/cyan]            - Show monitoring status")
        console.print("  [cyan]clear[/cyan]             - Clear screen")
        console.print("  [cyan]filter <type>[/cyan]    - Add filter")
        console.print("  [cyan]verbosity <0-2>[/cyan]  - Set verbosity level")
        console.print("  [cyan]watch <branch>[/cyan]   - Watch specific branch")
        console.print("  [cyan]unwatch <branch>[/cyan] - Stop watching branch")
        console.print("  [cyan]quit/exit[/cyan]        - Exit monitoring\n")
