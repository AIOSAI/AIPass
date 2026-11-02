# =================== AIPass ====================
# Name: readme_quality_content.py
# Description: README Quality Standards Content Handler
# Version: 1.0.0
# Created: 2026-07-17
# Modified: 2026-11-02
# =============================================

"""
README Quality Standards Content Handler

Provides formatted README quality standards content.
Module orchestrates, handler implements.
"""

from aipass.sentry.apps.handlers.json import json_handler


def get_readme_quality_standards() -> str:
    """Return formatted README quality standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold red]README QUALITY STANDARD[/bold red]",
        "",
        "[bold cyan]CORE RULE:[/bold cyan] READMEs must be accessible to strangers",
        "",
        "[yellow]RULE:[/yellow] AIPass is open source. A stranger cloning the repo should",
        "  understand what each branch does, how to invoke it, and be able to",
        "  get started from the README alone -- no insider knowledge required.",
        "",
        "[dim]Note: This standard checks CONTENT QUALITY. The existing 'readme'",
        "standard checks STRUCTURAL completeness (sections, tree, links).",
        "Both must pass.[/dim]",
        "",
        "=" * 70,
        "",
        "[bold cyan]WHAT IS CHECKED:[/bold cyan]",
        "",
        "  [yellow]Scope:[/yellow] entry_point -- derives README from branch root",
        "",
        "  [yellow]Check 1:[/yellow] quick_start",
        "    README has a Quick Start / Getting Started section containing",
        "    at least one fenced code block with a runnable command.",
        "",
        "  [yellow]Check 2:[/yellow] stranger_accessible",
        "    First 5 content lines must not reference more than 2 internal",
        "    AIPass branch names. Strangers cannot parse insider jargon.",
        "",
        "  [yellow]Check 3:[/yellow] invoke_match",
        "    If an Invoke/Usage section exists, the command shown must",
        "    reference the correct branch name.",
        "",
        "  [yellow]Check 4:[/yellow] what_description",
        "    README must describe what the branch does within the first",
        "    10 lines (at least one content line longer than 20 characters).",
        "",
        "=" * 70,
        "",
        "[bold cyan]THE STRANGER TEST:[/bold cyan]",
        "",
        "  Imagine someone who has never seen AIPass before. They clone the",
        "  repo and open your README. Can they answer:",
        "",
        "  [green]1.[/green] What does this branch do? (what_description)",
        "  [green]2.[/green] How do I run it? (quick_start + invoke_match)",
        "  [green]3.[/green] Do I need to know other branches first? (stranger_accessible)",
        "",
        "  If any answer is 'no', the README fails the stranger test.",
        "",
        "=" * 70,
        "",
        "[bold cyan]INTERNAL BRANCH NAMES (checked in stranger_accessible):[/bold cyan]",
        "",
        "  drone, devpulse, aipass, ai_mail, flow, sentry, prax, memory,",
        "  spawn, hooks, trigger, api, cli, skills, daemon, commons, backup",
        "",
        "  [dim]Using more than 2 of these in your opening lines without context",
        "  makes the README insider-only.[/dim]",
        "",
        "=" * 70,
        "",
        "[bold cyan]GOOD EXAMPLE:[/bold cyan]",
        "",
        "  # Flow",
        "  Plan lifecycle manager for AIPass. Creates, tracks, and closes",
        "  development plans across the project.",
        "",
        "  ## Quick Start",
        "  ```",
        "  drone @flow create . 'My Plan'",
        "  drone @flow list",
        "  ```",
        "",
        "[bold cyan]BAD EXAMPLE:[/bold cyan]",
        "",
        "  # AIPASS",
        "  Concierge and librarian for AIPass. Greets new users, walks them",
        "  through setup via drone, hands off to devpulse, integrates with",
        "  sentry, prax, and spawn for system health.",
        "  [red](5 internal names in opening lines -- stranger cannot follow)[/red]",
        "",
        "=" * 70,
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "",
        "  1. Add a Quick Start section with a runnable code block",
        "  2. Rewrite opening lines to explain what it does in plain terms",
        "  3. Ensure Invoke/Usage section matches the real CLI entry point",
        "  4. Write as if the reader has never seen AIPass before",
        "",
        "=" * 70,
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Score = (passed_checks / 4) * 100",
        "  Pass requires all 4 checks green",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: sentry standards pack (readme_quality)[/dim]",
        "  [dim]Complements: readme standard (structural completeness)[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "readme_quality"})
    return "\n".join(lines)
