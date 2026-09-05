# =================== AIPass ====================
# Name: self_skip_content.py
# Description: Self Skip Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
Self Skip Standards Content Handler

Provides formatted self_skip standards content.
Module orchestrates, handler implements.
"""


def get_self_skip_standards() -> str:
    """Return formatted self_skip standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A skip condition must ask the MACHINE, never the SUBJECT. A test",
        "  that skips itself when the thing it tests changes name has stopped",
        "  being a test — rename the symbol and it does not fail, it",
        "  [bold]evaporates[/bold], and the board stays green.",
        "",
        "[bold cyan]THE MEASUREMENT:[/bold cyan]",
        "  Renaming one constant in one branch made [bold red]75 tests silently",
        "  vanish[/bold red] and the run stayed green. Nothing failed, because",
        "  nothing ran, and nothing said so.",
        "",
        "[bold cyan]THREE PROVENANCES, ONE DEFECT:[/bold cyan]",
        "  [green]machine[/green]  sys.platform, sys.version_info, os.name,",
        "            os.environ, shutil.which, find_spec — [bold]correct code[/bold].",
        "            A Linux-only test skipping on Windows is right, and a rule",
        "            that flagged it would teach branches to delete their own",
        "            portability. A machine probe acquits the whole site.",
        "  [red]subject[/red]  the condition asks whether a production symbol",
        "            still EXISTS (hasattr/getattr), or reads a name imported",
        "            from the code under test. [bold]SELF-SKIP / SKIP-ON-DRIFT[/bold].",
        "  [red]nothing[/red]  an unconditional skip. [bold]PERMA-SKIP[/bold] — a test",
        "            that never runs proves nothing, whatever it asserts.",
        "",
        "[bold cyan]THE MODULE SCOPE IS MEASURED:[/bold cyan]",
        "  [dim]pytest.skip(..., allow_module_level=True)[/dim] removes an entire",
        "  FILE and belongs to no test function. That is the shape that took the",
        "  75 tests, so every file carries a [dim]<module>[/dim] scope of its own",
        "  and it is scored like any other.",
        "",
        "[bold cyan]ONE HOP, AND NO FURTHER:[/bold cyan]",
        "  [dim]if not _factory_still_there():[/dim] hides the provenance one",
        "  function away, and a module-level flag hides it in the statement that",
        "  computes it — often a [dim]for[/dim] loop around a [dim]hasattr[/dim],",
        "  not a bare assignment. Both are followed exactly one hop. Chasing an",
        "  arbitrary call graph would make this an interpreter, and an",
        "  interpreter that runs the subject is what this pack refuses to be.",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  Make the condition read the machine:",
        '  [red]@pytest.mark.skipif(not hasattr(mod, "THING"), ...)[/red]',
        '  [green]@pytest.mark.skipif(sys.platform == "win32", ...)[/green]',
        "  If the symbol's absence is the thing worth knowing, [bold]assert it[/bold]",
        "  instead of skipping on it.",
        "",
        "[bold cyan]IT NOMINATES, IT DOES NOT CONVICT:[/bold cyan]",
        "  A suite testing an optional plugin legitimately asks whether the",
        "  plugin is there, and at this distance that is indistinguishable from",
        "  the defect. The rule names the provenance. A human decides.",
        "",
        "[bold cyan]WHAT IT DOES NOT CLAIM:[/bold cyan]",
        "  A condition built at runtime is invisible. So is a skip reached",
        "  through an unrecognised alias, a [dim]skipif(condition=...)[/dim]",
        "  written as a keyword, and a class-level marker. Each is a finding",
        "  that does not happen, so the bias runs toward [yellow]clean[/yellow].",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Walks [dim]tests/[/dim] then [dim]test/[/dim]; whole tree if neither.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Clean scopes / total scopes, where a scope is every test unit",
        "  [bold]plus every file's module scope[/bold]. Deduped per scope: three",
        "  self-skips in one test is one place to go and look. Counting findings",
        "  instead would let one test push a small project below zero.",
        "  [yellow]ADVISORY[/yellow] — reports a number, never fails a board.",
        "  A project with no tests reports [dim]not_applicable[/dim]: zero",
        "  tests measured is not zero quality found.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: pytest_quality standards pack (self_skip)[/dim]",
        "  [dim]Checker: self_skip_check.py[/dim]",
        "  [dim]Design: DPLAN-0323 / FPLAN-0469[/dim]",
    ]

    return "\n".join(lines)
