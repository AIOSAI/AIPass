# =================== AIPass ====================
# Name: progress.py
# Description: Rich progress and glyph helpers for aipass doctor + init
# Version: 1.1.0
# Created: 2026-04-16
# Modified: 2026-10-17
# =============================================

"""
Rich progress and glyph helpers for aipass doctor.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from rich.progress import Progress, SpinnerColumn, TextColumn

from aipass.aipass.apps.handlers.json import json_handler
from aipass.prax import logger

GLYPH_PASS = "[green]✓[/green]"
GLYPH_WARN = "[yellow]![/yellow]"
GLYPH_FAIL = "[red]✗[/red]"


def make_doctor_progress() -> Progress:
    """Return a transient spinner progress bar for doctor checks."""
    logger.info("[progress] creating doctor progress bar")
    json_handler.log_operation("make_doctor_progress", {})
    return Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        transient=True,
    )


@contextmanager
def activity_spinner(description: str) -> Iterator[Progress]:
    """Transient spinner for a blocking action; never a streaming subprocess (the renderers fight)."""
    logger.info("[progress] activity spinner: %s", description)
    json_handler.log_operation("activity_spinner", {"description": description})
    prog = Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True)
    with prog:
        prog.add_task(description, total=None)
        yield prog


def format_check(
    label: str,
    glyph: str,
    detail: str = "",
    remediation: str = "",
) -> str:
    """Format a single doctor check line as Rich markup."""
    parts: list[str] = [f"  {glyph} [bold]{label}[/bold]"]
    if detail:
        parts.append(f" [dim]{detail}[/dim]")
    line = "".join(parts)

    if remediation:
        indent = "      "
        line = f"{line}\n{indent}[dim yellow]{remediation}[/dim yellow]"

    return line


def render_step_header(current: int, total: int, label: str, width: int = 18) -> str:
    """Render a one-line stage header with an inline progress bar.

    A static string, not a live Rich bar, so it composes with the input() prompts between stages.
    """
    total = max(total, 1)
    current = max(0, min(current, total))
    filled = round(width * current / total)
    bar = "█" * filled + "░" * (width - filled)
    return f"[bold cyan]Step {current}/{total}[/bold cyan] [green]{bar}[/green] — [bold]{label}[/bold]"
