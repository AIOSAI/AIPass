# =================== AIPass ====================
# Name: mock_drift_content.py
# Description: Mock Drift Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
Mock Drift Standards Content Handler

Provides formatted mock_drift standards content.
Module orchestrates, handler implements.
"""


def get_mock_drift_standards() -> str:
    """Return formatted mock_drift standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Patch the attribute, never the module. A patched MODULE becomes a",
        "  MagicMock, and a MagicMock answers [bold]every[/bold] attribute",
        "  access that will ever be made of it — including the ones production",
        "  no longer has. Delete the function the test was named for and the",
        "  mock supplies it anyway, silently, forever.",
        "",
        "[bold cyan]THE MEASUREMENT:[/bold cyan]",
        "  Deleting [dim]auth.validate_credentials[/dim] from one branch left",
        "  [bold red]46 of 46 tests green[/bold red]. The suite had no opinion",
        "  about whether the function existed, because not one of those tests",
        "  was ever talking to it.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Every [green]patch(...)[/green] reaching a test unit — decorator or",
        "  context manager — has its dotted target resolved against the files",
        "  the corpus parsed. A target is a MODULE when:",
        "  - it matches the path of a [dim].py[/dim] file in the project, or",
        "  - the file named by its parent segment binds that last segment to a",
        "    module by [dim]import[/dim]",
        "",
        "  [yellow]f-string targets resolve[/yellow] when every interpolation is",
        '  a module-level string constant. [dim]patch(f"{_MOD}.thing")[/dim] is',
        "  the dominant real spelling; a rule that demanded a plain literal",
        "  scored a branch holding 25 module patches as completely clean.",
        "",
        "[bold cyan]WHAT ACQUITS:[/bold cyan]",
        "  - [green]spec=[/green] / [green]spec_set=[/green]",
        "  - [green]autospec=True[/green]",
        "  - [green]new_callable=[/green]",
        "  A specced mock raises on an attribute the real object does not have,",
        "  which is exactly the property whose absence this rule is about.",
        "  A target that resolves to no file is [bold]not[/bold] flagged: the",
        "  rule reports what it can resolve rather than guessing from a name.",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  Patch the attribute, not the module — one line per decorator:",
        '  [red]@patch(f"{_MOD}.json_handler")[/red]',
        '  [green]@patch(f"{_MOD}.json_handler.read_json")[/green]',
        "  Or keep the module target and add [green]autospec=True[/green].",
        "",
        "[bold cyan]WHAT IT DOES NOT CLAIM:[/bold cyan]",
        "  Resolution is by FILE, never by import — this checker does not run",
        "  the project it measures, so a module created at runtime is invisible.",
        "  Class-level [dim]@patch[/dim] decorators are not read. A computed",
        "  target is never flagged. Every one of those is a finding that does",
        "  not happen, so the bias runs toward [yellow]clean[/yellow].",
        "",
        "[bold cyan]IT READS PRODUCTION, SO IT SAYS WHAT IT COULD NOT READ:[/bold cyan]",
        "  A production file that will not parse contributes no module path and",
        "  no import binding. Every result carries a [dim]Production readable[/dim]",
        "  line when that happens — a hole and an unread file look identical",
        "  from the outside, and only the check can tell them apart.",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Walks [dim]tests/[/dim] then [dim]test/[/dim]; whole tree if neither.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Units patching attributes / total units, [bold]deduped per unit[/bold]",
        "  — a unit with four module patches is one place to go and look.",
        "  [yellow]ADVISORY[/yellow] — reports a number, never fails a board.",
        "  A project with no tests reports [dim]not_applicable[/dim]: zero",
        "  tests measured is not zero quality found.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: pytest_quality standards pack (mock_drift)[/dim]",
        "  [dim]Checker: mock_drift_check.py[/dim]",
        "  [dim]Design: DPLAN-0323 / FPLAN-0469[/dim]",
    ]

    return "\n".join(lines)
