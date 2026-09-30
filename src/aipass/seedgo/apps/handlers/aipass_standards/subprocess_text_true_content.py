# =================== AIPass ====================
# Name: subprocess_text_true_content.py
# Description: Subprocess Text True Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""
Subprocess Text True Standards Content Handler

Provides formatted Subprocess Text True standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_subprocess_text_true_standards() -> str:
    """Return formatted subprocess_text_true standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A subprocess call in text mode with no encoding decodes the child's output with",
        "  the locale encoding: UTF-8 on Linux and macOS, cp1252 on Windows. The same hazard",
        "  as named_encoding, one pipe over; named_encoding never looks at subprocess.",
        "",
        "[bold cyan]THE SHAPE:[/bold cyan]",
        "  [red]subprocess.run / Popen / check_output / check_call / call[/red] with",
        "  [red]text=True[/red] or [red]universal_newlines=True[/red]",
        "  and no [green]encoding=[/green] (or encoding=None).",
        "  Reported on the text= line. Aliases are followed: import subprocess as sp,",
        "  from subprocess import run. errors= alone is not a cure.",
        "",
        "[bold cyan]NOT CONVICTED:[/bold cyan]",
        "  [yellow]encoding=[/yellow] named  [yellow]text=False[/yellow] or no flag",
        "  [yellow]text=flag[/yellow] (not a literal)",
        "  [yellow]**kwargs[/yellow]  a mock's assert_called_with(text=True)  a wrapper's callers.",
        "",
        "[bold cyan]CHECK FIRST (2026-09-25):[/bold cyan]",
        "  598 test files. [red]52 convicted, 115 hits[/red] across all 18 branches, every one",
        "  subprocess.run(text=True). 0 text-mode calls name an encoding. The model file passes.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit on ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        '  [green]Pass encoding="utf-8" (and errors= if the child may print non-utf-8 bytes).[/green]',
    ]

    json_handler.log_operation("content_served", {"standard": "subprocess_text_true"})
    return "\n".join(lines)
