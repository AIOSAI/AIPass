# =================== AIPass ====================
# Name: unentered_assert_content.py
# Description: Unentered Assert Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
Unentered Assert Standards Content Handler

Provides formatted unentered_assert standards content.
Module orchestrates, handler implements.
"""


def get_unentered_assert_standards() -> str:
    """Return formatted unentered_assert standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  An assertion proves nothing until it runs. A test whose only",
        "  assertion sits behind a branch that may never be entered reports",
        "  green whether or not anything was checked — and the run says",
        "  nothing about which of the two happened.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Every test unit is read as an AST and asked one question: can",
        "  any assertion in it be reached without taking a branch?",
        "",
        "  [yellow]VACUOUS-GUARD[/yellow] — every assert sits inside an",
        "  [dim]if[/dim] with no asserting [dim]else[/dim]. One instance in the",
        "  triage corpus was traced to an assertion that had never once run.",
        "",
        "  [yellow]VACUOUS-LOOP[/yellow] — every assert sits inside a",
        "  [dim]for[/dim] with nothing proving the iterable is non-empty. One",
        "  was observed live, passing over an empty directory.",
        "",
        "[bold cyan]NEVER FLAGGED:[/bold cyan]",
        "  - [green]an if that asserts on BOTH arms[/green] — correct",
        "    divergent code; whichever way it falls, something is checked",
        "  - [green]any assert on a path that always runs[/green] — the body",
        "    itself, or a [dim]with[/dim] / [dim]try[/dim] body, which branch",
        "    nothing",
        "  - [green]a loop over a literal collection[/green], or one preceded",
        "    by a floor — [dim]assert rows[/dim], [dim]len(rows) == 3[/dim]",
        "",
        "[bold cyan]WHAT IT DOES NOT CLAIM:[/bold cyan]",
        "  Not that the assertion IS dead — only that nothing in the file",
        "  proves it is alive. A guard on a constant, or a loop whose fixture",
        "  already filled the iterable, reads the same from outside. That is",
        "  a false flag, it costs a reader thirty seconds, and this tier is",
        "  advisory either way.",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  Assert the floor as well as the contents: [dim]assert rows[/dim]",
        "  before the loop, or an [dim]else[/dim] that checks the other case.",
        "  If the guard exists because the case cannot occur here, the honest",
        "  spelling is a [dim]skipif[/dim] with a reason, not a silent pass.",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Walks [dim]tests/[/dim] then [dim]test/[/dim]; whole tree if neither.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Units with no unentered assertion / total units.",
        "  One flag per unit — a unit carrying both shapes is one finding.",
        "  [yellow]ADVISORY[/yellow] — reports a number, never fails a board.",
        "  A project with no tests reports [dim]not_applicable[/dim]: zero",
        "  tests measured is not zero quality found.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: pytest_quality standards pack (unentered_assert)[/dim]",
        "  [dim]Checker: unentered_assert_check.py[/dim]",
        "  [dim]Design: DPLAN-0323 / FPLAN-0469[/dim]",
    ]

    return "\n".join(lines)
