# =================== AIPass ====================
# Name: host_state_content.py
# Description: Host State Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-08
# Modified: 2026-09-08
# =============================================

"""
Host State Standards Content Handler

Provides formatted host_state standards content.
Module orchestrates, handler implements.
"""


def get_host_state_standards() -> str:
    """Return formatted host_state standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A test may reach the real thing. It may not walk away leaving it",
        "  changed. Patrick's ruling, 2026-09-08: [italic]tests can't disable",
        "  processes, they should restore to exact same state before the test.",
        "  The test is fine and good that it can enter something.[/italic]",
        "  So [bold]touching the host is allowed[/bold]; leaving it changed is",
        "  the defect. This rule is about the restore, never about the reach.",
        "",
        "[bold cyan]WHY IT EXISTS:[/bold cyan]",
        "  A routing test drove [dim]uninstall-timer[/dim] through the real",
        "  [dim]main()[/dim] with nothing patched on the effectful seam. While",
        "  the refusal gate existed the verb never ran; on a red-first run, and",
        "  on every mutation run that removes the gate, production reached",
        "  [red]systemctl --user stop[/red] then [red]disable[/red] and deleted",
        "  the unit files. Measured: daemon-tick.timer stopped 11:46:40 on",
        "  2026-09-07 with no restart, no scheduler tick for 23 hours, and two",
        "  citizens missed their windows.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Every test unit and fixture is read as an AST and asked whether the",
        "  host state it changes is put back.",
        "",
        "  [yellow]Six species:[/yellow]",
        "  - [red]SERVICE_CONTROL[/red] — a subprocess call running",
        "    [dim]systemctl[/dim], [dim]launchctl[/dim], [dim]crontab[/dim] and",
        "    the rest of the service-manager roster",
        "  - [red]PROCESS_SIGNAL[/red] — [dim]os.kill[/dim] / [dim]os.killpg[/dim]",
        "    / [dim]signal.raise_signal[/dim] at a process the unit never started",
        "  - [red]HOME_WRITE[/red] — a pathlib or shutil mutation landing under",
        "    the real home rather than [dim]tmp_path[/dim]",
        "  - [red]ENV_MUTATION[/red] — [dim]os.environ[...] = ...[/dim],",
        "    [dim]del[/dim], [dim]putenv[/dim], [dim]pop/update/clear[/dim]",
        "  - [red]CWD_CHANGE[/red] — a bare [dim]os.chdir[/dim] the process keeps",
        "  - [red]EFFECTFUL_VERB[/red] — a verb DERIVED from the branch's own",
        "    production (a module that reaches host control AND publishes a",
        "    COMMANDS-style constant) driven through a real entry point with",
        "    nothing patched. Derived, never listed: a hardcoded roster of verb",
        "    names goes stale the first time a branch renames one.",
        "",
        "  [yellow]And one fixture species:[/yellow]",
        "  - [red]FIXTURE_NO_TEARDOWN[/red] — a fixture that reaches host state",
        "    and hands it over with nothing after the yield",
        "",
        "[bold cyan]WHAT IS NEVER FLAGGED:[/bold cyan]",
        "  - [green]the seam is patched[/green] — patch / patch.object /",
        "    patch.dict / monkeypatch.setattr naming the call, its module, or",
        "    the module that makes the verb effectful",
        "  - [green]monkeypatch.setenv / delenv / chdir[/green] — pytest",
        "    restores those by contract, on every path. Using them IS the cure",
        "  - [green]a path under tmp_path[/green] — a directory pytest creates",
        "    and removes is not host state",
        "  - [green]a same-file fixture that restores os.environ[/green] after",
        "    its yield, for every unit in that file which requests it",
        "  - [green]a same-file fixture that calls monkeypatch.chdir[/green] —",
        "    it restores the ORIGINAL directory, so a later raw chdir is undone",
        "  - [green]a change undone in the finally[/green] of a try in the same",
        "    unit, for environment and working-directory changes",
        "  - [green]a fixture with a teardown after its yield[/green] — pytest",
        "    runs it when the test fails too; try/finally is not demanded",
        "",
        "[bold cyan]HOW TO FIX, IN THIS ORDER:[/bold cyan]",
        "  1. [bold]Patch the seam[/bold] so the effect never happens. A",
        "     refusal test is about the router's decision, not about systemd.",
        "  2. [bold]Use monkeypatch[/bold] — setenv, delenv, setattr, chdir are",
        "     restored for you, including on the run where your test raises.",
        "  3. When the test must really touch the host, use the",
        "     [bold]snapshot/restore fixture pattern[/bold]: record what was",
        "     there, yield, put it back.",
        "",
        "[bold cyan]THE HARD-KILL LIMIT:[/bold cyan]",
        "  A [dim]finally[/dim] does not run when the process is killed. A",
        "  SIGKILL skips teardown, so [bold]no in-process restore is a",
        "  guarantee[/bold] — not a finally, not a yield fixture, not",
        "  monkeypatch. That is why the pattern lands its snapshot as a",
        "  DOCUMENT under [dim]tmp_path[/dim] and writes the restore",
        "  [bold]idempotent[/bold] — run it twice, same result — so a later run",
        "  can finish an interrupted one.",
        "",
        "[bold cyan]A --help IN THE ARGV IS NOT AN ACQUITTAL:[/bold cyan]",
        "  It only saves the machine if production's help gate fires before the",
        "  work does, and relying on a guard inside production is precisely the",
        "  reliance that failed here.",
        "",
        "[bold cyan]WHAT IT CANNOT SEE — ALL TOWARD FEWER FLAGS:[/bold cyan]",
        "  It does not follow calls, so an effect or a restore in a helper or",
        "  another file is invisible. A runtime-assembled argv is not read. A",
        "  verb whose module publishes no command set is not derived. A restore",
        "  in a conftest or an atexit hook is invisible. A flagged site may be",
        "  safe for a reason the reader can see and the checker cannot.",
        "  [bold]It nominates. A human decides.[/bold]",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Walks [dim]tests/[/dim] then [dim]test/[/dim]; whole tree if neither.",
        "  Reads production too — that is where the dangerous verbs come from.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Subjects not flagged / all subjects — units [bold]and[/bold] fixtures,",
        "  counted per subject: a unit carrying three species is one unit to",
        "  go and read, not three.",
        "  [yellow]ADVISORY[/yellow] — reports a number, never fails a board.",
        "  A project with no tests reports [dim]not_applicable[/dim]: zero",
        "  tests measured is not zero quality found.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: pytest_quality standards pack (host_state)[/dim]",
        "  [dim]Checker: host_state_check.py[/dim]",
        "  [dim]Design: DPLAN-0323 / FPLAN-0525[/dim]",
    ]

    return "\n".join(lines)
