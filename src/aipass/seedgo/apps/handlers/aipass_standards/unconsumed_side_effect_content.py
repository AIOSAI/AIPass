# =================== AIPass ====================
# Name: unconsumed_side_effect_content.py
# Description: Unconsumed Side Effect Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-23
# Modified: 2026-09-23
# =============================================

"""
Unconsumed Side Effect Standards Content Handler

Provides formatted Unconsumed Side Effect standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_unconsumed_side_effect_standards() -> str:
    """Return formatted unconsumed_side_effect standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (crack class F):[/bold cyan]",
        "  A test queues several answers for a mock and never checks they were all",
        "  taken.",
        "    [red]drive_api.side_effect = [{'files': []}, {'id': 'new'}, {'name': 'Backups'}][/red]",
        "  A list of three says the product will call this mock three times. Nothing",
        "  in the test says so. If the product calls it twice, the third answer is",
        "  never consumed, the test still passes, and whatever branch that answer was",
        "  written to feed is unpinned — deletable, with the suite green.",
        "",
        "[bold cyan]THE CURE IS ONE LINE:[/bold cyan]",
        "  [green]assert mock.call_count == 3[/green], or [green]assert_has_calls([...])[/green] when the arguments",
        "  matter. Either one turns the list's length from a hope into a claim.",
        "",
        "[bold cyan]ACQUITTED:[/bold cyan]",
        "  The test asserts the mock's calls — call_count, assert_called / assert_",
        "  called_once / assert_called_with and their kin, assert_has_calls, mock_calls,",
        "  call_args, assert_not_called, and the await_ forms. [green]9 of the fleet's 26.[/green]",
        "",
        "[bold cyan]SCORED:[/bold cyan]",
        "  The mock is never mentioned in any assertion in the test. [green]17.[/green]",
        "",
        "[bold cyan]COUNTED, NOT CHARGED:[/bold cyan]",
        "  The mock is asserted some OTHER way — its return value reaches an assert,",
        "  say — so the test is watching it, just not counting it. Zero in this fleet",
        "  today; the bucket is here because the shape is legitimate and the count",
        "  should be ready when it appears.",
        "",
        "[bold cyan]NEVER JUDGED:[/bold cyan]",
        "  A list of ONE. A single queued answer is a return value spelled differently,",
        "  and there is no unconsumed tail to lose.",
        "",
        "[bold cyan]CHECK FIRST (2026-09-23, 572 fleet test files):[/bold cyan]",
        "  [green]5 files, 17 scored, 0 counted, 9 acquitted.[/green]",
        "  Lengths among the judged: 2 eleven times, 3 five times, 4 once.",
        "",
        "[bold cyan]WHY IT CANNOT BE SATISFIED BY ACCIDENT:[/bold cyan]",
        "  The list's length is an assertion the test declines to make. The fix is",
        "  additive — one more assert — and no threshold exists to tune.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit names the line, the mock and how many answers",
        "  it was queued, on ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]assert mock.call_count, or assert_has_calls when the arguments matter.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "unconsumed_side_effect"})
    return "\n".join(lines)
