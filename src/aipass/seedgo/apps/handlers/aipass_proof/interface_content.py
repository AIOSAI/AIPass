# =================== AIPass ====================
# Name: interface_content.py
# Description: Queryable content for the interface proof
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Interface Proof Content Handler

Provides formatted interface proof content for the query system.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_interface_proof() -> str:
    """Return interface proof content for query system.

    Returns:
        str: Formatted proof text with Rich styling
    """
    sep = "\u2500" * 70
    lines = [
        f"[dim]{sep}[/dim]",
        "[bold red]INTERFACE PROOF \u2014 Checker Interface Compliance[/bold red]",
        "[dim]Every checker must declare AUDIT_SCOPE and use the correct function signature.[/dim]",
        f"[dim]{sep}[/dim]",
        "",
        "[bold cyan]WHAT THIS CHECKS:[/bold cyan]",
        "  [yellow]1.[/yellow] AUDIT_SCOPE variable is declared at module level",
        "  [yellow]2.[/yellow] Function signature matches the expected pattern",
        "  [yellow]3.[/yellow] Parameters match the audit engine's calling convention",
        "",
        "[bold cyan]AUDIT_SCOPE VALUES:[/bold cyan]",
        '  [green]"all_files"[/green]    \u2014 Checker receives every file in the branch',
        '  [green]"entry_point"[/green]  \u2014 Checker receives only the main entry point',
        '  [green]"branch_level"[/green] \u2014 Checker receives the branch root path',
        "",
        "[bold cyan]FUNCTION SIGNATURES:[/bold cyan]",
        "  [yellow]all_files / entry_point:[/yellow] [dim]def check_module(file_path, module_name, branch_path)[/dim]",
        "  [yellow]branch_level:[/yellow]             [dim]def check_branch(branch_path, module_name)[/dim]",
        "",
        "[bold cyan]WHY IT MATTERS:[/bold cyan]",
        "  Without AUDIT_SCOPE, the audit engine can't scope the checker.",
        "  It won't know whether to pass individual files or the branch root.",
        "  Without the correct function signature, the checker crashes at runtime.",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]COMMON FAILURES:[/bold cyan]",
        "",
        "[yellow]Missing AUDIT_SCOPE:[/yellow]",
        "  [red]\u2717[/red] Checker has no AUDIT_SCOPE declaration at all",
        '  [green]\u2713[/green] [dim]AUDIT_SCOPE = "all_files"[/dim]',
        "",
        "[yellow]Wrong function name:[/yellow]",
        "  [red]\u2717[/red] [dim]def check(file_path, module_name, branch_path)[/dim]",
        "  [green]\u2713[/green] [dim]def check_module(file_path, module_name, branch_path)[/dim]",
        "",
        "[yellow]Wrong parameters:[/yellow]",
        "  [red]\u2717[/red] [dim]def check_module(file_path)[/dim]  (missing module_name, branch_path)",
        "  [green]\u2713[/green] [dim]def check_module(file_path, module_name, branch_path)[/dim]",
        "",
        # TODO: Expand with actual validation logic details once the
        # interface scanner is fully implemented.
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        '  [yellow]1.[/yellow] Add [dim]AUDIT_SCOPE = "all_files" | "entry_point" | "branch_level"[/dim]',
        "  [yellow]2.[/yellow] Ensure function matches expected interface:",
        "     [dim]check_module(file_path, module_name, branch_path)[/dim]  for file-level",
        "     [dim]check_branch(branch_path, module_name)[/dim]            for branch-level",
        "",
        "[bold cyan]RELATED:[/bold cyan]",
        "  [dim]DPLAN-0044: Self-audit tooling design[/dim]",
        "  [dim]tools/interface_scanner.py: Original prototype[/dim]",
        f"[dim]{sep}[/dim]",
    ]

    json_handler.log_operation("proof_content_queried", {"proof": "interface"})
    return "\n".join(lines)
