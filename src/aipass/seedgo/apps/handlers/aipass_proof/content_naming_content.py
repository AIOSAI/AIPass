# =================== AIPass ====================
# Name: content_naming_content.py
# Description: Queryable content for the content naming proof
# Version: 1.0.1
# Created: 2026-03-22
# Modified: 2026-10-17
# =============================================

"""Content Naming Proof Content Handler"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_content_naming_proof() -> str:
    """Return content naming proof content for query system."""
    sep = "\u2500" * 70
    lines = [
        f"[dim]{sep}[/dim]",
        "[bold red]CONTENT NAMING PROOF \u2014 Function Name Convention[/bold red]",
        "[dim]Every *_content.py must have get_{name}_standards() matching its filename.[/dim]",
        f"[dim]{sep}[/dim]",
        "",
        "[bold cyan]WHAT THIS CHECKS:[/bold cyan]",
        "  Each content file [dim]{name}_content.py[/dim] must export a function named",
        "  [dim]get_{name}_standards()[/dim] that the standards_query module can call.",
        "",
        "[bold cyan]THE NAMING CONVENTION:[/bold cyan]",
        "  [yellow]File:[/yellow]     [dim]architecture_content.py[/dim]",
        "  [yellow]Function:[/yellow] [dim]get_architecture_standards()[/dim]",
        "",
        "  [yellow]File:[/yellow]     [dim]imports_content.py[/dim]",
        "  [yellow]Function:[/yellow] [dim]get_imports_standards()[/dim]",
        "",
        "  [yellow]File:[/yellow]     [dim]log_handler_content.py[/dim]",
        "  [yellow]Function:[/yellow] [dim]get_log_handler_standards()[/dim]",
        "",
        "[bold cyan]WHY IT MATTERS:[/bold cyan]",
        "  The [dim]standards_query[/dim] module calls this exact function name to retrieve",
        "  content. It derives the function name from the filename:",
        "  [dim]{name}_content.py[/dim] \u2192 [dim]get_{name}_standards()[/dim]",
        "",
        "  Wrong name = query fails silently. The standard appears to have no",
        "  content even though the file exists.",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]COMMON FAILURES:[/bold cyan]",
        "",
        "[yellow]Wrong function name:[/yellow]",
        "  [red]\u2717[/red] [dim]def get_architecture_content()[/dim]  \u2014 wrong suffix",
        "  [red]\u2717[/red] [dim]def get_arch_standards()[/dim]        \u2014 abbreviated name",
        "  [green]\u2713[/green] [dim]def get_architecture_standards()[/dim]",
        "",
        "[yellow]Missing function entirely:[/yellow]",
        "  [red]\u2717[/red] File exists but has no function matching the convention",
        "",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  [yellow]1.[/yellow] Extract the standard name from the filename: "
        "[dim]{name}_content.py[/dim] \u2192 [dim]{name}[/dim]",
        "  [yellow]2.[/yellow] Ensure the file contains: [dim]def get_{name}_standards() -> str:[/dim]",
        "  [yellow]3.[/yellow] Verify the function returns a string of formatted content",
        "",
        "[bold cyan]RELATED:[/bold cyan]",
        "  [dim]DPLAN-0044: Self-audit tooling design[/dim]",
        "  [dim]tools/content_naming_scanner.py: Original prototype[/dim]",
        f"[dim]{sep}[/dim]",
    ]

    json_handler.log_operation("proof_content_queried", {"proof": "content_naming"})
    return "\n".join(lines)
