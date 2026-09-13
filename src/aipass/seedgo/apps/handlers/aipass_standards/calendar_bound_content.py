# =================== AIPass ====================
# Name: calendar_bound_content.py
# Description: Calendar Bound Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-13
# Modified: 2026-09-13
# =============================================

"""
Calendar Bound Standards Content Handler

Provides formatted Calendar Bound standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_calendar_bound_standards() -> str:
    """Return formatted calendar_bound standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A test's verdict must be a fact about the code, not about today's date.",
        "  A daemon test asserted a weekly slot's seeded value as a literal while",
        "  the seeder rolled it forward from [yellow]datetime.now()[/yellow]. It was green",
        "  for exactly one week, merged green, and turned [red]red on every host[/red]",
        "  when the calendar moved - every gate had run inside its window.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Parses every [dim]tests/[/dim] and [dim]lib/*/tests/[/dim] Python file and",
        "  convicts a test unit only when ALL THREE legs stand:",
        "",
        "  [red]1. It asserts a date literal[/red]",
        "     An ISO string or [dim]datetime(...)[/dim] / [dim]date(...)[/dim] with integer",
        "     literals, as an operand of an assert comparison or [dim]assertEqual[/dim].",
        "",
        "  [red]2. It reaches code that COMPUTES with the clock[/red]",
        "     Following calls by name from the unit into production (6 hops max),",
        "     a function feeds [dim]datetime.now()[/dim], [dim]date.today()[/dim] or",
        "     [dim]time.time()[/dim] into arithmetic, a comparison, or another call.",
        "     A STAMP is not a derivation: [dim]now().isoformat()[/dim] stored, logged or",
        "     formatted cannot change what another field holds.",
        "",
        "  [red]3. It does not own the clock[/red]",
        "",
        "  [yellow]Owning the clock (acquits, and is the cure):[/yellow]",
        "  - [dim]monkeypatch.setattr(module, 'datetime', Frozen)[/dim] / a [dim]patch[/dim]",
        "    naming datetime, date, time, now, today, clock, freeze or frozen -",
        "    in the unit, its class helpers, or a same-file helper it calls",
        "  - an injected instant: [dim]now=[/dim], [dim]clock=[/dim], [dim]timestamp=[/dim] ...,",
        "    or a [dim]datetime(...)[/dim] literal passed positionally",
        "  - a clock-named fixture parameter ([dim]frozen_now[/dim], [dim]fixed_clock[/dim])",
        "  - [dim]@freeze_time[/dim] / [dim]time_machine[/dim] on the unit or its class",
        "  - an autouse fixture in the file or a conftest.py above it",
        "  A patched call is also cut from the walk.",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "",
        "  [red]Bad -- the expected value is a fact about now:[/red]",
        "  [dim]def test_seeds_the_slot(self):[/dim]",
        "  [dim]    runstate = {'jobs': {}}[/dim]",
        "  [dim]    run_tick()                    # seeder reads datetime.now()[/dim]",
        "  [dim]    assert runstate['jobs'][KEY]['last_run'] == '2026-09-06T03:00:00'[/dim]",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "",
        "  [green]Good -- freeze the clock the code reads:[/green]",
        "  [dim]class Frozen(datetime):[/dim]",
        "  [dim]    @classmethod[/dim]",
        "  [dim]    def now(cls, tz=None):[/dim]",
        "  [dim]        return datetime(2026, 9, 13, 12, 31)[/dim]",
        "  [dim]monkeypatch.setattr(runstate_mod, 'datetime', Frozen)[/dim]",
        "",
        "  [green]Good -- inject the instant:[/green]",
        "  [dim]seed_interval_slot(runstate, job, now=datetime(2026, 9, 13, 12, 31))[/dim]",
        "",
        "  [green]Good -- write the expected value by hand from a calendar, per frozen now[/green]",
        "  [dim]@pytest.mark.parametrize('now,seeded', SLOT_SEED_CASES)[/dim]",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Corpus is [bold]tests/ and lib/*/tests/[/bold]; production is read through the",
        "  tests' own imports under the package root",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  [bold]clean test files / total test files x 100[/bold]",
        "  [green]100[/green] = no date literal asserted against an unfrozen clock",
        "  Reports up to 3 offending file:line rows with descriptions",
        "  A second [dim]passed: True[/dim] line counts units that reach the clock and",
        "  already own it -- context, never scored",
        "  Overall pass threshold: [yellow]75%[/yellow]",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Via [dim].seedgo/bypass.json[/dim] -- supports standard, file-level,",
        "  and line-level bypass rules",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (calendar_bound)[/dim]",
        "  [dim]Checker: calendar_bound_check.py[/dim]",
        "  [dim]Sibling: host_portability (which host a test needs; this is which date)[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "calendar_bound"})
    return "\n".join(lines)
