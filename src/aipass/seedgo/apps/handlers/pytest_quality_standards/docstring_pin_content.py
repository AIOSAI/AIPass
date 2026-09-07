# =================== AIPass ====================
# Name: docstring_pin_content.py
# Description: Docstring Pin Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
Docstring Pin Standards Content Handler

Provides formatted docstring_pin standards content.
Module orchestrates, handler implements.
"""


def get_docstring_pin_standards() -> str:
    """Return formatted docstring_pin standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A test's docstring should name the defect it pins. That rule is",
        "  accepted [bold]structurally only[/bold] — never as a prose match.",
        "",
        "[bold cyan]WHY NOT PROSE:[/bold cyan]",
        "  The standard this pack replaces scored tests by searching for",
        "  pattern substrings, and branches complied by writing the patterns",
        "  into [yellow]comments[/yellow]. A prose version of this rule is that",
        '  same defect one level up: [dim]"Pins the contract that the parser',
        '  rejects malformed input"[/dim] passes a prose matcher while naming',
        "  nothing, proving nothing, and costing the author eight seconds.",
        "",
        "[bold cyan]WHAT IT ACTUALLY CHECKS:[/bold cyan]",
        "  1. Collect every name the unit [green]CALLS[/green].",
        "  2. Pull every identifier and dotted path out of the docstring.",
        "  3. [bold]Anchored[/bold] if any docstring token matches any called",
        "     name — full dotted string or final segment, either direction.",
        "",
        "  [dim]parse[/dim] in prose anchors a call to [dim]mod.parse[/dim].",
        "  [dim]mod.parse[/dim] in prose anchors a call to [dim]parse[/dim].",
        "",
        "[bold cyan]WHAT IT IS FORBIDDEN TO DO:[/bold cyan]",
        "  It never scores on docstring length, word count, sentence count, or",
        "  the presence of words like [dim]pins[/dim], [dim]contract[/dim],",
        "  [dim]defect[/dim], [dim]regression[/dim], [dim]invariant[/dim].",
        "  [yellow]If you find yourself matching prose, you have rebuilt the",
        "  defect this pack exists to delete.[/yellow]",
        "",
        "[bold cyan]SPECIES:[/bold cyan]",
        "  - [red]NO_DOCSTRING[/red] — no docstring node at all; nothing to anchor",
        "  - [red]UNANCHORED_DOCSTRING[/red] — a docstring naming nothing the",
        "    unit calls. An empty docstring lands here: it is present and it",
        "    names nothing, which is exactly what this species is.",
        "",
        "[bold cyan]THE KNOWN FALSE-FLAG FAMILY:[/bold cyan]",
        "  A unit that makes [bold]no call at all[/bold] can never be anchored",
        "  — a test pinning a constant [dim]assert mod.LIMIT == 10[/dim], an",
        "  operator, or an attribute read has no call for this rule to find.",
        "  Every such unit is flagged. The row carries [dim]call_count[/dim] so",
        "  a reader can filter them in one pass.",
        "  The reverse error exists too: a docstring word that happens to equal",
        "  a called name — [dim]raises, open, list, format, next[/dim] — anchors",
        "  a unit by accident. This rule is a [bold]floor, never a ceiling[/bold].",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Walks [dim]tests/[/dim] then [dim]test/[/dim]; whole tree if neither.",
        "",
        "[bold cyan]SCORING — REPORTING, NOT SCORING:[/bold cyan]",
        "  [bold]SCORED = False[/bold] ships the ruling as accepted: structural,",
        "  with an unscored report-line fallback. The full violation list and",
        "  every check line are still returned; the reported score is",
        "  [bold]100[/bold] and the measured number travels in",
        "  [dim]measured_score[/dim] and in a check line naming the fallback.",
        "  A fallback that silently discarded its own measurement would be",
        "  indistinguishable from a rule that found nothing.",
        "  [yellow]ADVISORY[/yellow] — reports, never fails a board.",
        "  A project with no tests reports [dim]not_applicable[/dim].",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: pytest_quality standards pack (docstring_pin)[/dim]",
        "  [dim]Checker: docstring_pin_check.py[/dim]",
        "  [dim]Design: DPLAN-0323 / FPLAN-0469[/dim]",
    ]

    return "\n".join(lines)
