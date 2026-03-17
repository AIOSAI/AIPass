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

from pathlib import Path

from datetime import datetime
from typing import Optional, Dict, List
from threading import Lock

try:
    from aipass.cli.apps.modules import console
except ImportError:
    from rich.console import Console
    console = Console()

from aipass.prax.apps.handlers.json import json_handler

# Thread safety
_print_lock = Lock()

# Color schemes by event type and level
COLORS = {
    'file_created': 'green',
    'file_modified': 'yellow',
    'file_deleted': 'red',
    'file_moved': 'blue',
    'log_info': 'white',
    'log_warning': 'yellow',
    'log_error': 'red',
    'log_critical': 'bold red',
    'module_loaded': 'cyan',
    'module_error': 'red',
    'system_info': 'blue',
    'system_warning': 'yellow',
    'system_error': 'bold red',
}

# Symbols for different event types
SYMBOLS = {
    'file': '📁',
    'log': '📝',
    'module': '⚡',
    'system': '🔧',
    'error': '❌',
    'warning': '⚠️',
    'success': '✅',
    'info': 'ℹ️',
}

# Branch display width
BRANCH_WIDTH = 8

# Level-based color mapping (simplified)
LEVEL_COLORS = {
    'error': 'red',
    'warning': 'yellow',
    'critical': 'bold red',
    'info': 'white',
    'success': 'green',
}

# Branch-specific colors for visual distinction
BRANCH_COLORS = {
    'SEED': 'green',
    'DRONE': 'cyan',
    'FLOW': 'blue',
    'PRAX': 'magenta',
    'CLI': 'yellow',
    'CORTEX': 'bright_blue',
    'AI_MAIL': 'bright_cyan',
    'BACKUP_SYSTEM': 'bright_green',
    'MEMORY_BANK': 'bright_magenta',
    'DEVPULSE': 'bright_yellow',
    'API': 'bright_red',
    'SECURITY': 'red',
    'AIPASS': 'bold white',
    'TRIGGER': 'bright_red',
    'SPEAKEASY': 'bright_white',
    'THE_COMMONS': 'bright_green',
    'ASSISTANT': 'bright_yellow',
}


def print_event(event_type: str, branch: str, message: str, level: str = 'info', pid: Optional[int] = None):
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
        # For subagent labels like 'DEV_CENTRAL AGENT', use base branch color
        branch_upper = branch.upper()
        base_branch = branch_upper[:-6] if branch_upper.endswith(' AGENT') else branch_upper
        branch_color = BRANCH_COLORS.get(base_branch, 'white')

        # Format branch label with optional PID
        if pid:
            branch_label = f"{branch_upper}:{pid}"
        else:
            branch_label = branch_upper
        branch_formatted = f"[{branch_color}][{branch_label:<{BRANCH_WIDTH}}][/{branch_color}]"

        # Get message color based on level
        msg_color = LEVEL_COLORS.get(level, 'white')

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
        branch_color = BRANCH_COLORS.get(branch.upper(), 'white')
        console.print()
        console.print(f"[bold {branch_color}]{'─' * 60}[/bold {branch_color}]")

        # Build context line: CALLER → TARGET
        context_parts = []
        if caller and caller.upper() != 'UNKNOWN':
            caller_color = BRANCH_COLORS.get(caller.upper(), 'cyan')
            context_parts.append(f"[{caller_color}]{caller}[/{caller_color}]")
        if target:
            target_color = BRANCH_COLORS.get(target.upper(), 'cyan')
            if context_parts:
                context_parts.append(f"→ [{target_color}]{target}[/{target_color}]")
            else:
                context_parts.append(f"→ [{target_color}]{target}[/{target_color}]")

        if context_parts:
            console.print(f"  {' '.join(context_parts)}")

        console.print(f"[bold {branch_color}]▶ {command}[/bold {branch_color}]")
        console.print(f"[bold {branch_color}]{'─' * 60}[/bold {branch_color}]")


def get_file_category(filename: str) -> str:
    """Categorize a file by its type for display context.

    Args:
        filename: Just the filename (not full path)

    Returns:
        Short category tag like 'code', 'memory', 'config', etc.
    """
    name_lower = filename.lower()

    # Dashboard (check before general memory)
    if name_lower == 'dashboard.local.json':
        return 'dashboard'

    # Memory files
    if name_lower.endswith('.local.json') or name_lower.endswith('.id.json') or name_lower.endswith('.observations.json'):
        return 'memory'

    # Dev notes
    if name_lower == 'dev.local.md':
        return 'devnotes'

    # Config
    if name_lower.endswith('_config.json') or name_lower.endswith('config.json'):
        return 'config'

    # Documentation
    if name_lower.endswith('.md'):
        return 'docs'

    # Code
    if name_lower.endswith('.py'):
        return 'code'

    # Data/JSON
    if name_lower.endswith('.json'):
        return 'data'

    # Mail
    if 'ai_mail' in name_lower or 'mail' in name_lower:
        return 'mail'

    return ''


