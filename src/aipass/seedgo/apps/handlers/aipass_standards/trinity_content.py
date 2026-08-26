# =================== AIPass ====================
# Name: trinity_content.py
# Description: Trinity Memory-File Standards Content
# Version: 1.0.0
# Created: 2026-08-25
# Modified: 2026-08-25
# =============================================

"""
Trinity Memory-File Standards Content

Provides formatted standards content for the trinity standard.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_trinity_standards() -> str:
    """Return formatted trinity memory-file standards content."""
    lines = [
        "[bold red]TRINITY STANDARD[/bold red]",
        "",
        "[bold cyan]PURPOSE:[/bold cyan]",
        "",
        "  The canonical shape of every citizen's memory files. A fresh",
        "  agent wakes up inside these files and imitates the shape it",
        "  finds — a drifted file teaches drift. One enforced shape keeps",
        "  memory readable by the machinery that caps, rolls, archives and",
        "  searches it.",
        "",
        "  Scope: [dim].trinity/local.json[/dim], [dim]observations.json[/dim],",
        "  [dim].template_version.json[/dim]. Passports and compass are",
        "  separate systems with their own rules.",
        "",
        "─" * 70,
        "",
        "[bold cyan]THE ONE LAW:[/bold cyan]",
        "",
        "  [bold]A field the checker cannot measure is a VIOLATION,[/bold]",
        "  [bold]never a silent pass.[/bold]",
        "",
        "  This standard exists because the previous gate measured",
        "  unparseable shapes as zero chars and passed them. A list-valued",
        "  [dim]note[/dim] dodged every cap for five months; the agents seen",
        "  being corrected were the healthy ones. Unreadable file, wrong",
        "  type, renamed field, missing config — each fails loud.",
        "",
        "─" * 70,
        "",
        "[bold cyan]WHAT IS CHECKED — nine groups:[/bold cyan]",
        "",
        "  [bold]1. File set[/bold] (10) — exactly passport.json, local.json,",
        "     observations.json, README.md, .template_version.json.",
        "     Stray files and dirs flagged.",
        "  [bold]2. Top-level keys[/bold] (15) — exact set AND order; duplicate",
        "     keys; document_metadata fields. A [dim]status[/dim] block is a",
        "     violation — health is computed, never stored.",
        "  [bold]3. Entry shapes[/bold] (25) — required fields with required",
        "     TYPES, no extras. Heaviest: shape breaks the machinery.",
        "  [bold]4. Ordering & numbering[/bold] (12) — newest-first, strictly",
        "     descending, no reuse. Unnumbered entries are flagged, not",
        "     skipped.",
        "  [bold]5. Char caps[/bold] (12) — measured against the CONFIG, never",
        "     the meta line. An unmeasurable field is a violation.",
        "  [bold]6. Meta lines & _usage[/bold] (10) — byte-match against",
        "     rendered tab + template prose.",
        "  [bold]7. Freshness[/bold] (3) — last_updated ≥ newest entry date.",
        "  [bold]8. Todos hygiene[/bold] (5) — status:done is a violation;",
        "     delete, do not keep.",
        "  [bold]9. Receipt[/bold] (8) — .template_version.json present,",
        "     machine-shaped, versions matching the gold source.",
        "",
        "  Score = weighted sum of per-group subscores. A group holding any",
        "  violation record never scores 100, whatever its denominator.",
        "",
        "─" * 70,
        "",
        "[bold cyan]CANONICAL ENTRY SHAPES:[/bold cyan]",
        "",
        "  [dim]sessions[/dim]       {number:int, date:str, summary:str,",
        "                  status:str} + optional tags:list[str]",
        "  [dim]key_learnings[/dim]  {number:int, date:str, key:str, value:str}",
        "  [dim]todos[/dim]          {number:int, date:str, task:str,",
        "                  priority:str, status:str}",
        "  [dim]observations[/dim]   {number:int, date:str, note:str,",
        "                  tags:list[str]}",
        "",
        "─" * 70,
        "",
        "[bold cyan]FAILURE CASE:[/bold cyan]",
        "",
        "  [red]BAD[/red]  note carries a list — measures as 0 chars, passes",
        "       every cap, renders blank on a phone:",
        "       [dim]{\"note\": [{\"title\": \"...\", \"detail\": \"...\"}]}[/dim]",
        "",
        "  [green]GOOD[/green] note is a string within its configured cap:",
        "       [dim]{\"note\": \"User wants tests run before handover.\",[/dim]",
        "       [dim] \"tags\": [\"verification\"]}[/dim]",
        "",
        "─" * 70,
        "",
        "[bold cyan]NO BYPASS — BY DESIGN:[/bold cyan]",
        "",
        "  Shape rules carry no bypass. A bypassable memory standard",
        "  recreates the drift it exists to end. A branch that genuinely",
        "  needs different numbers gets a per-branch entry in @memory's",
        "  memory.config.json — the one source — not a bypass file.",
        "",
    ]
    content = "\n".join(lines)
    json_handler.log_operation("standard_content_served", {"standard": "trinity"})
    return content
