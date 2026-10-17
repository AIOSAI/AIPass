# =================== AIPass ====================
# Name: template_content.py
# Description: Template Standards Content Handler
# Version: 1.0.0
# Created: 2026-07-01
# Modified: 2026-10-17
# =============================================

"""
Template Standards Content Handler

Provides formatted template standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_template_standards() -> str:
    """Return formatted template standards content with Rich markup."""
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Branches should not run with un-configured template files.",
        "  Spawn creates scaffolding from templates — but those templates",
        "  must be filled in by the branch owner. Un-configured stubs are",
        "  a silent failure: the branch runs fine but gets wrong prompts,",
        "  generic READMEs, or placeholder identity.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Scans key branch files for template markers that indicate the",
        "  file was never configured after spawn:",
        "",
        "  [yellow]Target files:[/yellow]",
        "  - [dim].aipass/aipass_local_prompt.md[/dim] — branch prompt",
        "  - [dim]README.md[/dim] — branch documentation",
        "  - [dim].trinity/*.json[/dim] — identity files",
        "",
        "  [yellow]Definitive markers (all file types):[/yellow]",
        "  - [red]NEEDS CONFIGURATION[/red]",
        "  - [red]{{BRANCHNAME}}[/red] / [red]{{BRANCH}}[/red]",
        "  - [red]INSTRUCTIONS FOR FILLING OUT THIS TEMPLATE[/red]",
        "  - [red]WHEN YOU'RE DONE[/red]",
        "",
        "  [yellow]Markdown-only markers (.md files):[/yellow]",
        "  - Single-curly placeholders: [dim]{role}[/dim], [dim]{command1}[/dim]",
        "",
        "[bold cyan]SEVERITY:[/bold cyan]",
        "  [yellow]Advisory (WARNING)[/yellow] — never fails the audit.",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  Open the flagged file and replace template markers with real",
        "  content. The spawn template shows which sections need filling.",
        "",
        "  Intentional exception? Add a bypass in [dim].seedgo/bypass.json[/dim]:",
        '  [dim]{"file":"<path>","standard":"template","reason":"..."}[/dim]',
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  One check per target file. Score dips per flagged file.",
        "  Audit still [green]passes[/green] regardless (advisory).",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Via [dim].seedgo/bypass.json[/dim] — standard + file-level",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (template)[/dim]",
        "  [dim]Checker: template_check.py[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "template"})
    return "\n".join(lines)