def print_file_event(event_type: str, branch: str, file_path: str, details: Optional[str] = None):
    """
    Print file system event

    Args:
        event_type: created, modified, deleted, moved
        branch: Branch name
        file_path: Path to file
        details: Optional additional details
    """
    # Get file category for context
    filename = file_path.split('/')[-1] if '/' in file_path else file_path
    category = get_file_category(filename)

    # Build message with category context
    category_tag = f"[dim]\\[{category}][/dim] " if category else ""
    message = f"{category_tag}{event_type.upper()}: {file_path}"
    if details:
        message += f" ({details})"

    # Map file event types to levels for color coding
    level_map = {
        'created': 'success',
        'modified': 'info',
        'deleted': 'warning',
        'moved': 'info'
    }
    level = level_map.get(event_type, 'info')
    print_event('file', branch, message, level)


def print_log_event(branch: str, level: str, message: str, source: Optional[str] = None):
    """
    Print log file event

    Args:
        branch: Branch name
        level: Log level (info, warning, error, critical)
        message: Log message
        source: Optional source file/module
    """
    # Add level prefix for errors and warnings
    if level in ['error', 'critical']:
        log_msg = f"ERROR: {message}"
    elif level == 'warning':
        log_msg = f"WARNING: {message}"
    else:
        log_msg = message

    if source:
        log_msg = f"[{source}] {log_msg}"

    print_event('log', branch, log_msg, level)


def print_module_event(branch: str, module_name: str, status: str, details: Optional[str] = None):
    """
    Print module loading event

    Args:
        branch: Branch name
        module_name: Name of module
        status: loaded, error, reloaded, started, stopped
        details: Optional error or status details
    """
    message = f"Module {status}: {module_name}"
    if details:
        message += f" - {details}"

    # Map status to level for color coding
    level_map = {
        'error': 'error',
        'failed': 'error',
        'loaded': 'success',
        'started': 'success',
        'stopped': 'warning',
        'reloaded': 'info'
    }
    level = level_map.get(status, 'info')
    print_event('module', branch, message, level)


def print_header():
    """Print monitoring system header"""
    with _print_lock:
        console.print("\n[bold cyan]═══════════════════════════════════════════[/bold cyan]")
        console.print("[bold cyan]    PRAX Monitoring System v0.1.0[/bold cyan]")
        console.print("[bold cyan]═══════════════════════════════════════════[/bold cyan]")
        console.print("[dim]Type 'help' for commands, 'quit' to exit[/dim]\n")


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
            if filters.get('file_types'):
                console.print(f"    File types: {', '.join(filters['file_types'])}")
            if filters.get('log_levels'):
                console.print(f"    Log levels: {', '.join(filters['log_levels'])}")
            if filters.get('exclude_patterns'):
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


def print_error(message: str, details: Optional[str] = None):
    """
    Print error message

    Args:
        message: Error message
        details: Optional error details
    """
    with _print_lock:
        console.print(f"[bold red]ERROR:[/bold red] {message}")
        if details:
            console.print(f"[dim]{details}[/dim]")


def print_warning(message: str):
    """Print warning message"""
    with _print_lock:
        console.print(f"[yellow]WARNING:[/yellow] {message}")


def print_success(message: str):
    """Print success message"""
    with _print_lock:
        console.print(f"[green]SUCCESS:[/green] {message}")


def print_info(message: str):
    """Print info message"""
    with _print_lock:
        console.print(f"[blue]INFO:[/blue] {message}")


def clear_screen():
    """Clear terminal screen"""
    with _print_lock:
        console.clear()


def print_separator():
    """Print visual separator"""
    with _print_lock:
        console.print("[dim]─────────────────────────────────────────[/dim]")


def format_event_summary(events: Dict[str, int]) -> str:
    """
    Format event summary statistics

    Args:
        events: Dictionary of event type counts

    Returns:
        Formatted summary string
    """
    parts = []
    for event_type, count in events.items():
        if count > 0:
            parts.append(f"{event_type}: {count}")
    return ", ".join(parts) if parts else "No events"
