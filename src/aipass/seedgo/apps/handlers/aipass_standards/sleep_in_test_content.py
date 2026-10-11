# =================== AIPass ====================
# Name: sleep_in_test_content.py
# Description: Sleep In Test Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Sleep In Test Standards Content Handler

Provides formatted Sleep In Test standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_sleep_in_test_standards() -> str:
    """Return formatted sleep_in_test standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (crack class N, template v1 item 23):[/bold cyan]",
        "  A sleep inside a test. It is always one of two mistakes, and both are",
        "  curable without waiting.",
        "",
        "[bold cyan]A SLEEP TO MOVE AN MTIME:[/bold cyan]",
        "  On a filesystem with one-second timestamp granularity a 0.01s nudge does",
        "  not move the mtime at all, so the test goes red for a reason that has",
        "  nothing to do with the product. On a coarse or loaded host a 1.1s sleep is",
        "  simply 1.1s of the suite's life, repeated.",
        "  Cure: [green]os.utime(path, (when, when))[/green] — exact, instant, every filesystem.",
        "",
        "[bold cyan]A SLEEP TO WAIT FOR SOMETHING:[/bold cyan]",
        "  A fixed sleep is a bet that the machine is fast enough today. Flaky on a",
        "  loaded CI box, slow on a fast one.",
        "  Cure: [green]a deadline poll on the REAL condition[/green] — read the flag, join the",
        "  thread with a timeout. Faster, and honest about what it waits for.",
        "",
        "[bold cyan]MATCH THROUGH THE ALIAS, NOT THROUGH time.sleep:[/bold cyan]",
        "  The whole implementation lesson. The rule is 'a call whose name is sleep',",
        "  because the fleet spells the module four different ways:",
        "    [green]time.sleep(0.01)[/green]          35 hits",
        "    [green]_time.sleep(0.05)[/green]          5     @prax test_watcher",
        "    [green]time_module.sleep(0.01)[/green]    2     @hooks test_engine",
        "    [green]time_mod.sleep(0.1)[/green]        1     @ai_mail test_dispatch_monitor",
        "",
        "  Matching time.sleep and a bare sleep found 14 files / 35 hits and [red]silently",
        "  missed eight[/red]. Matching the call's tail name found all of them.",
        "",
        "[bold cyan]CHECK FIRST (2026-09-22, 565 fleet test files):[/bold cyan]",
        "  [green]17 files, 43 hits[/green] — the review's first cut exactly, once aliases count.",
        "  Every hit is scored. There is no legitimate form: both shapes above have a",
        "  cure that is strictly better.",
        "  Evidence lands: test_versioned_engine.py 89, 110, 126, 240, 315, 441.",
        "",
        "[bold cyan]WHY IT CANNOT BE SATISFIED BY ACCIDENT:[/bold cyan]",
        "  A sleep asserts nothing. It can only make the suite slower, or make it",
        "  pass on one machine and fail on another.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit names the line and how the call is spelled, on",
        "  ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]os.utime for an mtime, a deadline poll on the real condition for an event.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "sleep_in_test"})
    return "\n".join(lines)
