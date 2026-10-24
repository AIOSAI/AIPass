# =================== AIPass ====================
# Name: unified_stream.py
# Description: Unified Display Handler
# Version: 0.4.0
# Created: 2025-11-23
# Modified: 2026-10-24
# =============================================

"""Unified Stream Display Handler"""

from datetime import datetime
from typing import Optional
from threading import Lock

from rich.markup import escape

from aipass.prax.apps.modules.logger import get_direct_logger

logger = get_direct_logger()

try:
    from aipass.cli.apps.modules import console
except ImportError as e:
    logger.info(f"[unified_stream] CLI console not available, falling back to rich.Console: {e}")
    from rich.console import Console

    console = Console()

_print_lock = Lock()


def _plain(text: str) -> str:
    """Escape text that came from a branch, so Rich shows it instead of parsing it.

    ``[/usr/bin]`` raises MarkupError and kills the display thread: escape all dynamic text.
    """
    return escape(str(text))


# Wide enough for three-tier labels like AIPASS/DEVPULSE/OPUS
BRANCH_WIDTH = 24

LEVEL_COLORS = {
    "error": "red",
    "warning": "yellow",
    "critical": "bold red",
    "info": "white",
    "success": "green",
}

# Three-tier labels (AIPASS/DEVPULSE/OPUS) key on their first segment.
BRANCH_COLORS = {
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
    "AIPASS": "bold white",  # All internal AIPass agent sessions
    "AIPL": "bright_blue",  # AIPL external project
    "VERA-STUDIO": "bright_cyan",  # Vera Studio external project
}


def print_event(event_type: str, branch: str, message: str, level: str = "info", pid: Optional[int] = None):
    """Format and print event with branch attribution."""
    with _print_lock:
        timestamp = datetime.now().strftime("%H:%M:%S")

        branch_upper = branch.upper()
        base_branch = branch_upper.split("/")[0]  # strip model tag
        if base_branch.endswith(" AGENT"):
            base_branch = base_branch[:-6]
        branch_color = BRANCH_COLORS.get(base_branch, "white")

        # The brackets are meant to be seen: escape the whole group, or a
        # lowercase label is parsed as a tag.
        if pid:
            branch_label = f"{branch_upper}:{pid}"
        else:
            branch_label = branch_upper
        label_text = _plain(f"[{branch_label:<{BRANCH_WIDTH}}]")
        branch_formatted = f"[{branch_color}]{label_text}[/{branch_color}]"

        msg_color = LEVEL_COLORS.get(level, "white")

        console.print(f"[dim]{timestamp}[/dim] {branch_formatted} [{msg_color}]{_plain(message)}[/{msg_color}]")


def print_command_separator(branch: str, command: str, caller: Optional[str] = None, target: Optional[str] = None):
    """
    Print prominent command separator/header with caller attribution.
    """
    with _print_lock:
        branch_color = BRANCH_COLORS.get(branch.upper(), "white")
        console.print()
        console.print(f"[bold {branch_color}]{'─' * 60}[/bold {branch_color}]")

        context_parts = []
        if caller and caller.upper() != "UNKNOWN":
            caller_color = BRANCH_COLORS.get(caller.upper(), "cyan")
            context_parts.append(f"[{caller_color}]{_plain(caller)}[/{caller_color}]")
        if target:
            target_color = BRANCH_COLORS.get(target.upper(), "cyan")
            context_parts.append(f"→ [{target_color}]{_plain(target)}[/{target_color}]")

        if context_parts:
            console.print(f"  {' '.join(context_parts)}")

        console.print(f"[bold {branch_color}]▶ {_plain(command)}[/bold {branch_color}]")
        console.print(f"[bold {branch_color}]{'─' * 60}[/bold {branch_color}]")


def print_hook_event(branch: str, message: str, action: str = "unknown"):
    """Print a hook event with distinct fired/skipped styling."""
    with _print_lock:
        timestamp = datetime.now().strftime("%H:%M:%S")
        if action == "fired":
            style = "bold green"
            symbol = "⚡"
        elif action == "skipped":
            style = "dim"
            symbol = "·"
        else:
            style = "white"
            symbol = "?"
        branch_color = BRANCH_COLORS.get(branch.upper(), "white")
        branch_label = f"[{branch_color}]{_plain(branch.upper())}[/{branch_color}]"
        console.print(
            f"[dim]{timestamp}[/dim] [{style}]{symbol} HOOK[/{style}] {branch_label} [{style}]{_plain(message)}[/{style}]"
        )
