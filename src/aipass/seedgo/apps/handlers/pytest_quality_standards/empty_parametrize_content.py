# =================== AIPass ====================
# Name: empty_parametrize_content.py
# Description: Empty Parametrize Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
Empty Parametrize Standards Content Handler

Provides formatted empty_parametrize standards content.
Module orchestrates, handler implements.
"""


def get_empty_parametrize_standards() -> str:
    """Return formatted empty_parametrize standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A parametrized test over an EMPTY table generates no cases,",
        "  is marked SKIPPED, and the run prints [green]1 passed,[/green]",
        "  [green]1 skipped[/green] with exit code 0. The instrument checked",
        "  nothing and reported the same green a clean tree reports.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Every [dim]@pytest.mark.parametrize[/dim] decorator is read and its",
        "  argvalues expression asked one question: can this be empty?",
        "",
        "  [yellow]VANISHING-TABLE[/yellow] — computed, and unguarded:",
        "  - [red]@pytest.mark.parametrize('item', collect())[/red] in a file",
        "    with no independent non-empty guard anywhere in it",
        "",
        "  [yellow]SHORT-TABLE[/yellow] — computed, guarded only for emptiness:",
        "  - the file's guard asks [dim]did it find anything[/dim], which a",
        "    collector that silently drops ONE entry still satisfies",
        "  - an empty run at least looks odd; a short one looks normal",
        "",
        "[bold cyan]THE ACQUITTALS MATTER MORE THAN THE FLAGS:[/bold cyan]",
        "  - [green]a literal list/tuple/set/dict with elements[/green] — it",
        "    cannot be empty, and it is most of every corpus",
        "  - [green]a module name bound to a non-empty literal[/green]",
        "  - [green]a safe builtin over one of those[/green]:",
        "    [dim]range(24)[/dim], [dim]sorted(WORLDS)[/dim] — one layer",
        "    unwrapped, because following a chain would be an interpreter",
        "  - [green]a file that pins an expected COUNT[/green] — it has",
        "    already done the thing this rule exists to ask for",
        "",
        "[bold cyan]WHAT IT DOES NOT CLAIM:[/bold cyan]",
        "  It does not claim a flagged table is empty. A table legitimately",
        "  empty on some machines — a platform sweep with no rows on this OS —",
        "  is the honest case, and no static reader can tell it from the",
        "  broken one. The guard is matched anywhere in the FILE rather than",
        "  proven to cover the table, and loosely: any len() inside any",
        "  assert counts. Both errors point toward [bold]acquitting[/bold].",
        "  Parametrize on a test CLASS is not read at all.",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  Assert the collection is non-empty in a test of its own, and",
        "  derive that assertion from the [bold]raw data[/bold] rather than",
        "  from the function being judged — a probe that calls the collector",
        "  cannot detect a blinded collector. Better still, pin the expected",
        "  count: only that notices a table one entry short.",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Walks [dim]tests/[/dim] then [dim]test/[/dim]; whole tree if neither.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Units with no vanishing table / total units. Per UNIT, not per",
        "  finding — stacked decorators are one test to go and look at.",
        "  [yellow]ADVISORY[/yellow] — reports a number, never fails a board.",
        "  A project with no tests reports [dim]not_applicable[/dim]: zero",
        "  tests measured is not zero quality found.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: pytest_quality standards pack (empty_parametrize)[/dim]",
        "  [dim]Checker: empty_parametrize_check.py[/dim]",
        "  [dim]Ported from: TAXONOMY section 5 rule 3a nominator[/dim]",
        "  [dim]Design: DPLAN-0323 / FPLAN-0469[/dim]",
    ]

    return "\n".join(lines)
