# =================== AIPass ====================
# Name: json_handler_content.py
# Description: JSON Handler Integrity Standards Content
# Version: 1.2.0
# Created: 2026-06-14
# Modified: 2026-09-03
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
        "  [bold]1. Handler capability[/bold] (one must be true, best first):",
        "    [green]a)[/green] IS the canonical shim — sha256 of the file equals the",
        "       bytes pinned in DPLAN-0325 section 3. Checked by identity, so a",
        "       shim cannot drift by one character without saying so.",
        "    [green]b)[/green] Binds the one json service and carries no branch tokens",
        "       [dim]from aipass.prax import json_handler[/dim]",
        "       [dim](transitional — retires when the fleet sweep completes)[/dim]",
        "    [green]c)[/green] Wires the retiring shared JsonHandler:",
        "       [dim]from aipass.aipass.shared.json_handler import JsonHandler[/dim]",
        "    [green]d)[/green] Standalone with triplet surface:",
        "       [dim]def ensure_module_jsons(...)[/dim]",
        "       [dim]def ensure_json_exists(...)[/dim]",
        "",
        "  [bold]2. Template capability[/bold] (only where a template ships):",
        "    A branch shipping [dim]templates/citizen/apps/handlers/json/[/dim]",
        "    [dim]json_handler.py[/dim] has it judged by the same rule. Nothing",
        "    audited that file before, so every newborn inherited whatever",
        "    shape it had.",
        "",
        "  [bold]3. Disk triplet completeness[/bold] (bidirectional):",
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
        "  Replace the forked handler with the canonical shim — the same bytes",
        "  in every branch, copied from DPLAN-0325 section 3, never retyped:",
        "",
        "  [dim]from aipass.prax import json_handler[/dim]",
        "  [dim]_h = json_handler.for_module(__file__)[/dim]",
        "  [dim]log_operation = _h.log_operation[/dim]",
        "  [dim]ensure_module_jsons = _h.ensure_module_jsons[/dim]",
        "  [dim]# ... bind the remaining public names ...[/dim]",
        "",
        "  It BINDS, never wraps. A [dim]def[/dim] wrapper adds one frame, and the",
        "  service reads the calling module at that depth to name the document",
        "  it writes — so a wrapping shim sends every log to the wrong file.",
        "",
        "─" * 70,
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "",
        "  Percentage of the checks that passed; 75% is the gate. Most branches",
        "  run three checks (exists / capability / disk triplets), so the ladder",
        "  is 100 / 66 / 33 / 0. A branch shipping the citizen template runs a",
        "  fourth, and its ladder is 100 / 75 / 50 / 25 / 0.",
        "",
        "  [green]100[/green] — every check passed",
        "  [yellow] 66[/yellow] — handler capable, disk triplets incomplete",
        "  [red]  33[/red] — log-only fork (cannot create triplets)",
        "  [red]   0[/red] — no handler file and no disk triplets",
        "  [green]100[/green] — bypassed via .seedgo/bypass.json",
    ]
    json_handler.log_operation("standard_content_queried", {"standard": "json_handler"})
    return "\n".join(lines)
