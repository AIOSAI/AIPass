# =================== AIPass ====================
# Name: posix_literal_content.py
# Description: Posix Literal Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
Posix Literal Standards Content Handler

Provides formatted posix_literal standards content.
Module orchestrates, handler implements.
"""


def get_posix_literal_standards() -> str:
    """Return formatted posix_literal standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A rooted path literal put through a resolver is an assertion",
        "  about one platform, written as if it were about all of them.",
        '  [dim]Path("/tmp").resolve()[/dim] is [green]/tmp[/green] on POSIX and',
        "  [yellow]D:\\tmp[/yellow] under ntpath, because a rooted literal is",
        "  DRIVE-RELATIVE there — so the assertion underneath accuses code",
        "  that is working perfectly.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Every test unit is read as an AST and asked where its rooted",
        "  literals go.",
        "",
        "  [yellow]Flagged:[/yellow]",
        '  - [red]Path("/tmp").resolve()[/red] — a path CONSTRUCTOR over a',
        "    rooted literal, with resolve() called on it",
        '  - [red]os.path.realpath("/tmp")[/red] / [red]abspath[/red] — a',
        "    resolver function over a rooted literal",
        "",
        "  [yellow]Not flagged:[/yellow]",
        '  - [green]registry.resolve("/tmp", ...)[/green] — any other object\'s',
        "    resolve(); a branch-name lookup shares the verb and nothing else",
        '  - [green]Path("logs").resolve()[/green] — a relative fragment',
        "    carries no platform claim",
        "  - [green]tmp_path / os.sep[/green] — a path that was derived,",
        "    not written down",
        "",
        "[bold cyan]WHY THE RECEIVER AND NOT THE NAME:[/bold cyan]",
        "  Measured over 721 test files before the rule existed: keying on",
        "  the method NAME found 10 sites and [yellow]six of them were a",
        "  branch-name resolver[/yellow] holding a literal it never resolves.",
        "  Keyed on the receiver it nominates none of those. A rule with that",
        "  acquittal rate is one a fleet learns to ignore inside a week.",
        "",
        "[bold cyan]IT NOMINATES, IT DOES NOT CONVICT:[/bold cyan]",
        "  A test that deliberately exercises POSIX spelling — a fence",
        "  refusing [dim]/etc/passwd[/dim] — is a legitimate site and stays.",
        "  What the flag buys is that the decision gets [bold]made[/bold]",
        "  rather than inherited from whichever platform the author was",
        "  standing on.",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  Derive the path from [dim]tmp_path[/dim] or [dim]os.sep[/dim], or",
        "  state the claim out loud: parametrise both dialects, or assert on",
        "  [dim]Path.parts[/dim] rather than on a spelling. Where the literal",
        "  IS the subject, keep it and say so.",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Walks [dim]tests/[/dim] then [dim]test/[/dim]; whole tree if neither.",
        "",
        "[bold cyan]LIMITS — ALL TOWARD FEWER FLAGS:[/bold cyan]",
        "  Reads the RECEIVER, so a literal handed through a variable is not",
        "  seen. Walks TEST UNITS, so a fixture or module-level literal is not",
        "  seen. Nothing here follows a call.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Units with no resolved rooted literal / total units, counted",
        "  [bold]per unit[/bold] — four literals in one test is one unit to",
        "  go and read, not four.",
        "  [yellow]ADVISORY[/yellow] — reports a number, never fails a board.",
        "  A project with no tests reports [dim]not_applicable[/dim]: zero",
        "  tests measured is not zero quality found.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: pytest_quality standards pack (posix_literal)[/dim]",
        "  [dim]Checker: posix_literal_check.py[/dim]",
        "  [dim]Design: DPLAN-0323 / FPLAN-0469[/dim]",
    ]

    return "\n".join(lines)
