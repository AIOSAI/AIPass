# =================== AIPass ====================
# Name: no_oracle_content.py
# Description: No Oracle Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
No Oracle Standards Content Handler

Provides formatted no_oracle standards content.
Module orchestrates, handler implements.
"""


def get_no_oracle_standards() -> str:
    """Return formatted no_oracle standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A test earns its place by proving something. If it verifies",
        "  nothing, it is a smoke test wearing a test's name — it passes",
        "  until the code raises, and reports green while the behaviour",
        "  it was named for silently rots.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Every test unit is read as an AST and asked one question:",
        "  is there an oracle a reader can see?",
        "",
        "  [yellow]Counts as an oracle (deliberately generous):[/yellow]",
        "  - [green]assert[/green] — anywhere in the unit",
        "  - [green]pytest.raises / warns / fail / approx / xfail[/green]",
        "  - [green]any assert_* method[/green] — unittest and mock spellings",
        "  - [green]a call to a checking helper[/green] — a name starting",
        "    assert/check/verify/expect, because the oracle is one hop away",
        "",
        "[bold cyan]WHY GENEROUS:[/bold cyan]",
        "  A false flag costs a reader thirty seconds. A missed one costs",
        "  nothing visible at all. Being wrong in the generous direction is",
        "  the cheap mistake, so this rule makes it on purpose.",
        "",
        "[bold cyan]IT NOMINATES, IT DOES NOT CONVICT:[/bold cyan]",
        "  A bare trailing call [dim]parse(bad_input)[/dim] with no assert",
        "  really does fail when parse starts accepting bad input. That is a",
        "  [yellow]weak[/yellow] oracle, not an absent one, and static reading",
        "  cannot tell them apart from outside. The flag says: no oracle is",
        "  visible here, and here is what the test calls. A human decides.",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  If the call raising IS the property under test, say so with",
        "  [dim]pytest.raises[/dim]. Otherwise assert the result.",
        "  If the test proves nothing either way, it is a deletion candidate —",
        "  but nothing is deleted by this checker.",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Walks [dim]tests/[/dim] then [dim]test/[/dim]; whole tree if neither.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Units with a visible oracle / total units.",
        "  [yellow]ADVISORY[/yellow] — reports a number, never fails a board.",
        "  A project with no tests reports [dim]not_applicable[/dim]: zero",
        "  tests measured is not zero quality found.",
        "",
        "[bold cyan]REPLACES:[/bold cyan]",
        "  [dim]aipass_standards/test_quality[/dim] v4, which scored by",
        "  searching for 99 pattern substrings over raw text — comments and",
        "  docstrings counted, and a file of patterns with no code scored 94%.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: pytest_quality standards pack (no_oracle)[/dim]",
        "  [dim]Checker: no_oracle_check.py[/dim]",
        "  [dim]Design: DPLAN-0323 / FPLAN-0469[/dim]",
    ]

    return "\n".join(lines)
