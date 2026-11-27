# =================== AIPass ====================
# Name: unified_stream.py
# Description: Unified Display Handler
# Version: 0.7.0
# Created: 2025-11-23
# Modified: 2026-11-22
# =============================================

"""Unified Stream Display Handler"""

from datetime import datetime
from typing import Optional
from threading import Lock

from rich.markup import escape

from aipass.cli import console


_print_lock = Lock()


def _plain(text: str) -> str:
    """Escape text that came from a branch, so Rich shows it instead of parsing it.

    ``[/usr/bin]`` raises MarkupError and kills the display thread: escape all dynamic text.
    """
    return escape(str(text))


# Wide enough for three-tier labels like aipass/devpulse/opus
BRANCH_WIDTH = 24

LEVEL_COLORS = {
    "error": "red",
    "warning": "yellow",
    "critical": "bold red",
    "info": "white",
    "success": "green",
}

# Three-tier labels (aipass/devpulse/opus) key on their first segment.
BRANCH_COLORS = {
    "sentry": "green",
    "drone": "cyan",
    "flow": "blue",
    "prax": "magenta",
    "cli": "yellow",
    "ai_mail": "bright_cyan",
    "backup": "bright_green",
    "memory": "bright_magenta",
    "devpulse": "bright_yellow",
    "api": "bright_red",
    "security": "red",
    "trigger": "bright_red",
    "speakeasy": "bright_white",
    "commons": "bright_green",
    "canary_test": "bright_white",
    "daemon": "blue",
    "hooks": "bright_blue",
    "skills": "bright_magenta",
    "spawn": "green",
    "assistant": "bright_yellow",
    "aipass": "bold white",  # All internal AIPass agent sessions
    "aipl": "bright_blue",  # AIPL external project
    "vera-studio": "bright_cyan",  # Vera Studio external project
}


def print_event(branch: str, message: str, level: str = "info", pid: Optional[int] = None):
    """Format and print event with branch attribution."""
    with _print_lock:
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Labels arrive lowercase; sentinels (UNKNOWN, SYSTEM, CODEX) keep their case on screen.
        base_branch = branch.lower().split("/")[0]  # strip model tag
        if base_branch.endswith(" agent"):
            base_branch = base_branch[:-6]
        branch_color = BRANCH_COLORS.get(base_branch, "white")

        # The brackets are meant to be seen: escape the whole group, or a
        # lowercase label is parsed as a tag.
        if pid:
            branch_label = f"{branch}:{pid}"
        else:
            branch_label = branch
        label_text = _plain(f"[{branch_label:<{BRANCH_WIDTH}}]")
        branch_formatted = f"[{branch_color}]{label_text}[/{branch_color}]"

        msg_color = LEVEL_COLORS.get(level, "white")

        console.print(f"[dim]{timestamp}[/dim] {branch_formatted} [{msg_color}]{_plain(message)}[/{msg_color}]")


def print_command_separator(branch: str, command: str, caller: Optional[str] = None, target: Optional[str] = None):
    """
    Print prominent command separator/header with caller attribution.
    """
    with _print_lock:
        branch_color = BRANCH_COLORS.get(branch.lower(), "white")
        console.print()
        console.print(f"[bold {branch_color}]{'─' * 60}[/bold {branch_color}]")

        context_parts = []
        if caller and caller.upper() != "UNKNOWN":
            caller_color = BRANCH_COLORS.get(caller.lower(), "cyan")
            context_parts.append(f"[{caller_color}]{_plain(caller)}[/{caller_color}]")
        if target:
            target_color = BRANCH_COLORS.get(target.lower(), "cyan")
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
        branch_color = BRANCH_COLORS.get(branch.lower(), "white")
        branch_label = f"[{branch_color}]{_plain(branch)}[/{branch_color}]"
        console.print(
            f"[dim]{timestamp}[/dim] [{style}]{symbol} HOOK[/{style}] {branch_label} "
            f"[{style}]{_plain(message)}[/{style}]"
        )
