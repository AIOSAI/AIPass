# =================== AIPass ====================
# Name: capture_never_read_content.py
# Description: Capture Never Read Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
Capture Never Read Standards Content Handler

Provides formatted capture_never_read standards content.
Module orchestrates, handler implements.
"""


def get_capture_never_read_standards() -> str:
    """Return formatted capture_never_read standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A test that arranges to SEE something and then never looks",
        "  proves nothing about what was printed. The fixture costs a",
        "  line of source, so requesting it is a declaration of intent —",
        "  and an unread capture is that intent abandoned.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Every test unit is read as an AST and asked two questions.",
        "",
        "  [yellow]CAPTURE-NEVER-READ[/yellow] — the exact static tell:",
        "  - the signature takes [red]capsys[/red] / [red]capfd[/red]",
        "    (or the binary spellings) and the body never calls",
        "    [red]readouterr()[/red] anywhere",
        "  - the fixture does nothing at all unless it is read, so this",
        "    is a leftover from a deleted assertion or a test never finished",
        "",
        "  [yellow]RECEIPT-ONLY[/yellow] — per UNIT, and only when SOLE:",
        "  - the unit's [red]entire[/red] oracle is [red]is True[/red] or",
        "    [red]== 0[/red] on a [dim]print_* / show_* / report_* /[/dim]",
        "    [dim]render_* / display_* / emit_*[/dim] call",
        "  - the return value is a receipt saying the call happened, not",
        "    evidence that anything was printed correctly",
        "",
        "[bold cyan]SOLE IS THE SPECIES:[/bold cyan]",
        "  A receipt standing [green]beside[/green] any other assertion, or",
        "  beside any [green]assert_*[/green] mock call, is never flagged. A",
        "  predicate under test — where the boolean [bold]is[/bold] the",
        "  behaviour — is never flagged either. Getting this backwards would",
        "  convict a large family of correct tests.",
        "",
        "[bold cyan]WHAT IT DOES NOT CLAIM:[/bold cyan]",
        "  It does not follow calls: a unit handing capsys to a helper that",
        "  reads it IS flagged, and that flag is wrong. It does not cover",
        "  [dim]caplog[/dim] — that fixture is read by touching .records or",
        "  .text, ordinary attribute access this mechanism cannot tell from",
        "  any other. And the output-prefix list is a measured under-count:",
        "  receipts on a [dim]router[/dim] are missed, because widening the",
        "  prefixes to catch routers would catch every predicate under test.",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  Read what you captured: [dim]assert capsys.readouterr().out[/dim]",
        "  contains what you expected. If the output does not matter, drop",
        "  the fixture from the signature — it is costing a reader a",
        "  question with no answer. If the return value is genuinely the",
        "  behaviour, assert what was emitted beside it.",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Walks [dim]tests/[/dim] then [dim]test/[/dim]; whole tree if neither.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Units that read what they asked for / total units. Per UNIT, not",
        "  per finding — a score that can go negative is believed once.",
        "  [yellow]ADVISORY[/yellow] — reports a number, never fails a board.",
        "  A project with no tests reports [dim]not_applicable[/dim]: zero",
        "  tests measured is not zero quality found.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: pytest_quality standards pack (capture_never_read)[/dim]",
        "  [dim]Checker: capture_never_read_check.py[/dim]",
        "  [dim]Ported from: TAXONOMY section 5 rule 8 nominator[/dim]",
        "  [dim]Design: DPLAN-0323 / FPLAN-0469[/dim]",
    ]

    return "\n".join(lines)
