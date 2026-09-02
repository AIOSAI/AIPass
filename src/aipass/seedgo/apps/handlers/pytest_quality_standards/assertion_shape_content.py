# =================== AIPass ====================
# Name: assertion_shape_content.py
# Description: Assertion Shape Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
Assertion Shape Standards Content Handler

Provides formatted assertion_shape standards content.
Module orchestrates, handler implements.
"""


def get_assertion_shape_standards() -> str:
    """Return formatted assertion_shape standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  An assertion that is true of every possible program is worse",
        "  than a missing one. A reader counts it as coverage, a mutant",
        "  walks straight past it, and the test reports green forever.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Every test unit is read as an AST and its assertions are asked",
        "  one question: could this ever say no?",
        "",
        "  [yellow]TAUTOLOGY[/yellow] — per assertion, decided before the run:",
        "  - [red]assert True[/red] / [red]assert 1[/red] / [red]assert 'text'[/red]",
        "  - [red]len(x) >= 0[/red] and [red]len(x) < 0[/red] — every sequence",
        "  - [red]x in (True, False)[/red] — every bool",
        "  - [red]a == a[/red] — both sides are the same expression",
        "",
        "  [yellow]TYPE-ONLY[/yellow] — per UNIT, never per line:",
        "  - the unit's [red]entire[/red] oracle is isinstance checks, so the",
        "    return shape is pinned and the value is not",
        "",
        "  [yellow]OR-ESCAPE[/yellow] — per assertion, deliberately narrow:",
        "  - [red]assert result == [] or isinstance(result, list)[/red] — the",
        "    second clause holds whenever the first does, so there is an exit",
        "",
        "[bold cyan]THE PAIRING RULE:[/bold cyan]",
        "  A type assertion standing [green]beside[/green] a value assertion is",
        "  correct, common, and is never flagged. TYPE-ONLY is a property of",
        "  the unit — getting that backwards would flag the right answer.",
        "",
        "[bold cyan]A CAPABILITY CLAUSE ACQUITS AN or:[/bold cyan]",
        "  [dim]assert not hasattr(signal, 'SIGKILL') or SIGKILL not in handlers[/dim]",
        "  is platform-divergent code, not an escape hatch — the first clause",
        "  asks about the [bold]machine[/bold], not about the result. hasattr,",
        "  sys.platform, os.name, platform.system, sys.version_info and",
        "  shutil.which all acquit.",
        "",
        "[bold cyan]WHAT IT DOES NOT CLAIM:[/bold cyan]",
        "  Not every unfailable assertion — one assembled at runtime from a",
        "  variable is invisible to a static reader, and a helper asserting on",
        "  the unit's behalf is not followed across the call. A flagged unit",
        "  is not a bad test either; a tautology can sit beside four real",
        "  assertions. It nominates. A human decides.",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  Assert the [bold]value[/bold]. If the type matters too, assert both —",
        "  the pairing is what makes it real. If the [dim]or[/dim] is there",
        "  because two answers are genuinely legal, say which, and why.",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Walks [dim]tests/[/dim] then [dim]test/[/dim]; whole tree if neither.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Units with no flagged assertion / total units. Per UNIT, not per",
        "  finding — one sloppy test cannot drive a score below zero.",
        "  [yellow]ADVISORY[/yellow] — reports a number, never fails a board.",
        "  A project with no tests reports [dim]not_applicable[/dim]: zero",
        "  tests measured is not zero quality found.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: pytest_quality standards pack (assertion_shape)[/dim]",
        "  [dim]Checker: assertion_shape_check.py[/dim]",
        "  [dim]Ported from: TAXONOMY section 5 rule 5 nominator[/dim]",
        "  [dim]Design: DPLAN-0323 / FPLAN-0469[/dim]",
    ]

    return "\n".join(lines)
