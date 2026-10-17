# =================== AIPass ====================
# Name: triplet_content.py
# Description: Queryable content for the triplet proof
# Version: 1.0.1
# Created: 2026-03-22
# Modified: 2026-10-17
# =============================================

"""Triplet Proof Content Handler"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_triplet_proof() -> str:
    """Return triplet proof content for query system."""
    sep = "\u2500" * 70
    lines = [
        f"[dim]{sep}[/dim]",
        "[bold red]TRIPLET PROOF \u2014 Standard File Completeness[/bold red]",
        "[dim]Every standard in a pack must have 3 files.[/dim]",
        f"[dim]{sep}[/dim]",
        "",
        "[bold cyan]WHAT THIS CHECKS:[/bold cyan]",
        "  Every standard must exist as a complete triplet:",
        "  [yellow]1.[/yellow] [dim]{name}_check.py[/dim]  \u2014 The checker (runtime validation)",
        "  [yellow]2.[/yellow] [dim]{name}_content.py[/dim] \u2014 Queryable content (for standards_query)",
        "  [yellow]3.[/yellow] [dim]{name}.md[/dim]          \u2014 Full documentation (for humans)",
        "",
        "[bold cyan]WHY IT MATTERS:[/bold cyan]",
        "  A checker without content means branches can't query the standard to understand it.",
        "  A checker without documentation means humans can't read the full spec.",
        "  Incomplete standards create knowledge gaps in the system.",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]COMMON FAILURES:[/bold cyan]",
        "",
        "[yellow]Check-only standards:[/yellow]",
        "  Checker exists but content and md are missing.",
        "  [red]\u2717[/red] [dim]naming_check.py exists, naming_content.py missing, naming.md missing[/dim]",
        "",
        "[yellow]Orphaned content:[/yellow]",
        "  Content file exists with no matching checker.",
        "  [red]\u2717[/red] [dim]bypass_content.py exists, no bypass_check.py[/dim]",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  [yellow]1.[/yellow] Create the missing [dim]*_content.py[/dim] with a "
        "[dim]get_{name}_standards()[/dim] function",
        "  [yellow]2.[/yellow] Create the missing [dim]*.md[/dim] with full documentation",
        "  [yellow]3.[/yellow] Follow existing triplets as examples:",
        "     [green]\u2713[/green] [dim]architecture_check.py + architecture_content.py + architecture.md[/dim]",
        "",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]RELATED:[/bold cyan]",
        "  [dim]DPLAN-0044: Self-audit tooling design[/dim]",
        "  [dim]tools/triplet_scanner.py: Original prototype[/dim]",
        f"[dim]{sep}[/dim]",
    ]

    json_handler.log_operation("proof_content_queried", {"proof": "triplet"})
    return "\n".join(lines)
