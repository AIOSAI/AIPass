# =================== AIPass ====================
# Name: json_handler_content.py
# Description: JSON Handler Integrity Standards Content
# Version: 1.1.0
# Created: 2026-06-14
# Modified: 2026-08-07
# =============================================

"""
JSON Handler Integrity Standards Content

Provides formatted standards content for the json_handler standard.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_json_handler_standards() -> str:
    """Return formatted json_handler integrity standards content."""
    lines = [
        "[bold red]JSON_HANDLER STANDARD[/bold red]",
        "",
        "[bold cyan]PURPOSE:[/bold cyan]",
        "",
        "  Catches silent handler drift. Every branch must have a",
        "  json_handler.py that can create the full config/data/log",
        "  triplet — not a stripped log-only fork.",
        "",
        "─" * 70,
        "",
        "[bold cyan]WHAT IS CHECKED:[/bold cyan]",
        "",
        "  [bold]1. Handler capability[/bold] (one must be true):",
        "    [green]a)[/green] Wires the shared JsonHandler:",
        "       [dim]from aipass.aipass.shared.json_handler import JsonHandler[/dim]",
        "    [green]b)[/green] Standalone with triplet surface:",
        "       [dim]def ensure_module_jsons(...)[/dim]",
        "       [dim]def ensure_json_exists(...)[/dim]",
        "",
        "  [bold]2. Disk triplet completeness[/bold] (bidirectional):",
        "    Any [dim]{module}_config.json[/dim], [dim]{module}_data.json[/dim] or",
        "    [dim]{module}_log.json[/dim] in [dim]{branch}_json/[/dim] implies the",
        "    other two must exist. Checking log files only would let a",
        "    hand-written config with no log sibling stay invisible.",
        "    [dim]Bypass a deliberate gap with standard 'json_handler' and the[/dim]",
        "    [dim]missing file path, e.g. {branch}_json/{module}_data.json.[/dim]",
        "",
        "─" * 70,
        "",
        "[bold cyan]FAILURE CASE:[/bold cyan]",
        "",
        "  A handler that only defines [dim]log_operation()[/dim] without",
        "  [dim]ensure_module_jsons[/dim] or [dim]ensure_json_exists[/dim]",
        "  can only create log files. Config and data files never appear,",
        "  making the branch log-only even though json_structure passes.",
        "",
        "─" * 70,
        "",
        "[bold cyan]FIX:[/bold cyan]",
        "",
        "  Replace the forked handler with the shared shim (35 lines):",
        "",
        "  [dim]from aipass.aipass.shared.json_handler import JsonHandler[/dim]",
        "  [dim]_handler = JsonHandler(json_dir=_BRANCH_ROOT / '{branch}_json')[/dim]",
        "  [dim]log_operation = _handler.log_operation[/dim]",
        "  [dim]ensure_module_jsons = _handler.ensure_module_jsons[/dim]",
        "  [dim]# ... re-export all public functions ...[/dim]",
        "",
        "─" * 70,
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "",
        "  [green]100[/green] — Handler capable + disk triplets complete",
        "  [yellow] 66[/yellow] — Handler capable but disk triplets incomplete",
        "  [red]  33[/red] — Log-only fork (cannot create triplets)",
        "  [red]   0[/red] — No handler file + no disk triplets",
        "  [green]100[/green] — Bypassed via .seedgo/bypass.json",
    ]
    json_handler.log_operation("standard_content_queried", {"standard": "json_handler"})
    return "\n".join(lines)
