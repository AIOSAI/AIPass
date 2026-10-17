# =================== AIPass ====================
# Name: plugin_integrity_content.py
# Description: Queryable content for the plugin integrity proof
# Version: 1.0.1
# Created: 2026-03-22
# Modified: 2026-10-17
# =============================================

"""Plugin Integrity Proof Content Handler"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_plugin_integrity_proof() -> str:
    """Return plugin integrity proof content for query system."""
    sep = "\u2500" * 70
    lines = [
        f"[dim]{sep}[/dim]",
        "[bold red]PLUGIN INTEGRITY PROOF \u2014 Dynamic Discovery Contract[/bold red]",
        "[dim]Core audit modules must not hardcode standard names.[/dim]",
        f"[dim]{sep}[/dim]",
        "",
        "[bold cyan]WHAT THIS CHECKS:[/bold cyan]",
        "  Core audit modules must use dynamic discovery (glob + importlib),",
        "  not hardcoded standard names. The plugin architecture depends on it.",
        "",
        "[bold cyan]MODULES SCANNED:[/bold cyan]",
        "  [yellow]\u2022[/yellow] [dim]standards_audit.py[/dim]  \u2014 Runs checker discovery and execution",
        "  [yellow]\u2022[/yellow] [dim]branch_audit.py[/dim]     \u2014 Orchestrates branch-level audits",
        "  [yellow]\u2022[/yellow] [dim]audit_display.py[/dim]    \u2014 Formats and displays audit results",
        "  [yellow]\u2022[/yellow] [dim]seedgo.py[/dim]           \u2014 Main entry point for seedgo",
        "",
        "[bold cyan]WHY IT MATTERS:[/bold cyan]",
        "  The plugin architecture depends on dynamic discovery. When a new standard",
        "  is added (drop a [dim]*_check.py[/dim] file in the pack), it should be automatically",
        "  picked up by glob + importlib. Hardcoded names break this contract:",
        "  [red]\u2717[/red] New standard added but not in the hardcoded list \u2192 silently skipped",
        "  [red]\u2717[/red] Standard renamed but hardcoded ref not updated \u2192 crash or stale results",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]WHAT COUNTS AS HARDCODED:[/bold cyan]",
        "  Any string literal matching a known standard name inside the core modules.",
        "  The scanner uses an AMBIGUOUS_NAMES filter to exclude false positives",
        '  (e.g. "meta", "naming" may appear in non-standard contexts).',
        "",
        "[bold cyan]COSMETIC vs STRUCTURAL:[/bold cyan]",
        "  [yellow]Structural:[/yellow] Standard name used in logic (if/elif chains, dict keys for routing)",
        "  [yellow]Cosmetic:[/yellow]   Standard name in display strings, help text, comments",
        "",
        "  [dim]audit_display.py[/dim] cosmetic refs are a known upgrade target ([dim]DPLAN-0047[/dim]).",
        "  [dim]branch_audit.py[/dim] has 3 legitimate special cases (architecture, meta, testing)",
        "  that require branch-level handling distinct from file-level standards.",
        "",
        "",
        f"[dim]{sep}[/dim]",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  [yellow]1.[/yellow] Replace hardcoded standard names with dynamic iteration over results",
        "  [yellow]2.[/yellow] Use [dim]glob('*_check.py')[/dim] + [dim]importlib.import_module()[/dim] pattern",
        "  [yellow]3.[/yellow] For display: iterate result dicts instead of hardcoding section order",
        "  [yellow]4.[/yellow] For special cases: document why they exist, track in DPLAN-0047",
        "",
        "[bold cyan]RELATED:[/bold cyan]",
        "  [dim]DPLAN-0044: Self-audit tooling design[/dim]",
        "  [dim]DPLAN-0047: audit_display.py cosmetic hardcoding upgrade[/dim]",
        "  [dim]tools/plugin_integrity_scanner.py: Original prototype[/dim]",
        f"[dim]{sep}[/dim]",
    ]

    json_handler.log_operation("proof_content_queried", {"proof": "plugin_integrity"})
    return "\n".join(lines)
