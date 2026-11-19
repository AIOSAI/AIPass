# =================== AIPass ====================
# Name: fallback_content.py
# Description: Fallback Standards Content Handler
# Version: 1.1.0
# Created: 2026-11-14
# Modified: 2026-11-17
# =============================================

"""
Fallback Standards Content Handler
"""

from aipass.sentry.apps.handlers.json import json_handler


def get_fallback_standards() -> str:
    """Return formatted fallback standards content with Rich markup"""
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A fallback answers a failure with a stand-in. Use one only when absolutely necessary,",
        "  then waive that one site with a bypass row that says why. A log line is not a waiver.",
        "",
        "[bold cyan]THE SHAPES:[/bold cyan] an except that does not raise, exit, show or carry the failure:",
        "  [red]import-failure stand-in[/red]            [red]unreadable file read as a default[/red]",
        "  [red]check that cannot run reads as passed[/red]",
        "  [red]disguised: best effort, graceful, legacy, compat[/red]",
        "  [red]default with no warning-level log[/red]   and [red]if not shutil.which(...): return[/red]",
        "",
        "[bold cyan]NOT FLAGGED:[/bold cyan] continue/break only, FileNotFoundError alone, a warning-level",
        "  log with none of the first four shapes (silent_catch and logged_fallback judge those).",
        "  ProcessLookupError alone around a kill/killpg/send_signal: no such process is the answer.",
        "  FileNotFoundError alone around one stat/lstat/getsize/getmtime: no such file is the answer.",
        "",
        "[bold cyan]REVIEW RULE, NOT A CHECK:[/bold cyan] dict.get default, env-or-default, a helper that",
        "  swallows, a boolean's polarity in a check. Ask: if this default is used, does anyone find out?",
        "",
        "[bold cyan]WAIVERS:[/bold cyan] one row per site (lines/functions) plus a reason.",
        "  Whole-file rows waive nothing.",
        "",
        "[bold cyan]SCORING:[/bold cyan] ADVISORY: scored per file, never in the branch average.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]Raise. If the fallback is necessary, waive that one site and say why.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "fallback"})
    return "\n".join(lines)
