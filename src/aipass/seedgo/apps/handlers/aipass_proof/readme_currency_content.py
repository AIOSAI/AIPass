# =================== AIPass ====================
# Name: readme_currency_content.py
# Description: Queryable content for the README currency proof
# Version: 1.0.1
# Created: 2026-03-22
# Modified: 2026-10-17
# =============================================

"""README Currency Proof Content Handler"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_readme_currency_proof() -> str:
    """Return README currency proof content for query system."""
    sep = "\u2500" * 70
    lines = [
        f"[dim]{sep}[/dim]",
        "[bold red]README CURRENCY PROOF \u2014 Documentation Accuracy[/bold red]",
        "[dim]README.md must reflect actual pack state at all times.[/dim]",
        f"[dim]{sep}[/dim]",
        "",
        "[bold cyan]WHAT THIS CHECKS:[/bold cyan]",
        "  [yellow]1.[/yellow] Checker count in README matches actual [dim]*_check.py[/dim] file count",
        "  [yellow]2.[/yellow] All standards in the pack are documented in the README",
        "  [yellow]3.[/yellow] No stale references to removed or renamed standards",
        "",
        "[bold cyan]WHY IT MATTERS:[/bold cyan]",
        "  A stale README misleads everyone about what the pack actually contains.",
        "  Branches query README to understand pack coverage. Humans read it to",
        "  orient themselves. Wrong counts and missing standards erode trust.",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]COMMON FAILURES:[/bold cyan]",
        "",
        "[yellow]Wrong checker count:[/yellow]",
        '  [red]\u2717[/red] README says "24 standards" but pack has 26 [dim]*_check.py[/dim] files',
        "  [green]\u2713[/green] Count matches actual glob of [dim]*_check.py[/dim]",
        "",
        "[yellow]Undocumented standards:[/yellow]",
        "  [red]\u2717[/red] [dim]stderr_routing_check.py[/dim] exists but README never mentions it",
        "  [green]\u2713[/green] Every checker has a corresponding entry in the README",
        "",
        "[yellow]Stale references:[/yellow]",
        "  [red]\u2717[/red] README mentions [dim]diagnostics_check.py[/dim] which was archived",
        "  [green]\u2713[/green] All referenced standards actually exist in the pack",
        "",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  [yellow]1.[/yellow] Update the checker count to match [dim]len(glob('*_check.py'))[/dim]",
        "  [yellow]2.[/yellow] Add entries for all undocumented standards",
        "  [yellow]3.[/yellow] Remove references to standards that no longer exist",
        "",
        "[bold cyan]RELATED:[/bold cyan]",
        "  [dim]DPLAN-0044: Self-audit tooling design[/dim]",
        "  [dim]tools/readme_currency_scanner.py: Original prototype[/dim]",
        f"[dim]{sep}[/dim]",
    ]

    json_handler.log_operation("proof_content_queried", {"proof": "readme_currency"})
    return "\n".join(lines)
