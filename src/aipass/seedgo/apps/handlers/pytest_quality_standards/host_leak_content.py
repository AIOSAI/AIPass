# =================== AIPass ====================
# Name: host_leak_content.py
# Description: Host Leak Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-15
# Modified: 2026-09-15
# =============================================

"""
Host Leak Standards Content Handler

Provides formatted host_leak standards content.
Module orchestrates, handler implements.
"""


def get_host_leak_standards() -> str:
    """Return formatted host_leak standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A test that pretends to be somewhere else must [bold]manufacture the",
        "  whole of that elsewhere[/bold]. The moment a faked world takes one",
        "  value from the host it is really running on, the fake is half real —",
        "  and the real half is the half that differs between runners.",
        "",
        "[bold cyan]THE ROW IT WAS WRITTEN FOR:[/bold cyan]",
        "  @ai_mail forced [dim]sys.platform = 'darwin'[/dim], then built the fake",
        "  [dim]lsof[/dim] line it feeds the parser out of [dim]tmp_path[/dim]:",
        '  [red]stdout = f"p100\\nn{target}\\n"[/red]',
        "  The parser accepts one grammar — [dim]line.startswith('n/')[/dim]. On",
        "  the Windows runner [dim]tmp_path[/dim] renders [dim]C:\\Users\\...[/dim],",
        "  the [dim]n/[/dim] prefix never appeared, and [bold red]the unit could",
        "  not parse the line the unit itself had written[/bold red]",
        "  (run 35058244702). Nothing was wrong with the code under test.",
        "",
        "[bold cyan]THE ACQUITTAL, THREE LINES ABOVE THE DEFECT:[/bold cyan]",
        "  [dim]test_get_pid_cwd_linux[/dim] fakes the platform and binds the same",
        "  [dim]str(tmp_path / 'project')[/dim] — and is perfectly portable:",
        "  [green]monkeypatch.setattr(os, 'readlink', lambda p: target)[/green]",
        "  It hands the host path to the subject as a [bold]value[/bold] and gets",
        "  it back unchanged. The darwin row wove it into [bold]text[/bold], beside",
        "  a literal, and the literal was a POSIX grammar. That is the difference,",
        "  and it is the whole rule.",
        "",
        "[bold cyan]THE LITERAL IS THE GRAMMAR:[/bold cyan]",
        '  [red]f"n{target}"[/red]  a protocol line with a host path dropped in.',
        '  [green]f"{target}"[/green]  is [dim]str(target)[/dim] spelled longer, and',
        "  claims nothing about shape. An empty literal never counts.",
        "",
        "[bold cyan]WHAT IT MEASURED:[/bold cyan]",
        "  18 branches, 18,997 units: [bold]zero rows[/bold] — the one row it",
        "  exists for was cured hours before it shipped. The two looser arms were",
        "  measured first and rejected: a platform fake beside any host value is",
        "  [yellow]23 rows[/yellow], all correct code; a host path woven into text",
        "  with no platform fake is [yellow]223 rows[/yellow], all correct code.",
        "  Each half is harmless. [bold]Only the pair is the species.[/bold]",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  Write the elsewhere down. Fake data is [bold]DATA the subject reads[/bold],",
        "  not a directory the host has to own:",
        '  [red]target = str(tmp_path / "project")[/red]',
        '  [green]target = "/private/var/folders/aipass/pytest-project"[/green]',
        "  If the value must be real, stop faking the platform around it.",
        "",
        "[bold cyan]IT NOMINATES, IT DOES NOT CONVICT:[/bold cyan]",
        "  Whether a woven host path is a defect depends on [bold]production[/bold]:",
        "  a subject that PARSES the text goes red, a subject that passes the value",
        "  through stays green. This reader walks test units and does not follow",
        "  calls, so it names the site where the host got into the fake world and",
        "  leaves the parser to a human.",
        "",
        "[bold cyan]WHAT IT DOES NOT CLAIM:[/bold cyan]",
        "  Composition inside a fixture, a helper or another file is invisible, and",
        "  so is a class-level or module-level mark. It never asks the running",
        "  machine — a finding means the same thing from either leg of the matrix,",
        "  which is the property the thing it hunts destroys. Every limit runs",
        "  toward [yellow]fewer[/yellow] flags.",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Walks [dim]tests/[/dim] then [dim]test/[/dim]; whole tree if neither.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  [bold]It does not score.[/bold] SCORED is False: an arm with zero measured",
        "  rows has never been observed against a live positive, so its precision on",
        "  real hits is unmeasured. It publishes the full finding list and the",
        "  measured number, and reports 100. This is a [bold]regression guard[/bold],",
        "  not a finder.",
        "  [yellow]ADVISORY[/yellow] — reports a number, never fails a board.",
        "  A project with no tests reports [dim]not_applicable[/dim]: zero tests",
        "  measured is not zero quality found.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: pytest_quality standards pack (host_leak)[/dim]",
        "  [dim]Checker: host_leak_check.py[/dim]",
        "  [dim]Design: DPLAN-0323 / FPLAN-0469 · cure: FPLAN-0593 Phase 5[/dim]",
    ]

    return "\n".join(lines)
