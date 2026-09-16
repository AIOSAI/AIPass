# =================== AIPass ====================
# Name: startup_budget_content.py
# Description: Startup Budget Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-15
# Modified: 2026-09-15
# =============================================

"""
Startup Budget Standards Content Handler

Provides formatted startup_budget standards content.
Module orchestrates, handler implements.
"""


def get_startup_budget_standards() -> str:
    """Return formatted startup_budget standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Every grounding layer has one job, one cap, and one owner. Growth",
        "  is authored against a number, and the number is a boundary the",
        "  system can read. Nothing measured the greeting until this rule —",
        "  every context regression so far was found by a human reading a",
        "  percentage on a status line.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Six files per branch, in [bold]CHARACTERS[/bold], each against the",
        "  cap its OWNER publishes:",
        "",
        "  [yellow]file[/yellow]                             [yellow]cap[/yellow]        [yellow]owner[/yellow]",
        "  [dim]README.md[/dim]                        10,000     [green]seedgo[/green] (this pack's pack.json)",
        "  [dim].aipass/aipass_local_prompt.md[/dim]    9,000     [green]hooks[/green]  (BRANCH_CHAR_BUDGET)",
        "  [dim].trinity/local.json[/dim]              25,000     [green]memory[/green] (memory.config.json)",
        "  [dim].trinity/observations.json[/dim]       15,000     [green]memory[/green] (memory.config.json)",
        "  [dim].trinity/passport.json[/dim]       6,000 + 600    [green]memory[/green] (file + per string)",
        "  [dim]DASHBOARD.local.json[/dim]             6,000      [green]prax[/green]   (DASHBOARD_CHAR_BUDGET)",
        "",
        "[bold cyan]CHARS, NEVER BYTES, NEVER TOKENS:[/bold cyan]",
        "  [dim]len(path.read_text(encoding='utf-8'))[/dim] — the number",
        "  [dim]wc -m[/dim] reports. A README of 23,478 chars is 23,498 bytes;",
        "  a rule quoting the second number measures the encoding, not the",
        "  greeting. The boardroom corrected bytes-for-chars three times in",
        "  one afternoon, so it is written into the rule.",
        "",
        "[bold cyan]READ, NEVER COPIED:[/bold cyan]",
        "  Five of the six caps belong to another branch. The checker reads",
        "  the owner's name off the owner's live module (or config) on every",
        "  call and carries no copy of any of them. Move a cap at its owner",
        "  and the next audit moves — nothing in seedgo is edited.",
        "  [dim]external_inputs()[/dim] names those owner files so the",
        "  incremental cache re-scores the fleet when one of them changes.",
        "",
        "[bold cyan]FAIL HONESTLY:[/bold cyan]",
        "  A cap that cannot be read is an [red]ERROR[/red] row naming the",
        "  owner and the missing thing. Never a default, never a remembered",
        "  number, never a silent pass. trinity's law applied to borrowed",
        "  numbers: an auditor that substitutes its own number is no longer",
        "  measuring the contract.",
        "",
        "[bold cyan]ABSENT IS NOT ZERO:[/bold cyan]",
        "  [dim].trinity/[/dim] and [dim]DASHBOARD.local.json[/dim] are",
        "  gitignored and a branch may not have a dashboard yet. A missing",
        "  file is reported [yellow]absent[/yellow] and leaves its group's",
        "  denominator — never 0 chars (a silent pass), never a violation (a",
        "  blamed branch). A branch with none of the six reports",
        "  [dim]not_applicable[/dim].",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Never opens [dim]apps/[/dim]. Six files, nothing else.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Weighted groups: README 30, Branch prompt 25, Trinity files 25,",
        "  Dashboard 20. Each group is proportional over the files actually",
        "  present; a group with nothing present is not scored and its weight",
        "  is shared across the rest.",
        "  [yellow]ADVISORY[/yellow] — reports a number, gates nothing. A",
        "  checker that moved in one commit put 17 of 18 branches red on",
        "  2026-09-13; the ruling is advisory first, then a per-file ratchet",
        "  in CI once the numbers have a week behind them.",
        "",
        "[bold cyan]WHAT IT DOES NOT CLAIM:[/bold cyan]",
        "  Not tokens. Not the injected kernel, navmap or identity block.",
        "  Not the true cost of a greeting — six files, no more. It never",
        "  judges what is IN a file, and it never writes one: the diet is",
        "  owner-run and this is only the scoreboard.",
        "",
        "[bold cyan]THE FLEET TABLE:[/bold cyan]",
        "  [green]drone @seedgo audit context[/green]          [dim]# every branch, one row each[/dim]",
        "  [green]drone @seedgo audit context @flow[/green]     [dim]# one branch[/dim]",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: context standards pack (startup_budget)[/dim]",
        "  [dim]Checker: startup_budget_check.py[/dim]",
        "  [dim]Design: DPLAN-0347 / FPLAN-0593, boardroom thread 16[/dim]",
        "  [dim]README cap 10,000 ruled by Patrick 2026-09-15 16:02[/dim]",
    ]

    return "\n".join(lines)
