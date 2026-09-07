# =================== AIPass ====================
# Name: entry_point_diff_content.py
# Description: Entry Point Diff Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
Entry Point Diff Standards Content Handler

Provides formatted entry_point_diff standards content.
Module orchestrates, handler implements.
"""


def get_entry_point_diff_standards() -> str:
    """Return formatted entry_point_diff standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A verb the suite has never once said out loud is a verb nothing",
        "  covers — however green the line-coverage number over the handler",
        "  behind it. Rename it, and every test still passes.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Production is read first and its declared entry points enumerated,",
        "  then diffed against every string literal in the test corpus.",
        "",
        "  [yellow]What counts as a declaration:[/yellow]",
        "  - [green]COMMANDS / HANDLED_COMMANDS / VERBS / SUBCOMMANDS[/green]",
        "    — a tuple, list or set of string literals",
        "  - [green]@route / @get / @post / @put / @patch / @delete[/green]",
        "  - [green]@websocket[/green] — the route string is argument 0",
        "",
        "  [yellow]What counts as a mention:[/yellow]",
        "  - the [bold]whole string literal[/bold] equalling the verb, anywhere",
        "    in the corpus — an argument, a parametrize entry, a fixture table,",
        "    a module-level list. Module level counts; prose does not.",
        "",
        "[bold cyan]IT IS NOT A SUBSTRING SEARCH:[/bold cyan]",
        "  The words [dim]purge-all[/dim] inside a docstring or a comment do",
        "  [bold]not[/bold] acquit [dim]purge-all[/dim]. A substring search over",
        "  raw text is precisely the v4 defect this pack exists to delete — it",
        "  let a file of pattern strings with no code score 94%, and it would",
        "  let any branch clear this rule by writing its verbs into a comment.",
        "  So the rule over-[yellow]convicts[/yellow] on prose rather than",
        "  over-acquitting on a substring: wrong in the direction a human",
        "  dismisses in ten seconds, never in the direction that mints a green",
        "  number nobody earned.",
        "",
        "[bold cyan]WHAT IT CANNOT SEE:[/bold cyan]",
        "  - a verb named only in prose — a false flag, and the deliberate",
        "    direction (see above)",
        '  - a verb assembled at runtime — [dim]f"{prefix}-install"[/dim], a',
        "    dict built in a loop, a registry filled by a plugin group",
        "  - a route reached only through a mounted sub-app (known false positive)",
        "  - a verb shorter than 3 characters — not measured rather than",
        "    measured badly, because a literal match on it means nothing",
        "",
        "[bold cyan]IT READS PRODUCTION, SO IT PUBLISHES ITS HOLES:[/bold cyan]",
        "  A production file that will not parse declares nothing this rule",
        "  can read, so every entry point inside it is a finding that never",
        "  happens — the bias runs toward [yellow]clean[/yellow]. The unread",
        "  count is printed beside the score on every path, because a hole and",
        "  an unread file look identical from outside.",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  Add a test that names the entry point, or delete the entry point.",
        "  [bold]Nothing is deleted by this checker[/bold] — an absence of",
        "  tests is not evidence the code is dead.",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Walks [dim]tests/[/dim] then [dim]test/[/dim]; whole tree if neither.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Declared entry points named by some test / declared entry points.",
        "  [yellow]The denominator is entry points, not test units[/yellow] —",
        "  the finding is an ABSENCE, so no unit is at fault and a per-unit",
        "  score would read 100 forever.",
        "  [yellow]ADVISORY[/yellow] — reports a number, never fails a board.",
        "  A project with no tests, or with no declared entry point, reports",
        "  [dim]not_applicable[/dim]: zero measured is not zero found.",
        "",
        "[bold cyan]EVIDENCE:[/bold cyan]",
        "  Wave 1: [bold]6 unexercised HTTP routes[/bold] over a 97%-covered",
        "  handler lane — the only security-consequential finding in the sweep.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: pytest_quality standards pack (entry_point_diff)[/dim]",
        "  [dim]Checker: entry_point_diff_check.py[/dim]",
        "  [dim]Ported from: TAXONOMY section 5 rule 10[/dim]",
        "  [dim]Design: DPLAN-0323 / FPLAN-0469[/dim]",
    ]

    return "\n".join(lines)
