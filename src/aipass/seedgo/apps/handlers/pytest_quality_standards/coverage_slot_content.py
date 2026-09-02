# =================== AIPass ====================
# Name: coverage_slot_content.py
# Description: Coverage Slot Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
Coverage Slot Standards Content Handler

Provides formatted coverage_slot standards content.
Module orchestrates, handler implements.
"""


def get_coverage_slot_standards() -> str:
    """Return formatted coverage_slot standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A test that says out loud why it exists — and the reason is not",
        "  the behaviour — has already told you what it is. Nobody writes",
        '  [dim]"added for coverage"[/dim] about a test they believe in.',
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Docstrings and full-line comments inside each test unit, against",
        "  PURPOSIVE phrases — the ones that state a REASON:",
        "",
        '  - [red]"for coverage"[/red] / [red]"coverage slot"[/red]',
        '  - [red]"to satisfy"[/red] / [red]"satisfies the checker"[/red]',
        '  - [red]"the standard requires"[/red] / [red]"seedgo requires"[/red]',
        '  - [red]"keeps X honest"[/red]',
        '  - [red]"placeholder test"[/red] / [red]"boilerplate test"[/red]',
        '  - [red]"exists only because the checker"[/red]',
        "",
        "[bold cyan]PHRASES, NEVER WORDS:[/bold cyan]",
        '  [green]"the coverage report lists every file"[/green] is a SUBJECT.',
        '  [red]"added for coverage"[/red] is a CONFESSION. The naive grep —',
        "  the bare word [dim]coverage[/dim] anywhere — flags a suite about",
        "  checkers dozens of times over, and a rule that noisy is one people",
        "  switch off. Word boundaries are anchored too, so",
        '  [green]"before coverage runs"[/green] is prose.',
        "",
        "[bold cyan]WHERE IT LOOKS — AND WHERE IT DOES NOT:[/bold cyan]",
        "  Docstrings and full-line comments inside the unit. [yellow]Not[/yellow]",
        "  arbitrary string literals: a test whose DATA contains the phrase is",
        "  testing a string, not confessing. Lines inside triple-quoted blocks",
        "  are excluded by reading the parsed tree, so a [dim]#[/dim] in sample",
        "  content is never mistaken for a comment.",
        "",
        "[bold cyan]IT NOMINATES, IT DOES NOT CONVICT:[/bold cyan]",
        "  A flag is never a licence to delete. A confessing test can still be",
        "  the last thing standing between a rename and a broken release. If",
        "  the behaviour matters, [bold]say what it is and assert it[/bold].",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Walks [dim]tests/[/dim] then [dim]test/[/dim]; whole tree if neither.",
        "",
        "[bold cyan]LIMITS — STATED, NOT PAPERED OVER:[/bold cyan]",
        "  A coverage slot written [bold]without[/bold] confessing is invisible",
        "  here, by construction. That is not a gap to close with heuristics —",
        "  it is the boundary that keeps every hit meaning something.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Units that state a behaviour / total units, counted [bold]per",
        "  unit[/bold] — three confessions in one docstring is one confessing",
        "  test.",
        "  [yellow]ADVISORY[/yellow] — reports a number, never fails a board.",
        "  A project with no tests reports [dim]not_applicable[/dim]: zero",
        "  tests measured is not zero quality found.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: pytest_quality standards pack (coverage_slot)[/dim]",
        "  [dim]Checker: coverage_slot_check.py[/dim]",
        "  [dim]Design: DPLAN-0323 / FPLAN-0469[/dim]",
    ]

    return "\n".join(lines)
